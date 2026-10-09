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

:func:`plan_units` plans the units; the sub-tree of one is ``tree.prune(select=unit_select(...))``,
which keeps the unit's values on every group axis (``TensorIndexTree.prune`` takes a value or a set of
values per axis) and copies the spatial sub-trees whole.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = ["GroupSpec", "plan_units", "unit_select"]


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
        """Spatial sub-trees (bulk nodes) of the group."""
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
