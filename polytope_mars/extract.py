"""Block extraction loop: sliced request tree -> :mod:`polytope_mars.blocks` -> encoder bytes.

Per request (:meth:`BlockExtractor.stream`):

1. the :class:`~polytope_mars.blocks.RequestHeader` is built from the parsed request alone and the
   encoder's ``begin()`` bytes are yielded before any datacube work;
2. the datacube is created, the request sliced once and ``FDBDatacube.prepare`` puts the tree into its
   final point order;
3. :mod:`polytope_mars.coverage_plan` enumerates the field groups in legacy coverage order;
4. MultiPoint groups are extracted one *unit* at a time: the largest run of consecutive
   groups that fits ``limits.memory_budget_bytes`` in one ``datacube.get`` with param/levelist and the
   group axes compressed (:mod:`polytope_mars.tree_units`), one group per call when there is no budget,
   and one (param, level) at a time when a whole group does not fit.  A *field* is never split: one that
   does not fit the budget on its own is refused (:meth:`BlockExtractor._refuse_field`).  Point features
   (PointSeries, VerticalProfile, Trajectory) are small: the whole prepared tree is fetched with one
   ``datacube.get`` and cut into groups afterwards;
5. ``CoordsBlock``, ``ValuesBlock`` per (param, level), ``GroupEnd``.

Missing fields.  gribjump reports a field it has no GRIB message for in one of two ways:
an empty result for that path, or (the remote gribjump, i.e. production) a ``GribJumpException`` whose
message contains ``DataNotFound`` for the whole ``extract`` call (:func:`is_data_not_found`).  The first is
read from the filled tree; on the second the unit that raised is re-fetched in smaller pieces so that the
fields that exist are kept and the missing ones omitted exactly as with empty results:

* whole-group unit -> per (param, level), each field fetched whole: a call asking for one field that
  raises ``DataNotFound`` says that this field is missing;
* whole tree of a point feature -> per param, then per (group, param), then per level.

The re-fetches only happen when data is missing; ``timings`` counts them (``n_fallbacks``) and the fields
found missing (``n_missing_fields``).  Any other exception propagates unchanged.

``RequestHeader.extra`` (read by the CovJSON encoder):

* ``"pointseries_order": "series_major"`` (only for class=ce stream=efas timeseries): legacy ordered those
  coverages by forecast run first, then by point.

Group ``mars_metadata`` is the legacy coverage metadata (keys and order) computed by the plan; for point
features it is the metadata of the coverage the group's instant belongs to, and consecutive groups with
equal ``mars_metadata`` and ``levels`` form one coverage series.
"""

from __future__ import annotations

import logging
import math
import re
import resource
import sys
import time
from typing import Any, Iterator

import numpy as np

from . import bulk_tree
from .blocks import (
    CoordsBlock,
    FieldGroup,
    GroupEnd,
    ParamInfo,
    RequestHeader,
    ValuesBlock,
)
from .coverage_plan import (
    GroupPlan,
    TreeInfo,
    analyse_tree,
    make_plan,
    spatial_children,
)
from .field_stream import (
    GroupAssembler,
    has_per_field_consumption,
    lazy_unit_fields,
    unit_field_source,
    whole_unit_fields,
)
from .limits import format_bytes, tree_byte_limit
from .sizing import DEFAULT_FRAGMENT_BYTES, UnitSizing
from .tree_units import GroupSpec, plan_units, prune_values, unit_select

__all__ = ["BlockExtractor", "collect_field_values", "is_data_not_found", "slice_request"]

logger = logging.getLogger(__name__)


def is_data_not_found(exc: BaseException) -> bool:
    """True for gribjump's "fields missing" error: a ``GribJumpException`` whose message has ``DataNotFound``.

    The class is matched by name over the exception's MRO, so neither pygribjump nor its C library has to be
    importable here.  The remote gribjump raises it for the whole ``extract`` call, e.g.
    ``DataNotFound. Matched 1 fields but 2 were requested.``, when the union of the call's requests matches
    fewer fields than were requested.
    """
    return any(cls.__name__ == "GribJumpException" for cls in type(exc).__mro__) and "DataNotFound" in str(exc)


_MATCHED_NONE = re.compile(r"\bMatched 0 fields\b")


def matched_no_field(exc: BaseException) -> bool:
    """True when a DataNotFound error says that no field of the call exists (``Matched 0 fields but ...``).

    Then every field of the unit is missing and nothing needs to be re-fetched; when the message cannot be
    read the unit is split up as for a partial match.
    """
    return bool(_MATCHED_NONE.search(str(exc)))


class _UnitPartiallyMissing(Exception):
    """gribjump has some but not all fields of a unit: re-fetch it in smaller pieces."""


def max_rss_bytes() -> int:
    """Peak resident set size of this process so far, in bytes (``ru_maxrss``).

    Reported in ``timings`` so that production logs can be held against the planner's estimate.
    Observation only: no decision in polytope-mars reads the RSS, a cgroup or any other runtime
    signal; the planner is a pure function of (request, config, tree).
    """
    try:
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except (OSError, ValueError, AttributeError):  # pragma: no cover - not on Linux/macOS
        return 0
    return peak if sys.platform == "darwin" else peak * 1024


