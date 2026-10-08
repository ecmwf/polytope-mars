"""Block extraction loop: sliced request tree -> :mod:`polytope_mars.blocks` -> encoder bytes.

Per request (:meth:`BlockExtractor.stream`):

1. the :class:`~polytope_mars.blocks.RequestHeader` is built from the parsed request alone and the
   encoder's ``begin()`` bytes are yielded before any datacube work (DESIGN §2.12);
2. the datacube is created, the request sliced once and ``FDBDatacube.prepare`` puts the tree into its
   final point order;
3. :mod:`polytope_mars.coverage_plan` enumerates the field groups in legacy coverage order;
4. MultiPoint groups are extracted one *unit* at a time (DESIGN §2.3): the largest run of consecutive
   groups that fits ``limits.memory_budget_bytes`` in one ``datacube.get`` with param/levelist and the
   group axes compressed (:mod:`polytope_mars.tree_units`), one group per call when there is no budget,
   and one (param, level) at a time in latitude bands when a single group does not fit; the first band of
   every field is fetched before the group's blocks are emitted (band-0 peek) so params gribjump does not
   have are left out of the group, and groups with no data at all are skipped.  Point features
   (PointSeries, VerticalProfile, Trajectory) are small: the whole prepared tree is fetched with one
   ``datacube.get`` and cut into groups afterwards;
5. ``CoordsBlock`` per band, ``ValuesBlock`` per (param, level, band), ``GroupEnd``.

Missing fields (DESIGN §2.5).  gribjump reports a field it has no GRIB message for in one of two ways:
an empty result for that path, or (the remote gribjump, i.e. production) a ``GribJumpException`` whose
message contains ``DataNotFound`` for the whole ``extract`` call (:func:`is_data_not_found`).  The first is
read from the filled tree; on the second the unit that raised is re-fetched in smaller pieces so that the
fields that exist are kept and the missing ones omitted exactly as with empty results:

* whole-group unit -> per (param, level), one band (the banded path with its band-0 peek);
* band 0 of a (param, level) -> that field is missing; a later band of a field whose band 0 was found
  re-raises (the field existed a moment ago);
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
from polytope_feature.datacube.tensor_index_tree import MergedTensorIndexNode

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
from .grid_ranges import RangeCounter
from .sizing import UnitSizing
from .tree_units import GroupSpec, plan_units, prune_values, unit_select

__all__ = ["BlockExtractor", "collect_field_values", "is_data_not_found", "mapper_type", "slice_request"]

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
    """gribjump has some but not all fields of a unit: re-fetch it in smaller pieces (DESIGN §2.5)."""


def max_rss_bytes() -> int:
    """Peak resident set size of this process so far, in bytes (``ru_maxrss``).

    Reported in ``timings`` so that production logs can be held against the planner's estimate.
    Observation only: no decision in polytope-mars reads it (DESIGN §2.7).
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


def mapper_type(options) -> str | None:
    """The ``type`` of the grid mapper transformation in polytope ``options`` (a Config or a dict)."""
    if hasattr(options, "model_dump"):
        options = options.model_dump()
    for axis in (options or {}).get("axis_config", []) or []:
        for tr in axis.get("transformations", []) or []:
            if tr.get("name") == "mapper":
                return tr.get("type")
    return None


# --- reading coordinates and values from (prepared / filled) trees ---------------------------------------


def _is_merged(node) -> bool:
    return isinstance(node, MergedTensorIndexNode)


def _spatial_points(node):
    """(lat, lon) arrays of one spatial child (latitude node or merged lat/lon leaf)."""
    if _is_merged(node):
        return np.array([node.values[0]], dtype=np.float64), np.array([node.values[1]], dtype=np.float64)
    lons = [np.asarray(leaf.values, dtype=np.float64) for leaf in node.children]
    lon = np.concatenate(lons) if len(lons) != 1 else lons[0]
    return np.full(lon.shape, node.values[0], dtype=np.float64), lon


def _leaves(spatial_node):
    """(leaf, n_points) of a spatial child; merged lat/lon nodes are their own single-point leaf."""
    if _is_merged(spatial_node):
        return [(spatial_node, 1)]
    return [(leaf, len(leaf.values)) for leaf in spatial_node.children]


