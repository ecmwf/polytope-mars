"""Multi-group extraction units: several field groups in one ``datacube.get``.

A remote gribjump ``extract`` call costs ~480 ms before it reads a single value (round trip, request
parsing, one FDB catalogue/TOC scan per single-field request) plus ~1.3 us per value.  One call per
field group therefore spends ~24 minutes in fixed cost for a 3000-field ensemble (50 members x 60
steps), where the data itself is a few seconds, and makes the FDB server scan its index 3000 times.
This module plans *units* of several consecutive groups instead: the group axes (``step``,
``number``, ``date``, ``hdate``, ``month``, ...) stay compressed for the whole unit, so one call
fetches every field of every group in it; the leaf results are split per (group, param, level)
afterwards (``polytope_mars.extract.collect_field_values``).

Two things bound a unit:

* how much memory it costs: :class:`~polytope_mars.sizing.UnitSizing` turns the budget, the hard
  caps (``limits.max_fields_per_call``, ``limits.max_values_per_unit``) and the group's shape
  (points, fields, gribjump index ranges, spatial sub-trees) into ``GroupSpec.max_groups``, the
  number of groups of that shape one ``datacube.get`` may fetch.  Without a budget every unit is a
  single group (``UnitSizing`` returns 1); 0 means that not even one group fits, and
  the extractor then fetches it one (param, level) at a time;
* what one tree can express: the group-axis values of a unit must form a cartesian product (a
  "rectangle"), because the compressed axes of a request tree expand to the *product* of their values
  (``FDBDatacube._gribjump_requests``).  Groups of one unit must also agree on their point count,
  params and levels, so that each group's blocks are the same bytes whatever unit fetched them.

:func:`plan_units` plans the units, :func:`prune_values` builds the sub-tree of one.
``TensorIndexTree.prune`` keeps a single value per selected axis (one group); a unit needs a set of
values per axis, which is the same sub-tree shape with more values left on the group-axis nodes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from polytope_feature.datacube import tree_pruning
from polytope_feature.datacube.tensor_index_tree import MergedTensorIndexNode

# Node copying is polytope-feature's own (``TensorIndexTree.prune``); reuse it so a pruned unit is
# built exactly like a pruned group.
_copy_node = tree_pruning._copy_node
_copy_subtree = tree_pruning._copy_subtree
_value_matches = tree_pruning._value_matches

__all__ = ["GroupSpec", "plan_units", "prune_values", "unit_select"]

LATITUDE = "latitude"


@dataclass(frozen=True)
class GroupSpec:
    """What :func:`plan_units` needs to know about one planned field group, in emission order."""

    #: the group's group-axis values (``GroupPlan.key``), or None when it must stay a unit of its own
    key: tuple | None
    #: ``(n_points, params, levels)``; groups of one unit must agree on all three
    shape: tuple
    #: groups of this shape one ``datacube.get`` may fetch (``UnitSizing.max_unit_groups``); 0 when
    #: a single group does not fit and is fetched one (param, level) per call
    max_groups: int = 1
    #: points per spatial sub-tree of the group, in tree order (one entry per bulk spatial node)
    counts: Any = ()
    #: gribjump index ranges of one field, per spatial sub-tree (parallel to ``counts``)
    range_counts: Any = ()
    #: True when this group has spatial sub-trees of its own, so a unit of k groups holds k times
    #: their arrays (:meth:`polytope_mars.sizing.UnitSizing.request_bytes`)
    own_branch: bool = False

    @property
    def n_points(self) -> int:
        return self.shape[0] if self.shape else 0

    @property
    def n_fields(self) -> int:
        """Fields of one group: params x levels."""
        _, params, levels = self.shape
        return max(1, len(params)) * max(1, len(levels))

    @property
    def n_values(self) -> int:
        return self.n_points * self.n_fields

    @property
    def n_ranges(self) -> int:
        """gribjump index ranges of one field of the group."""
        return sum(self.range_counts)

    @property
    def n_subtrees(self) -> int:
        """Spatial sub-trees (bulk nodes) of the group: what one call holds the arrays of."""
        return max(1, len(self.counts))


def _same(a, b) -> bool:
    if a is b:
        return True
    try:
        return bool(a == b)
    except Exception:  # pragma: no cover - exotic axis values
        return False


def plan_units(specs, max_groups=None) -> list:
    """``[(start, length), ...]`` of the units covering ``specs`` (a list of :class:`GroupSpec`).

    Greedy and in emission order: every unit is the longest run of consecutive groups that its
    first group's ``max_groups`` allows (what the memory model and the hard caps pay for), has the
    same shape throughout and whose group-axis values form a cartesian product.  ``max_groups``
    caps the run further (tests; the per-call field cap lives in ``GroupSpec.max_groups``).
    """
    units, start, n = [], 0, len(specs)
    while start < n:
        k = _unit_length(specs, start, max_groups)
        units.append((start, k))
        start += k
    return units


def _unit_length(specs, start: int, max_groups) -> int:
    first = specs[start]
    if first.key is None:
        return 1
    limit = min(len(specs) - start, max(1, first.max_groups))
    if max_groups is not None:
        limit = min(limit, max_groups)
    if limit < 2:
        return 1
    distinct = [[v] for v in first.key]
    best = 1
    for k in range(2, limit + 1):
        spec = specs[start + k - 1]
        if spec.key is None or spec.shape != first.shape or len(spec.key) != len(first.key):
            break
        for values, v in zip(distinct, spec.key):
            if not any(_same(v, u) for u in values):
                values.append(v)
        size = 1
        for values in distinct:
            size *= len(values)
        if size == k:
            best = k
        elif size > limit:
            # The rectangle spanned by the run is already larger than any unit that fits, so a
            # longer run cannot be exactly its own rectangle either.
            break
    return best


def unit_select(specs, start: int, length: int, axes) -> dict:
    """``{axis: values}`` of a unit: the distinct group-axis values of its groups, in plan order."""
    select: dict = {axis: [] for axis in axes}
    for spec in specs[start : start + length]:  # noqa: E203
        for axis, value in zip(axes, spec.key):
            values = select[axis]
            if not any(_same(value, v) for v in values):
                values.append(value)
    return {axis: tuple(values) for axis, values in select.items()}


def prune_values(tree, select: dict):
    """Copy of the (prepared) ``tree`` keeping, on every axis of ``select``, only the listed values.

    The multi-value counterpart of ``TensorIndexTree.prune(select=...)``: nodes on a selected axis
    keep their values that are in ``select`` (in the node's own order, so the compressed-axes
    expansion of ``FDBDatacube.get`` stays in tree order), branches with no value left are dropped and
    everything else is copied as ``prune`` copies it.  ``results`` are empty and no node is shared with
    ``tree``, so ``get`` on the result leaves ``tree`` untouched.

    :raises ValueError: for a spatial axis, a non-root tree, or an axis whose values are not in the
        tree at all (same contract as ``prune``).
    """
    if not tree.is_root():
        raise ValueError("prune_values() must be called on the root of a tree")
    for name in select:
        if name in (LATITUDE, "longitude"):
            raise ValueError(f"Cannot select on spatial axis {name!r}")
    matched = set()

    def visit(src, dst) -> bool:
        kept_any = False
        for child in src.children:
            if isinstance(child, MergedTensorIndexNode) or child.axis.name == LATITUDE:
                dst.add_child(_copy_subtree(child))
                kept_any = True
                continue
            values = None
            name = child.axis.name
            if name in select:
                wanted = select[name]
                values = tuple(v for v in child.values if any(_value_matches(v, w, child.axis) for w in wanted))
                if not values:
                    continue
                matched.add(name)
            new = _copy_node(child, values)
            if len(child.children) == 0:
                # a leaf above the latitude level (non-spatial tree): keep it whole
                dst.add_child(new)
                kept_any = True
                continue
            if visit(child, new):
                dst.add_child(new)
                kept_any = True
        return kept_any

    pruned = _copy_node(tree)
    visit(tree, pruned)
    missing = set(select) - matched
    if missing:
        raise ValueError(
            "Values not found in tree: " + ", ".join(f"{name}={select[name]!r}" for name in sorted(missing))
        )
    return pruned