def slice_request(api, preq):
    """``Polytope.retrieve`` without the ``datacube.get``: the sliced request tree."""
    datacube = api.datacube
    datacube.check_branching_axes(preq)
    api.switch_polytope_dim(preq)
    for polytope in preq.polytopes():
        if polytope.method == "nearest":
            k = polytope.k
            key = tuple(polytope.axes())
            if polytope.is_flat:
                if datacube.nearest_search.get(key, None) is None:
                    datacube.nearest_search[key] = (polytope.values, k)
                else:
                    datacube.nearest_search[key][0].append(polytope.values[0])
            else:
                if datacube.nearest_search.get(key, None) is None:
                    datacube.nearest_search[key] = (polytope.points, k)
                else:
                    datacube.nearest_search[key][0].append(polytope.points[0])
    return api.slice(datacube, preq.polytopes())


# --- reading coordinates and values from (prepared / filled) trees ---------------------------------------
#
# Every spatial sub-tree of a prepared tree is one array-backed bulk node (:mod:`polytope_mars.bulk_tree`):
# its coordinates, its grid indexes and one result array per field of the call are arrays, so none of the
# readers below holds anything per point.


def _spatial_points(node):
    """``(lat, lon)`` of one spatial sub-tree, in output order (views on the node's coordinates)."""
    return bulk_tree.coordinates(node)


def spatial_nodes(info: TreeInfo, branches) -> list:
    """The bulk spatial nodes of ``branches``, in tree order: one per spatial sub-tree."""
    return [child for b in branches for child in spatial_children(info.branches[b].node)]


def group_coordinates(info: TreeInfo, branches):
    """lat/lon of every point of a group, in output order."""
    points = [_spatial_points(node) for node in spatial_nodes(info, branches)]
    if not points:
        return np.empty(0), np.empty(0)
    if len(points) == 1:
        return points[0]
    return np.concatenate([lat for lat, _ in points]), np.concatenate([lon for _, lon in points])


def spatial_counts(info: TreeInfo, branches) -> list:
    """Points per spatial sub-tree over ``branches``, in tree order."""
    return [bulk_tree.point_count(node) for node in spatial_nodes(info, branches)]


def collect_field_values(tree, key_axes) -> dict:
    """Split the results of a filled tree into fields.

    Returns ``{key: (values float64 array, missing bool)}`` with ``key = tuple(field value of axis for axis
    in key_axes)`` (None for axes absent from a branch).  A field is ``missing`` when gribjump had no
    message for it (every value None); bitmap-missing points come back as NaN.

    A bulk spatial node holds one result array per field of the call, in the ``itertools.product`` order of
    the compressed axes above it, which is the order ``keys`` is built in.
    """
    info = analyse_tree(tree)
    chunks: dict = {}
    for branch in info.branches:
        axes = [a for a, _ in branch.path]
        combos = list(np.ndindex(*[len(v) for _, v in branch.path])) if branch.path else [()]
        keys = []
        for combo in combos:
            values = {a: branch.path[i][1][j] for i, (a, j) in enumerate(zip(axes, combo))}
            keys.append(tuple(values.get(a) for a in key_axes))
        for node in spatial_children(branch.node):
            results = bulk_tree.field_results(node, len(keys))
            for key, values in zip(keys, results):
                chunks.setdefault(key, []).append(values)
    out = {}
    for key, parts in chunks.items():
        arr = np.concatenate([np.asarray(p) for p in parts]) if len(parts) != 1 else np.asarray(parts[0])
        missing = False
        if arr.dtype == object:
            # gribjump had no message for a field: its values are None (astype turns them into NaN)
            missing = arr.size > 0 and all(v is None for v in arr)
        out[key] = (arr.astype(np.float64), missing)
    return out


#: Upper edges (seconds) of the per-unit ``get`` histogram reported in ``timings``.
GET_BUCKETS = ((1.0, "le_1s"), (5.0, "le_5s"), (30.0, "le_30s"), (math.inf, "gt_30s"))


class _Counters:
    def __init__(self):
        self.n_groups = 0
        self.n_units = 0
        self.groups_per_unit_max = 0
        #: fields one ``datacube.get`` fetched at most (what the call cost gribjump)
        self.fields_per_unit_max = 0
        #: spatial sub-trees (bulk nodes) the request walks
        self.n_spatial_subtrees = 0
        self.n_gribjump_calls = 0
        self.n_missing_fields = 0
        self.n_fallbacks = 0
        self.get_seconds = 0.0
        #: slowest single unit, and how the units are spread over the buckets (Splunk, no DEBUG)
        self.get_seconds_max = 0.0
        self.get_buckets = {name: 0 for _, name in GET_BUCKETS}
        #: gribjump index ranges of one field of the largest group (from the prepared tree)
        self.n_ranges = 0
        #: index ranges gribjump was actually asked for, over all calls (observed, for the model)
        self.n_ranges_requested = 0
        #: largest unit estimate the planner produced (bytes)
        self.estimated_unit_bytes_max = 0
        #: fields of one unit held on the Python heap at once (per-field consumption only)
        self.buffered_fields_max = 0
        #: where a unit's fields come from: "get" (whole unit) or "get_iter" (per field)
        self.unit_source = "get"
        #: "per_call" or "per_group": how often a unit pays for building its gribjump request ranges
        self.request_side = "per_call"

    def note_get(self, seconds: float, n_fields: int = 0) -> None:
        """One unit fetched: its duration into the total, the maximum and its bucket."""
        self.n_units += 1
        self.get_seconds += seconds
        self.get_seconds_max = max(self.get_seconds_max, seconds)
        self.fields_per_unit_max = max(self.fields_per_unit_max, n_fields)
        for edge, name in GET_BUCKETS:
            if seconds <= edge:
                self.get_buckets[name] += 1
                break