def group_coordinates(info: TreeInfo, branches, start: int = 0, stop: float = math.inf):
    """lat/lon of spatial nodes ``start <= k < stop`` (counted over ``branches`` in tree order)."""
    lats, lons, k = [], [], 0
    for b in branches:
        for child in spatial_children(info.branches[b].node):
            if start <= k < stop:
                lat, lon = _spatial_points(child)
                lats.append(lat)
                lons.append(lon)
            k += 1
            if k >= stop:
                break
        if k >= stop:
            break
    if not lats:
        return np.empty(0), np.empty(0)
    return np.concatenate(lats), np.concatenate(lons)


def spatial_counts(info: TreeInfo, branches) -> list:
    """Points per spatial node over ``branches`` (what ``latitude_point_counts`` gives for the group)."""
    return [sum(n for _, n in _leaves(c)) for b in branches for c in spatial_children(info.branches[b].node)]


def collect_field_values(tree, key_axes) -> dict:
    """Split the leaf results of a filled tree into fields.

    Returns ``{key: (values float64 array, missing bool)}`` with ``key = tuple(field value of axis for axis
    in key_axes)`` (None for axes absent from a branch).  A field is ``missing`` when gribjump had no
    message for it (every value None); bitmap-missing points come back as NaN.
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
        n_comb = len(combos)
        for child in spatial_children(branch.node):
            for leaf, n in _leaves(child):
                res = leaf.result
                if len(res) != n_comb * n:
                    raise RuntimeError(f"Leaf result has {len(res)} values, expected {n_comb} fields x {n} points")
                for c, key in enumerate(keys):
                    lo = c * n
                    chunks.setdefault(key, []).append(res[lo : lo + n])  # noqa: E203
    out = {}
    for key, parts in chunks.items():
        arr = np.concatenate([np.asarray(p) for p in parts]) if len(parts) != 1 else np.asarray(parts[0])
        missing = False
        if arr.dtype == object:
            # gribjump had no message for a field: its values are None (astype turns them into NaN)
            missing = arr.size > 0 and all(v is None for v in arr)
        out[key] = (arr.astype(np.float64), missing)
    return out


class _Counters:
    def __init__(self):
        self.n_groups = 0
        self.n_units = 0
        self.groups_per_unit_max = 0
        self.n_bands = 0
        self.n_gribjump_calls = 0
        self.n_missing_fields = 0
        self.n_fallbacks = 0
        self.get_seconds = 0.0
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
        #: "whole_tree" or "per_band": what was handed to ``FDBDatacube.prepare``
        self.prepare_mode = "whole_tree"


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
        #: gribjump index ranges per spatial node, memoised per spatial shape
        self.ranges = RangeCounter()

    # -- datacube --------------------------------------------------------------------------------------

    def _get(self, datacube, tree, **kwargs):
        t0 = time.perf_counter()
        try:
            return datacube.get(tree, self.pm.log_context, **kwargs)
        finally:
            self.counters.get_seconds += time.perf_counter() - t0
            self.counters.n_units += 1

    def _get_fields(self, datacube, tree, key_axes, label=None, **kwargs):
        """``collect_field_values`` of ``datacube.get(tree, **kwargs)``.

        On DataNotFound: ``{}`` (no field) when gribjump matched none of the fields, else None (some fields
        exist: the caller re-fetches in smaller pieces).  Other exceptions propagate.  ``label`` names the
        fetched sub-tree in the DEBUG line when it is not described by ``kwargs`` (pre-pruned unit trees).
        """
        try:
            filled = self._get(datacube, tree, **kwargs)
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

        for block in source:
            data = emit(self.encoder.encode, block)
            if data:
                yield data
        last = emit(self.encoder.end)

        c = self.counters
        timings["get_ms"] = round(c.get_seconds * 1000, 3)
        timings["retrieve_ms"] = round(
            timings.get("slice_ms", 0.0) + timings.get("prepare_ms", 0.0) + c.get_seconds * 1000, 3
        )
        timings["encode_ms"] = round(enc_seconds * 1000, 3)
        timings["n_groups"] = c.n_groups
        timings["n_units"] = c.n_units
        timings["groups_per_unit_max"] = c.groups_per_unit_max
        timings["n_bands"] = c.n_bands
        timings["n_gribjump_calls"] = c.n_gribjump_calls
        timings["n_missing_fields"] = c.n_missing_fields
        timings["n_fallbacks"] = c.n_fallbacks
        timings["n_ranges"] = c.n_ranges
        timings["n_ranges_requested"] = c.n_ranges_requested
        timings["estimated_unit_bytes_max"] = c.estimated_unit_bytes_max
        timings["unit_source"] = c.unit_source
        timings["prepare_mode"] = c.prepare_mode
        timings["buffered_fields_max"] = c.buffered_fields_max
        timings["max_rss_bytes"] = max_rss_bytes()
        n_cov = getattr(self.encoder, "n_coverages", None)
        timings["n_coverages"] = n_cov if n_cov is not None else c.n_groups
        logger.info(
            "%s: extracted %d groups in %d units (<= %d groups per unit, %d bands, %d gribjump calls,"
            " %d ranges per field via %s, prepared %s); estimated <= %.1f MB per unit, peak RSS %.1f MB;"
            " get %.1f ms, encode %.1f ms",
            self.pm.id,
            c.n_groups,
            c.n_units,
            c.groups_per_unit_max,
            c.n_bands,
            c.n_gribjump_calls,
            c.n_ranges,
            c.unit_source,
            c.prepare_mode,
            c.estimated_unit_bytes_max / 1e6,
            timings["max_rss_bytes"] / 1e6,
            timings["get_ms"],
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
        api = Polytope(datacube=handle, options=self.conf.options.model_dump(), context=self.pm.log_context)
        # The block walker reads any number of points per longitude leaf, so polygons and paths can be
        # sliced into one leaf per latitude line instead of one node per point.
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

        ``prepare`` computes a grid index per point, so its transient scales with what is prepared:
        ``select``/``latitude_range`` keep it down to one band of one field.
        """
        t0 = time.perf_counter()
        try:
            return datacube.prepare(tree, self.pm.log_context, **kwargs)
        finally:
            self.pm._add_timing("prepare_ms", time.perf_counter() - t0)

    def _slice_and_prepare(self):
        """``(api, prepared tree)`` of the whole request (point features, and tests that spy here)."""
        api, tree = self._slice()
        return api, self._prepare(api.datacube, tree)

    def _plan(self, tree):
        """``(info, plan, groups)``: the field groups of ``tree`` in legacy coverage order."""
        info = analyse_tree(tree)
        plan = make_plan(info, self.feature_type, self.header.domain_type, self.role, self.request)
        groups = plan.groups()
        logger.debug("%s: %d field groups planned", self.pm.id, len(groups))
        return info, plan, groups

    # -- MultiPoint: one unit per group, or per (param, level) band ---------------------------------------

    def _sizing(self, datacube) -> UnitSizing:
        """The memory model of one unit, and how this datacube delivers a unit's fields.

        ``per_field_consumption`` is on when the datacube can hand the fields over one at a time
        (``get_iter``), which keeps the Python side at one group whatever the unit's size; without it
        (today) one ``get`` returns the whole unit and the Python term covers all of it.
        """
        return UnitSizing.from_limits(self.conf.limits, per_field_consumption=self._per_field(datacube))

    def _per_field(self, datacube) -> bool:
        """True when this run consumes a unit's fields one at a time (config + datacube support)."""
        return bool(self.conf.limits.per_field_consumption) and has_per_field_consumption(datacube)

    def _field_group(self, plan, g: GroupPlan, index, params, n_points, n_bands) -> FieldGroup:
        return FieldGroup(
            index=index,
            path={a: str(v) for a, v in g.select.items()},
            t=tuple(g.t),
            params=tuple(str(p) for p in params),
            levels=tuple(plan.level_out(lev) for lev in g.levels),
            n_points=n_points,
            n_bands=n_bands,
            mars_metadata=g.mars_metadata,
        )

    def _group_specs(self, info, plan, groups, sizing: UnitSizing) -> list:
        """One :class:`~polytope_mars.tree_units.GroupSpec` per planned group, in emission order.

        Points, fields and gribjump index ranges come from the tree (prepared or not: ``prepare``
        only reorders points and drops duplicates); the sizing turns them into the number of groups
        one ``datacube.get`` may fetch.
        """
        axes = plan.group_axes()
        ranges = self.ranges
        specs = []
        for g in groups:
            counts = spatial_counts(info, g.branches)
            n_points = int(sum(counts))
            n_fields = len(g.params) * len(g.levels or [None])
            range_counts = ranges.counts(info, g.branches, counts) if n_points else []
            # A group that does not have a value on every group axis cannot be selected together with
            # its neighbours (branches without that axis would come along whole): it stays its own unit.
            key = tuple(g.key) if axes and all(v is not None for v in g.key) else None
            specs.append(
                GroupSpec(
                    key=key,
                    shape=(n_points, tuple(g.params), tuple(g.levels)),
                    max_groups=sizing.max_unit_groups(n_points, n_fields, sum(range_counts)),
                    counts=counts,
                    range_counts=range_counts,
                )
            )
        self.counters.n_ranges = max([s.n_ranges for s in specs], default=0)
        return specs

    def _multipoint_source(self, datacube, tree) -> Iterator[Any]:
        """Plan the units on the sliced tree, then prepare either the whole tree or band by band.

        ``prepare`` computes a grid index per point, so on the whole tree of a 26M-point field its
        transient is larger than the field itself.  The plan does not need a prepared tree (point and
        range counts are the same before and after, bar duplicates), so it is made first: when every
        group fits one call the whole tree is prepared as before, and when a group has to be fetched
        in latitude bands the whole tree is never prepared -- each band prepares its own pruned copy,
        which is where that band's coordinates come from, and prepare-time memory scales with the
        band instead of the request.

        One exception: when two latitude nodes ask for the same grid index (a box meeting itself
        across the longitude seam), only a call holding both can drop the duplicate, so the whole
        tree is prepared even for a banded request -- bytes first.
        """
        info, plan, groups = self._plan(tree)
        sizing = self._sizing(datacube)
        specs = self._group_specs(info, plan, groups, sizing)
        banded = any(spec.max_groups < 1 for spec in specs)
        if self._prepare_whole_tree(banded):
            tree = self._prepare(datacube, tree)
            info, plan, groups = self._plan(tree)
            specs = self._group_specs(info, plan, groups, sizing)
            return self._multipoint_blocks(datacube, tree, info, plan, groups, specs, sizing)
        self.counters.prepare_mode = "per_band"
        return self._multipoint_blocks(datacube, tree, info, plan, groups, specs, sizing)

    def _prepare_whole_tree(self, banded: bool) -> bool:
        """Whether to prepare the whole tree up front instead of band by band.

        Yes while every group is fetched whole (the tree has to be in its final order before the
        first coordinate block), and yes for a banded request whose latitude nodes ask for the same
        grid index twice: only a call holding both can drop such a duplicate, and dropping it is
        part of the output.  Duplicates *inside* one latitude node (a box meeting itself across the
        longitude seam) do not count: a band holds whole latitude nodes, so its own prepare drops
        them exactly as a whole-tree prepare would.
        """
        if not banded:
            return True
        if self.ranges.cross_node_duplicates:
            logger.debug("%s: duplicate grid points across latitude nodes: preparing the whole tree", self.pm.id)
            return True
        return False

    def _multipoint_blocks(self, datacube, tree, info, plan, groups, specs, sizing) -> Iterator[Any]:
        axes = plan.group_axes()
        prepared = self.counters.prepare_mode == "whole_tree"
        for start, length in plan_units(specs):
            self.counters.groups_per_unit_max = max(self.counters.groups_per_unit_max, length)
            spec = specs[start]
            if length > 1:
                self._note_estimate(sizing, length * spec.n_fields, spec)
                yield from self._multi_group_unit(
                    datacube, tree, info, plan, axes, groups, specs, start, length, sizing
                )
                continue
            g = groups[start]
            if spec.n_points == 0:
                continue
            index = self.counters.n_groups
            if spec.max_groups >= 1 and prepared:
                self._note_estimate(sizing, spec.n_fields, spec)
                blocks = self._single_unit(datacube, tree, info, plan, g, index, spec.counts)
            else:
                # Per-band prepare: a group that fits is still one band, prepared on its own.
                ratio = spec.n_ranges / spec.n_points if spec.n_points else 1.0
                band_points = spec.n_points if spec.max_groups >= 1 else sizing.band_points(spec.n_fields, ratio)
                self._note_estimate(sizing, spec.n_fields, spec, n_points=min(band_points, spec.n_points))
                blocks = self._banded(datacube, tree, info, plan, g, index, spec.counts, band_points, prepared=prepared)
            yield from self._emit_group(blocks)

    def _note_estimate(self, sizing: UnitSizing, n_fields: int, spec, n_points=None) -> None:
        """Record what the planner thinks the next ``datacube.get`` costs (observability only)."""
        points = spec.n_points if n_points is None else n_points
        ranges = spec.n_ranges
        if points != spec.n_points and spec.n_points:
            ranges = max(1, round(spec.n_ranges * points / spec.n_points))
        estimate = sizing.estimate_bytes(n_fields, points, ranges, group_fields=spec.n_fields)
        self.counters.estimated_unit_bytes_max = max(self.counters.estimated_unit_bytes_max, estimate)

    def _emit_group(self, blocks) -> Iterator[Any]:
        """Pass one group's blocks on and count the group when it produced any."""
        produced = False
        for block in blocks:
            produced = True
            yield block
        if produced:
            self.counters.n_groups += 1

    def _single_unit(self, datacube, tree, info, plan, g, index, counts):
        fields = self._get_fields(datacube, tree, ["param", "levelist"], select=dict(g.select))
        if fields is None:
            # DataNotFound and some fields exist: re-fetch per (param, level) in one band; the band-0 peek
            # keeps the fields that exist (only costs extra calls when data is missing).
            self.counters.n_fallbacks += 1
            yield from self._banded(datacube, tree, info, plan, g, index, counts, int(sum(counts)))
            return
        yield from self._group_blocks(info, plan, g, index, counts, fields, ())

    def _multi_group_unit(
        self, datacube, tree, info, plan, axes, groups, specs, start, length, sizing
    ) -> Iterator[Any]:
        """One ``datacube.get`` for ``length`` consecutive groups (DESIGN §2.3), consumed per field.

        The group axes stay compressed over the unit, so the call fetches every field of every group
        in it.  The fields are then taken one at a time and a group's blocks are emitted (and its
        fields dropped) as soon as all of its (param, level) have arrived, in plan order
        (:class:`~polytope_mars.field_stream.GroupAssembler`): the Python heap only ever holds the
        groups still incomplete, not the whole unit.

        Where the fields come from is the seam of :mod:`polytope_mars.field_stream`: today one
        ``datacube.get`` returns all of them at once (so the unit's size is what the budget has to
        cover), and ``FDBDatacube.get_iter`` will hand them over as they are decoded.
        """
        select = unit_select(specs, start, length, axes)
        logger.debug("%s: unit of %d groups: %s", self.pm.id, length, select)
        sub = prune_values(tree, select)
        unit_groups = [groups[i] for i in range(start, start + length)]
        assembler = GroupAssembler(unit_groups)
        source = self._unit_fields(datacube, sub, list(axes) + ["param", "levelist"], select)
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
                yield from self._emit_group(
                    self._single_unit(datacube, tree, info, plan, groups[i], index, specs[i].counts)
                )
            return
        finally:
            self.counters.buffered_fields_max = max(self.counters.buffered_fields_max, assembler.max_buffered_fields)

    def _emit_unit_group(self, info, plan, g, spec, fields) -> Iterator[Any]:
        index = self.counters.n_groups
        yield from self._emit_group(self._group_blocks(info, plan, g, index, spec.counts, fields, tuple(g.key)))

    def _unit_fields(self, datacube, sub, key_axes, label) -> Iterator:
        """``(key, (values, missing))`` of a unit's fields, from ``get_iter`` when there is one.

        Raises :class:`_UnitPartiallyMissing` when gribjump reports some (not all) fields of the unit
        missing; yields nothing when it has none of them.
        """
        per_field = self._per_field(datacube)
        self.counters.unit_source = unit_field_source(datacube, per_field)
        if per_field:
            yield from self._lazy_unit_fields(datacube, sub, key_axes, label)
            return
        fields = self._get_fields(datacube, sub, key_axes, label=label)
        del sub  # the values live in `fields` now; drop the pruned tree's nodes
        if fields is None:
            raise _UnitPartiallyMissing(label)
        yield from whole_unit_fields(fields)

    def _lazy_unit_fields(self, datacube, sub, key_axes, label) -> Iterator:
        """The per-field seam: ``FDBDatacube.get_iter`` delivers the unit's fields as they arrive."""
        t0 = time.perf_counter()
        self.counters.n_units += 1
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
            self.counters.get_seconds += time.perf_counter() - t0

    def _group_blocks(self, info, plan, g, index, counts, fields, prefix) -> Iterator[Any]:
        """The blocks of one group whose fields are fetched: one band, params with data only.

        ``fields`` is a :func:`collect_field_values` result keyed ``prefix + (param, levelist)``, with
        the group's group-axis values as ``prefix`` when the call covered several groups (else empty).
        """
        n_points = int(sum(counts))
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
        fg = self._field_group(plan, g, index, params, n_points, 1)
        self.counters.n_bands += 1
        logger.debug(
            "%s: group %d %s: %d points, %d params, one band", self.pm.id, index, g.select, n_points, len(params)
        )
        yield CoordsBlock(fg, 0, 0, lat, lon)
        for p in params:
            for lev in levels:
                vals = fields.pop(key(p, lev), None)
                if vals is None or len(vals[0]) != n_points:
                    arr = np.full(n_points, np.nan)
                else:
                    arr = vals[0]
                yield ValuesBlock(fg, str(p), plan.level_out(lev) if has_levels else None, 0, 0, arr)
        yield GroupEnd(fg)

    def _prepared_band(self, datacube, tree, g, lo, hi) -> tuple:
        """``(n_points, lat, lon)`` of one latitude band, from a prepared pruned copy of it.

        One field is selected, so preparing costs one grid-index lookup per point of the band and
        nothing of the rest of the request stays behind: the tree is dropped before returning.
        """
        select = dict(g.select)
        select["param"] = g.params[0]
        if g.levels:
            select["levelist"] = g.levels[0]
        band = self._prepare(datacube, tree, select=select, latitude_range=(lo, hi))
        band_info = analyse_tree(band)
        branches = range(len(band_info.branches))
        n_points = sum(spatial_counts(band_info, branches))
        lat, lon = group_coordinates(band_info, branches)
        return n_points, lat, lon

    def _banded(self, datacube, tree, info, plan, g, index, counts, band_points, prepared=True):
        """One (param, level) at a time, in latitude bands of at most ``band_points`` points.

        ``prepared`` says where the band's coordinates come from: the prepared whole tree
        (``group_coordinates``), or -- when the tree was deliberately left unprepared so that
        prepare-time memory stays proportional to a band -- a prepared pruned copy of that band
        alone.  Both give the same points in the same order: a band is a run of whole latitude nodes
        of the same tree and ``prepare`` only reorders points within a leaf and drops duplicate grid
        indices, which can only span two bands when two latitude nodes share an index (checked
        before the mode is chosen, :meth:`_multipoint_source`).
        """
        # Consecutive spatial nodes up to band_points points (at least one node per band).
        bands, start, acc = [], 0, 0
        for k, n in enumerate(counts):
            if k > start and acc + n > band_points:
                bands.append((start, k))
                start, acc = k, 0
            acc += n
        bands.append((start, len(counts)))
        band_sizes = [sum(counts[lo:hi]) for lo, hi in bands]
        if not prepared:
            # What each band holds once prepared (duplicate points inside a latitude node are gone).
            band_sizes = [self._prepared_band(datacube, tree, g, lo, hi)[0] for lo, hi in bands]
        offsets = [0]
        for size in band_sizes:
            offsets.append(offsets[-1] + size)
        n_points = offsets[-1]
        has_levels = bool(g.levels)

        def fetch(p, lev, band):
            sel = dict(g.select)
            sel["param"] = p
            if has_levels:
                sel["levelist"] = lev
            lo, hi = bands[band]
            expected = offsets[band + 1] - offsets[band]
            try:
                filled = self._get(datacube, tree, select=sel, latitude_range=(lo, hi))
            except Exception as exc:
                # DataNotFound on band 0 (the peek) = the field is missing.  On a later band the field was
                # found a moment ago: that is an error, re-raised.
                if band != 0 or not is_data_not_found(exc):
                    raise
                return np.full(expected, np.nan), True
            fields = collect_field_values(filled, [])
            vals = fields.get(())
            if vals is None:
                return np.full(expected, np.nan), True
            if len(vals[0]) != expected:
                raise RuntimeError(f"Band {band} of {sel}: {len(vals[0])} values for {expected} points")
            return vals

        # Band-0 peek: the first unit of every field, before anything of the group is emitted.
        band0 = {}
        missing_fields = set()
        params = []
        for p in g.params:
            present = False
            for lev in g.levels or [None]:
                arr, missing = fetch(p, lev, 0)
                if not missing:
                    present = True
                else:
                    missing_fields.add((p, lev))
                    self._note_missing(g.select, p, lev)
                band0[(p, lev)] = arr
            if present:
                params.append(p)
            else:
                for lev in g.levels or [None]:
                    band0.pop((p, lev), None)
        if not params:
            logger.debug("%s: group %s has no data, skipped", self.pm.id, g.select)
            return
        fg = self._field_group(plan, g, index, params, n_points, len(bands))
        self.counters.n_bands += len(bands)
        logger.debug(
            "%s: group %d %s: %d points, %d params, %d bands of <= %d points",
            self.pm.id,
            index,
            g.select,
            n_points,
            len(params),
            len(bands),
            band_points,
        )
        for b, (lo, hi) in enumerate(bands):
            if prepared:
                lat, lon = group_coordinates(info, g.branches, lo, hi)
            else:
                _, lat, lon = self._prepared_band(datacube, tree, g, lo, hi)
            yield CoordsBlock(fg, b, offsets[b], lat, lon)
        for p in params:
            for lev in g.levels or [None]:
                out_level = plan.level_out(lev) if has_levels else None
                for b in range(len(bands)):
                    if b == 0:
                        arr = band0.pop((p, lev))
                    elif (p, lev) in missing_fields:  # a missing level of a present param: never re-fetched
                        arr = np.full(offsets[b + 1] - offsets[b], np.nan)
                    else:
                        arr = fetch(p, lev, b)[0]
                    yield ValuesBlock(fg, str(p), out_level, b, offsets[b], arr)
        yield GroupEnd(fg)

    # -- point features: one get for the whole tree --------------------------------------------------------

    def _note_whole_tree_estimate(self, datacube, info, groups) -> None:
        """Estimate of the one call a point feature makes (observability; point features are small)."""
        sizing = self._sizing(datacube)
        ranges = RangeCounter()
        n_fields = n_points = n_ranges = 0
        for g in groups:
            counts = spatial_counts(info, g.branches)
            points = sum(counts)
            if not points:
                continue
            fields = len(g.params) * len(g.levels or [None])
            n_fields += fields
            n_points += points
            n_ranges += sum(ranges.counts(info, g.branches, counts))
        if not n_fields:
            return
        # one call, one "group": per-field points and ranges averaged over the tree
        estimate = sizing.estimate_bytes(n_fields, n_points // n_fields or n_points, n_ranges)
        self.counters.n_ranges = max(self.counters.n_ranges, n_ranges)
        self.counters.estimated_unit_bytes_max = max(self.counters.estimated_unit_bytes_max, estimate)

    def _whole_tree_blocks(self, datacube, tree, info, plan, groups) -> Iterator[Any]:
        axes = plan.group_axes()
        key_axes = axes + ["param", "levelist"]
        self._note_whole_tree_estimate(datacube, info, groups)
        try:
            filled = self._get(datacube, tree)
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
            counts = spatial_counts(info, g.branches)
            n_points = int(sum(counts))
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
            fg = self._field_group(plan, g, index, params, n_points, 1)
            lat, lon = group_coordinates(info, g.branches)
            self.counters.n_bands += 1
            yield CoordsBlock(fg, 0, 0, lat, lon)
            for p in params:
                for lev in levels:
                    vals = group_fields[(p, lev)]
                    arr = vals[0] if vals is not None and len(vals[0]) == n_points else np.full(n_points, np.nan)
                    yield ValuesBlock(fg, str(p), plan.level_out(lev) if g.levels else None, 0, 0, arr)
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