class BlockExtractor:
    """Runs one parsed request through slice / prepare / get and yields encoder bytes."""

    def __init__(self, pm, request: dict, feature_type: str, feature, role: str, header: RequestHeader, encoder):
        self.pm = pm
        self.conf = pm.conf
        self.request = request
        self.feature_type = feature_type
        self.feature = feature
        self.role = role
        self.header = header
        self.encoder = encoder
        self.counters = _Counters()
        #: gribjump index ranges per spatial sub-tree, counted once per node
        self.ranges = bulk_tree.RangeCounts()

    # -- datacube --------------------------------------------------------------------------------------

    def _get(self, datacube, tree, n_fields: int = 0, **kwargs):
        """One ``datacube.get``, timed and counted as one unit (``n_fields``: fields it asks for)."""
        t0 = time.perf_counter()
        try:
            return datacube.get(tree, self.pm.log_context, **kwargs)
        finally:
            self.counters.note_get(time.perf_counter() - t0, n_fields)

    def _get_fields(self, datacube, tree, key_axes, label=None, n_fields: int = 0, **kwargs):
        """``collect_field_values`` of ``datacube.get(tree, **kwargs)``.

        On DataNotFound: ``{}`` (no field) when gribjump matched none of the fields, else None (some fields
        exist: the caller re-fetches in smaller pieces).  Other exceptions propagate.  ``label`` names the
        fetched sub-tree in the DEBUG line when it is not described by ``kwargs`` (pre-pruned unit trees).
        """
        try:
            filled = self._get(datacube, tree, n_fields=n_fields, **kwargs)
        except Exception as exc:
            if not is_data_not_found(exc):
                raise
            logger.debug("%s: DataNotFound for %s: %s", self.pm.id, kwargs if label is None else label, exc)
            return {} if matched_no_field(exc) else None
        return collect_field_values(filled, key_axes)

    def _note_missing(self, select, param, level) -> None:
        self.counters.n_missing_fields += 1
        logger.debug("%s: field missing: %s param=%s levelist=%s", self.pm.id, select, param, level)

    def _count_extract_calls(self, datacube):
        gj = getattr(datacube, "gj", None)
        if gj is None or not hasattr(gj, "extract"):
            return
        extract = gj.extract
        counters = self.counters

        def counted_extract(requests, *args, **kwargs):
            counters.n_gribjump_calls += 1
            requests = list(requests)
            counters.n_ranges_requested += sum(len(r[1]) for r in requests)
            return extract(requests, *args, **kwargs)

        try:
            gj.extract = counted_extract
        except (AttributeError, TypeError):  # e.g. a C extension object
            logger.debug("Cannot count gribjump extract calls on %r", type(gj))

    # -- main loop -------------------------------------------------------------------------------------

    def stream(self, t_start: float) -> Iterator[bytes]:
        timings = self.pm.timings
        enc_seconds = 0.0

        def emit(fn, *args) -> bytes:
            nonlocal enc_seconds
            t0 = time.perf_counter()
            try:
                return fn(*args)
            finally:
                enc_seconds += time.perf_counter() - t0

        first = emit(self.encoder.begin, self.header)
        timings["first_byte_ms"] = round((time.perf_counter() - t_start) * 1000, 3)
        if first:
            yield first

        api, tree = self._slice()
        datacube = api.datacube

        if self.header.domain_type == "MultiPoint" or (
            self.header.domain_type == "Trajectory" and self.role == "hdate"
        ):
            source = self._multipoint_source(datacube, tree)
        else:
            tree = self._prepare(datacube, tree)
            info, plan, groups = self._plan(tree)
            source = self._whole_tree_blocks(datacube, tree, info, plan, groups)

        encode_iter = getattr(self.encoder, "encode_iter", None)
        for block in source:
            if encode_iter is not None:
                # Bounded fragments (covjsonkit >= feat/streaming-encoder): the encoder never materialises a
                # whole block's text, so memory per block does not scale with the block. The generator must be
                # consumed completely and in order before the next block (the encoder's state advances with it).
                t0 = time.perf_counter()
                fragments = encode_iter(block)
                enc_seconds += time.perf_counter() - t0
                while True:
                    t0 = time.perf_counter()
                    try:
                        data = next(fragments)
                    except StopIteration:
                        enc_seconds += time.perf_counter() - t0
                        break
                    enc_seconds += time.perf_counter() - t0
                    if data:
                        yield data
            else:
                data = emit(self.encoder.encode, block)
                if data:
                    yield data
        last = emit(self.encoder.end)

        c = self.counters
        timings["get_ms"] = round(c.get_seconds * 1000, 3)
        timings["encode_ms"] = round(enc_seconds * 1000, 3)
        timings["n_groups"] = c.n_groups
        timings["n_units"] = c.n_units
        timings["groups_per_unit_max"] = c.groups_per_unit_max
        timings["fields_per_unit_max"] = c.fields_per_unit_max
        timings["n_spatial_subtrees"] = c.n_spatial_subtrees
        timings["n_gribjump_calls"] = c.n_gribjump_calls
        timings["n_missing_fields"] = c.n_missing_fields
        timings["n_fallbacks"] = c.n_fallbacks
        timings["n_ranges"] = c.n_ranges
        timings["n_ranges_requested"] = c.n_ranges_requested
        timings["estimated_unit_bytes_max"] = c.estimated_unit_bytes_max
        # Where the get time went, without per-unit DEBUG lines: one unit per bucket plus the worst.
        for name, count in c.get_buckets.items():
            timings[f"units_get_{name}"] = count
        timings["get_ms_max"] = round(c.get_seconds_max * 1000, 3)
        timings["unit_source"] = c.unit_source
        timings["request_side"] = c.request_side
        timings["buffered_fields_max"] = c.buffered_fields_max
        timings["max_rss_bytes"] = max_rss_bytes()
        n_cov = getattr(self.encoder, "n_coverages", None)
        timings["n_coverages"] = n_cov if n_cov is not None else c.n_groups
        logger.info(
            "%s: extracted %d groups in %d units (<= %d groups / %d fields per unit,"
            " %d gribjump calls, %d spatial sub-trees, %d ranges per field via %s, request side %s);"
            " estimated <= %.1f MB per unit,"
            " peak RSS %.1f MB; get %.1f ms (max %.1f ms per unit, %s), encode %.1f ms",
            self.pm.id,
            c.n_groups,
            c.n_units,
            c.groups_per_unit_max,
            c.fields_per_unit_max,
            c.n_gribjump_calls,
            c.n_spatial_subtrees,
            c.n_ranges,
            c.unit_source,
            c.request_side,
            c.estimated_unit_bytes_max / 1e6,
            timings["max_rss_bytes"] / 1e6,
            timings["get_ms"],
            timings["get_ms_max"],
            " ".join(f"{name}={count}" for name, count in c.get_buckets.items()),
            timings["encode_ms"],
        )
        if last:
            yield last

    def _slice(self):
        """``(api, tree)``: the datacube, the sliced request tree.  Nothing is prepared yet."""
        from polytope_feature.polytope import Polytope, Request

        shapes = self.pm._create_base_shapes(self.request, self.feature_type)
        shapes.extend(self.feature.get_shapes())
        preq = Request(*shapes)

        t0 = time.perf_counter()
        if self.conf.datacube.type != "gribjump":
            raise NotImplementedError(f"Datacube type '{self.conf.datacube.type}' not found")
        handle = self.pm.datacube_factory() if self.pm.datacube_factory is not None else self.pm._default_gribjump()
        options = self.conf.options.model_dump()
        # One array-backed node per spatial sub-tree instead of a latitude -> longitude layer per grid row:
        # the gribjump index ranges come from one sort of the whole field's indexes (hundreds instead of
        # hundreds of thousands on HEALPix nested) and nothing of the spatial walk is per point
        # (:mod:`polytope_mars.bulk_tree`).  Required: every tree reader here expects bulk nodes.
        options["bulk_grid_leaves"] = True
        api = Polytope(datacube=handle, options=options, context=self.pm.log_context)
        # The block walker reads any number of points per longitude leaf, so polygons and paths can be
        # sliced into one leaf per latitude line instead of one node per point (which is also what the
        # fold above turns into one node per sub-tree).
        api._merge_union_rows = True
        self._count_extract_calls(api.datacube)
        self.pm._add_timing("datacube_init_ms", time.perf_counter() - t0)

        logger.debug("%s: request given to polytope: %s", self.pm.id, preq)
        t0 = time.perf_counter()
        tree = slice_request(api, preq)
        self.pm._add_timing("slice_ms", time.perf_counter() - t0)
        return api, tree

    def _prepare(self, datacube, tree, **kwargs):
        """``FDBDatacube.prepare``: the points of (a pruned copy of) ``tree`` in their final order.

        ``prepare`` also folds each spatial sub-tree into one bulk node and is where the request ranges
        are planned, so after it the tree holds the exact coordinates, grid indexes and range counts the
        extraction is sized and emitted from.  It is also the first point where the tree's size is known
        exactly rather than estimated, so that is where ``limits.max_tree_bytes`` is enforced
        (:meth:`_check_tree_bytes`) -- still before any gribjump call.
        """
        t0 = time.perf_counter()
        try:
            prepared = datacube.prepare(tree, self.pm.log_context, **kwargs)
        finally:
            self.pm._add_timing("prepare_ms", time.perf_counter() - t0)
        self._check_tree_bytes(prepared)
        return prepared

    def _check_tree_bytes(self, tree) -> None:
        """Report the prepared tree's size and refuse it when it exceeds ``limits.max_tree_bytes``.

        The pre-slice estimate (:meth:`polytope_mars.api.PolytopeMars._check_tree_bytes`) prices the
        branching axes it can read off the request; this is the exact figure, and the backstop for the
        shapes the estimate cannot see (an uncompressed union leaf, an ``ALL`` axis).
        """
        n_spatial, n_points, n_bytes = bulk_tree.tree_summary(tree)
        self.pm.timings["tree_bytes"] = n_bytes
        limit = tree_byte_limit(self.conf.limits)
        if limit is None or n_bytes <= limit:
            return
        raise ValueError(
            f"The request tree holds {n_points} grid points in {n_spatial} separate branches and costs "
            f"{format_bytes(n_bytes)}, more than the limit of {format_bytes(limit)}; "
            "request a smaller area, or fewer dates and times per request"
        )

    def _plan(self, tree):
        """``(info, plan, groups)``: the field groups of ``tree`` in legacy coverage order."""
        info = analyse_tree(tree)
        plan = make_plan(info, self.feature_type, self.header.domain_type, self.role, self.request)
        groups = plan.groups()
        logger.debug("%s: %d field groups planned", self.pm.id, len(groups))
        return info, plan, groups

    # -- MultiPoint: one unit per group, or one call per (param, level) -----------------------------------

    def _sizing(self, datacube, per_field=None) -> UnitSizing:
        """The memory model of one unit, and how this datacube delivers a unit's fields.

        ``per_field_consumption`` is on (the default) when the datacube can hand the fields over one
        at a time (``get_iter``), which keeps the per-value term at one group whatever the unit's
        size; without it one ``get`` returns the whole unit and that term covers all of it.  The
        fragment term comes from the encoder in use, so a smaller ``max_fragment_bytes`` buys unit
        size back.
        """
        if per_field is None:
            per_field = self._per_field(datacube)
        return UnitSizing.from_limits(
            self.conf.limits,
            per_field_consumption=per_field,
            fragment_bytes=2 * getattr(self.encoder, "max_fragment_bytes", DEFAULT_FRAGMENT_BYTES // 2),
        )

    def _per_field(self, datacube) -> bool:
        """True when this run consumes a unit's fields one at a time (config + datacube support)."""
        return bool(self.conf.limits.per_field_consumption) and has_per_field_consumption(datacube)

    def _field_group(self, plan, g: GroupPlan, index, params, n_points) -> FieldGroup:
        return FieldGroup(
            index=index,
            path={a: str(v) for a, v in g.select.items()},
            t=tuple(g.t),
            params=tuple(str(p) for p in params),
            levels=tuple(plan.level_out(lev) for lev in g.levels),
            n_points=n_points,
            mars_metadata=g.mars_metadata,
        )

    def _group_specs(self, info, plan, groups, sizing: UnitSizing) -> list:
        """One :class:`~polytope_mars.tree_units.GroupSpec` per planned group, in emission order.

        Points and gribjump index ranges are read off the prepared tree's bulk spatial nodes, one entry
        per spatial sub-tree (:mod:`polytope_mars.bulk_tree`); the sizing turns them into the number of
        groups one ``datacube.get`` may fetch.

        Whether the groups share a spatial sub-tree decides how often one call pays the request side
        (:meth:`~polytope_mars.sizing.UnitSizing.request_bytes`): the group axes of an EFAS ensemble
        (``number``, ``step``) are compressed inside one branch, so a unit of any size holds one node's
        arrays, while climate-dt's merged date/time axis gives every hourly field its own branch, so a
        unit of ``k`` groups holds ``k`` of them.
        """
        axes = plan.group_axes()
        ranges = self.ranges
        own_branch = self._groups_own_their_branches(groups)
        self.counters.request_side = "per_group" if own_branch else "per_call"
        specs = []
        subtrees: set = set()
        for g in groups:
            nodes = spatial_nodes(info, g.branches)
            subtrees.update(id(node) for node in nodes)
            counts = tuple(bulk_tree.point_count(node) for node in nodes)
            n_points = sum(counts)
            n_fields = len(g.params) * len(g.levels or [None])
            range_counts = tuple(ranges.of(node) for node in nodes) if n_points else ()
            # A group that does not have a value on every group axis cannot be selected together with
            # its neighbours (branches without that axis would come along whole): it stays its own unit.
            key = tuple(g.key) if axes and all(v is not None for v in g.key) else None
            specs.append(
                GroupSpec(
                    key=key,
                    shape=(n_points, tuple(g.params), tuple(g.levels)),
                    max_groups=sizing.max_unit_groups(
                        n_points, n_fields, sum(range_counts), n_subtrees=len(counts), own_branch=own_branch
                    ),
                    counts=counts,
                    range_counts=range_counts,
                    own_branch=own_branch,
                )
            )
        self.counters.n_ranges = max([s.n_ranges for s in specs], default=0)
        self.counters.n_spatial_subtrees = len(subtrees)
        return specs

    @staticmethod
    def _groups_own_their_branches(groups) -> bool:
        """True when no two groups share a spatial sub-tree, so each brings its own request side."""
        seen: set = set()
        for g in groups:
            for b in g.branches:
                if b in seen:
                    return False
                seen.add(b)
        return True

    def _multipoint_source(self, datacube, tree) -> Iterator[Any]:
        """Prepare the whole tree, plan the units on it, and refuse a field that cannot be fetched whole.

        ``prepare`` is what folds the spatial layers into one bulk node per sub-tree and plans the
        request ranges, so the point counts and range counts the units are sized from come from the
        prepared tree.  A field is never split: when a single field does not fit the budget the request
        is refused (:meth:`_refuse_field`) rather than cut into pieces.
        """
        tree = self._prepare(datacube, tree)
        info, plan, groups = self._plan(tree)
        sizing = self._sizing(datacube)
        specs = self._group_specs(info, plan, groups, sizing)
        for spec in specs:
            if spec.max_groups < 1 and not sizing.fits_field(
                spec.n_points, spec.n_fields, spec.n_ranges, n_subtrees=spec.n_subtrees
            ):
                self._refuse_field(sizing, spec)
        return self._multipoint_blocks(datacube, tree, info, plan, groups, specs, sizing)

    def _refuse_field(self, sizing: UnitSizing, spec) -> None:
        """Refuse a request one field of which does not fit ``limits.memory_budget_bytes``.

        A field is always fetched whole, so a field larger than the budget cannot
        be served at all.  ``limits.max_points_per_field`` is the explicit cap that refuses such a
        request before it is even sliced; this is the backstop for the requests it does not cover.
        """
        needed = sizing.field_bytes(spec.n_points, spec.n_ranges, spec.n_fields, spec.n_subtrees)
        raise ValueError(
            f"One field of this request covers {spec.n_points} grid points and needs about "
            f"{needed / 1e6:.0f} MB to extract, more than the memory budget of {sizing.budget} bytes; "
            "request a smaller area or fewer parameters per request"
        )

    def _multipoint_blocks(self, datacube, tree, info, plan, groups, specs, sizing) -> Iterator[Any]:
        axes = plan.group_axes()
        for start, length in plan_units(specs):
            self.counters.groups_per_unit_max = max(self.counters.groups_per_unit_max, length)
            spec = specs[start]
            if length > 1:
                self._note_estimate(sizing, length * spec.n_fields, spec, n_groups=length)
                yield from self._multi_group_unit(
                    datacube, tree, info, plan, axes, groups, specs, start, length, sizing
                )
                continue
            g = groups[start]
            if spec.n_points == 0:
                continue
            index = self.counters.n_groups
            if spec.max_groups >= 1:
                self._note_estimate(sizing, spec.n_fields, spec)
                blocks = self._single_unit(datacube, tree, info, plan, g, index, spec)
            else:
                # The group's fields do not fit one call together: one call per (param, level), each
                # fetching its field whole (checked to fit by :meth:`_multipoint_source`).
                self.counters.estimated_unit_bytes_max = max(
                    self.counters.estimated_unit_bytes_max,
                    sizing.field_bytes(spec.n_points, spec.n_ranges, spec.n_fields, spec.n_subtrees),
                )
                blocks = self._field_units(datacube, tree, info, plan, g, index, spec)
            yield from self._emit_group(blocks)

    def _note_estimate(self, sizing: UnitSizing, n_fields: int, spec, n_groups: int = 1) -> None:
        """Record what the planner thinks the next ``datacube.get`` costs (observability only)."""
        branches = spec.n_subtrees * (n_groups if spec.own_branch else 1)
        estimate = sizing.estimate_bytes(
            n_fields, spec.n_points, spec.n_ranges, group_fields=spec.n_fields, n_branches=branches
        )
        self.counters.estimated_unit_bytes_max = max(self.counters.estimated_unit_bytes_max, estimate)

    def _emit_group(self, blocks) -> Iterator[Any]:
        """Pass one group's blocks on and count the group when it produced any."""
        produced = False
        for block in blocks:
            produced = True
            yield block
        if produced:
            self.counters.n_groups += 1

    def _single_unit(self, datacube, tree, info, plan, g, index, spec):
        fields = self._get_fields(datacube, tree, ["param", "levelist"], n_fields=spec.n_fields, select=dict(g.select))
        if fields is None:
            # DataNotFound and some fields exist: re-fetch one (param, level) per call, which is also
            # what says which fields are missing (only costs extra calls when data is missing).
            self.counters.n_fallbacks += 1
            yield from self._field_units(datacube, tree, info, plan, g, index, spec)
            return
        yield from self._group_blocks(info, plan, g, index, spec.n_points, fields, ())

    def _multi_group_unit(
        self, datacube, tree, info, plan, axes, groups, specs, start, length, sizing
    ) -> Iterator[Any]:
        """One ``datacube.get`` for ``length`` consecutive groups, consumed per field.

        The group axes stay compressed over the unit, so the call fetches every field of every group
        in it.  The fields are then taken one at a time and a group's blocks are emitted (and its
        fields dropped) as soon as all of its (param, level) have arrived, in plan order
        (:class:`~polytope_mars.field_stream.GroupAssembler`): the Python heap only ever holds the
        groups still incomplete, not the whole unit.

        The fields are handed over by :mod:`polytope_mars.field_stream`:
        ``FDBDatacube.get_iter`` hands the fields over as they are decoded (the default), or one
        ``datacube.get`` returns all of them at once (``limits.per_field_consumption: false``, in
        which case the unit's whole size is what the budget has to cover).
        """
        select = unit_select(specs, start, length, axes)
        logger.debug("%s: unit of %d groups: %s", self.pm.id, length, select)
        sub = prune_values(tree, select)
        unit_groups = [groups[i] for i in range(start, start + length)]
        assembler = GroupAssembler(unit_groups)
        n_fields = length * specs[start].n_fields
        source = self._unit_fields(datacube, sub, list(axes) + ["param", "levelist"], select, n_fields)
        emitted = False
        try:
            for key, value in source:
                for i, fields in assembler.feed(key, value):
                    emitted = True
                    yield from self._emit_unit_group(info, plan, unit_groups[i], specs[start + i], fields)
            for i, fields in assembler.flush():
                emitted = True
                yield from self._emit_unit_group(info, plan, unit_groups[i], specs[start + i], fields)
        except _UnitPartiallyMissing:
            if emitted:
                # Only reachable on a per-field source that fails mid-unit: blocks of earlier groups
                # are already on the wire, so the call cannot be retried in smaller pieces.
                raise
            # DataNotFound and some fields exist: fetch the unit's groups one at a time, which falls
            # back to one call per (param, level) for the group that is missing a field.
            self.counters.n_fallbacks += 1
            for i in range(start, start + length):
                index = self.counters.n_groups
                yield from self._emit_group(self._single_unit(datacube, tree, info, plan, groups[i], index, specs[i]))
            return
        finally:
            self.counters.buffered_fields_max = max(self.counters.buffered_fields_max, assembler.max_buffered_fields)

    def _emit_unit_group(self, info, plan, g, spec, fields) -> Iterator[Any]:
        index = self.counters.n_groups
        yield from self._emit_group(self._group_blocks(info, plan, g, index, spec.n_points, fields, tuple(g.key)))

    def _unit_fields(self, datacube, sub, key_axes, label, n_fields: int = 0) -> Iterator:
        """``(key, (values, missing))`` of a unit's fields, from ``get_iter`` when there is one.

        Raises :class:`_UnitPartiallyMissing` when gribjump reports some (not all) fields of the unit
        missing; yields nothing when it has none of them.
        """
        per_field = self._per_field(datacube)
        self.counters.unit_source = unit_field_source(datacube, per_field)
        if per_field:
            yield from self._lazy_unit_fields(datacube, sub, key_axes, label, n_fields)
            return
        fields = self._get_fields(datacube, sub, key_axes, label=label, n_fields=n_fields)
        del sub  # the values live in `fields` now; drop the pruned tree's nodes
        if fields is None:
            raise _UnitPartiallyMissing(label)
        yield from whole_unit_fields(fields)

    def _lazy_unit_fields(self, datacube, sub, key_axes, label, n_fields: int = 0) -> Iterator:
        """The per-field seam: ``FDBDatacube.get_iter`` delivers the unit's fields as they arrive.

        The whole pass is one gribjump call, so it is timed and counted as one unit; the time
        includes the consumer's work on each field, which is what a per-unit duration means here.
        """
        t0 = time.perf_counter()
        try:
            for item in lazy_unit_fields(datacube, sub, key_axes, self.pm.log_context):
                yield item
        except Exception as exc:
            if not is_data_not_found(exc):
                raise
            logger.debug("%s: DataNotFound for %s: %s", self.pm.id, label, exc)
            if not matched_no_field(exc):
                raise _UnitPartiallyMissing(label) from None
        finally:
            self.counters.note_get(time.perf_counter() - t0, n_fields)

    def _group_blocks(self, info, plan, g, index, n_points, fields, prefix) -> Iterator[Any]:
        """The blocks of one group whose fields are fetched: one block of points, params with data only.

        ``fields`` is a :func:`collect_field_values` result keyed ``prefix + (param, levelist)``, with
        the group's group-axis values as ``prefix`` when the call covered several groups (else empty).
        """
        has_levels = bool(g.levels)
        levels = g.levels or [None]

        def key(p, lev):
            return prefix + (p, lev if has_levels else None)

        params = []
        for p in g.params:
            present = False
            for lev in levels:
                vals = fields.get(key(p, lev))
                if vals is not None and not vals[1]:
                    present = True
                else:
                    self._note_missing(g.select, p, lev)
            if present:
                params.append(p)
        if not params:
            logger.debug("%s: group %s has no data, skipped", self.pm.id, g.select)
            return
        lat, lon = group_coordinates(info, g.branches)
        if len(lat) != n_points:
            raise RuntimeError(f"Group {g.select}: {len(lat)} coordinates for {n_points} points")
        fg = self._field_group(plan, g, index, params, n_points)
        logger.debug("%s: group %d %s: %d points, %d params", self.pm.id, index, g.select, n_points, len(params))
        yield CoordsBlock(fg, lat, lon)
        for p in params:
            for lev in levels:
                vals = fields.pop(key(p, lev), None)
                if vals is None or len(vals[0]) != n_points:
                    arr = np.full(n_points, np.nan)
                else:
                    arr = vals[0]
                yield ValuesBlock(fg, str(p), plan.level_out(lev) if has_levels else None, arr)
        yield GroupEnd(fg)

    def _field_units(self, datacube, tree, info, plan, g, index, spec) -> Iterator[Any]:
        """One ``datacube.get`` per (param, level) of a group whose fields do not fit one call together.

        Each call fetches one whole field -- a field is never split -- so gribjump's own buffer holds one
        field instead of the group's, while the Python side still holds the group (its params have to be
        known before the coverage is opened).  A ``DataNotFound`` on such a call therefore says that this
        one field has no GRIB message, which is how a missing field is reported.
        """
        has_levels = bool(g.levels)
        fields: dict = {}
        for p in g.params:
            for lev in g.levels or [None]:
                sel = dict(g.select)
                sel["param"] = p
                if has_levels:
                    sel["levelist"] = lev
                got = self._get_fields(datacube, tree, [], label=sel, n_fields=1, select=sel)
                # {} (gribjump matched no field of the call) or None (an unreadable DataNotFound message):
                # with one field per call both mean that this field is missing, and nothing smaller is left
                # to try.  Leaving the key out is how :meth:`_group_blocks` reports it.
                if got:
                    vals = got.get(())
                    if vals is not None:
                        fields[(p, lev if has_levels else None)] = vals
        yield from self._group_blocks(info, plan, g, index, spec.n_points, fields, ())

    # -- point features: one get for the whole tree --------------------------------------------------------

    def _note_whole_tree_estimate(self, datacube, info, groups) -> int:
        """Estimate of the one call a point feature makes, and its field count.

        Point features fetch the whole tree with one ``datacube.get``, never through ``get_iter``,
        so this is the whole-unit model whatever ``limits.per_field_consumption`` says.  A point
        feature's fields hold a handful of points each, so this is observability only: there is
        nothing to refuse and nothing to fetch in smaller pieces.
        """
        sizing = self._sizing(datacube, per_field=False)
        ranges = self.ranges
        n_fields = n_points = n_ranges = 0
        subtrees: set = set()
        for g in groups:
            nodes = spatial_nodes(info, g.branches)
            points = sum(bulk_tree.point_count(node) for node in nodes)
            if not points:
                continue
            subtrees.update(id(node) for node in nodes)
            fields = len(g.params) * len(g.levels or [None])
            n_fields += fields
            n_points += points
            n_ranges += sum(ranges.of(node) for node in nodes)
        self.counters.n_spatial_subtrees = len(subtrees)
        if not n_fields:
            return 0
        # one call, one "group": per-field points and ranges averaged over the tree
        estimate = sizing.estimate_bytes(n_fields, n_points // n_fields or n_points, n_ranges)
        self.counters.n_ranges = max(self.counters.n_ranges, n_ranges)
        self.counters.estimated_unit_bytes_max = max(self.counters.estimated_unit_bytes_max, estimate)
        return n_fields

    def _whole_tree_blocks(self, datacube, tree, info, plan, groups) -> Iterator[Any]:
        axes = plan.group_axes()
        key_axes = axes + ["param", "levelist"]
        n_fields = self._note_whole_tree_estimate(datacube, info, groups)
        try:
            filled = self._get(datacube, tree, n_fields=n_fields)
        except Exception as exc:
            if not is_data_not_found(exc):
                raise
            logger.debug("%s: DataNotFound for the whole tree: %s", self.pm.id, exc)
            if matched_no_field(exc):
                fields = {}
            else:
                fields = self._point_fields_fallback(datacube, tree, info, groups, key_axes)
        else:
            info = analyse_tree(filled)
            fields = collect_field_values(filled, key_axes)
        index = 0
        for g in groups:
            n_points = sum(spatial_counts(info, g.branches))
            if n_points == 0:
                continue
            levels = g.levels or [None]

            group_fields = {(p, lev): fields.get(tuple(g.key) + (p, lev)) for p in g.params for lev in levels}
            found = {k for k, v in group_fields.items() if v is not None and not v[1]}
            for p, lev in group_fields:
                if (p, lev) not in found:
                    self._note_missing(g.select, p, lev)
            params = [p for p in g.params if any((p, lev) in found for lev in levels)]
            if not params:
                continue
            fg = self._field_group(plan, g, index, params, n_points)
            lat, lon = group_coordinates(info, g.branches)
            yield CoordsBlock(fg, lat, lon)
            for p in params:
                for lev in levels:
                    vals = group_fields[(p, lev)]
                    arr = vals[0] if vals is not None and len(vals[0]) == n_points else np.full(n_points, np.nan)
                    yield ValuesBlock(fg, str(p), plan.level_out(lev) if g.levels else None, arr)
            yield GroupEnd(fg)
            index += 1
            self.counters.n_groups += 1

    def _point_fields_fallback(self, datacube, tree, info, groups, key_axes) -> dict:
        """The fields of ``tree`` fetched piecewise after the whole-tree get raised DataNotFound.

        Per param first (the usual case: one param missing everywhere costs one failed call), then, for a
        param that raised with some of its fields found, per (group, param) and per level.  Missing fields
        are absent from the result, which the caller treats like the all-``None`` fields of an empty
        gribjump result.
        """
        self.counters.n_fallbacks += 1
        params = list(info.values.get("param", ()))
        if not params:
            raise RuntimeError("DataNotFound for a tree without a param axis")
        fields: dict = {}
        for p in params:
            got = self._get_fields(datacube, tree, key_axes, select={"param": p})
            if got is not None:
                fields.update(got)
                continue
            self.counters.n_fallbacks += 1
            for g in groups:
                if p not in g.params:
                    continue
                sel = {**g.select, "param": p}
                if g.select:
                    got = self._get_fields(datacube, tree, key_axes, select=sel)
                    if got is not None:
                        fields.update(got)
                        continue
                if "levelist" in g.select or len(g.levels) < 2:
                    continue  # a single field: missing
                self.counters.n_fallbacks += 1
                for lev in g.levels:
                    got = self._get_fields(datacube, tree, key_axes, select={**sel, "levelist": lev})
                    if got is not None:
                        fields.update(got)
        return fields


def build_parameters(param_ids, param_db) -> tuple:
    """ParamInfo per param id, resolved from the local param_db (the legacy ``add_parameter`` rules)."""
    from .param_db import get_params, get_units

    params = get_params(param_db)
    units = get_units(param_db)
    out = []
    for pid in param_ids:
        try:
            entry = params[str(pid)]
        except KeyError:
            raise KeyError(f"Parameter {pid!r} not found in param_db {param_db!r}") from None
        unit_id = entry["unit_id"]
        unit = unit_id if isinstance(unit_id, str) else units[str(unit_id)]["name"]
        out.append(
            ParamInfo(
                id=str(pid),
                shortname=entry["shortname"],
                name=entry["name"],
                unit=unit,
                description=entry.get("description", "") or "",
            )
        )
    return tuple(out)
