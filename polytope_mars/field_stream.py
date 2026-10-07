"""The fields of one extraction unit, and the group they belong to.

A multi-group unit (DESIGN §2.3) fetches the fields of several field groups in one
``datacube.get``.  The extractor consumes them *per field* and emits a group's blocks as soon as
every (param, level) of that group has arrived, so the Python side only holds the groups that are
still incomplete (:class:`GroupAssembler`), not the whole unit.

Where the fields come from is the seam between polytope-mars and polytope-feature:

* :func:`whole_unit_fields` -- **the default path**: one ``FDBDatacube.get`` fills the pruned
  sub-tree and :func:`~polytope_mars.extract.collect_field_values` splits the leaf results per
  (group, param, level).  Every field of the call is on the Python heap before the first block is
  emitted, so the unit's size is what the budget has to cover
  (:class:`~polytope_mars.sizing.UnitSizing` with ``per_field_consumption=False``).
* :func:`lazy_unit_fields` -- ``FDBDatacube.get_iter``, used when the datacube has it *and*
  ``limits.per_field_consumption`` is on: the fields arrive one at a time and are handed on as they
  come, so the Python peak is one group whatever the unit's size.  gribjump's own buffer still holds
  the whole call (the deployed gribjump decodes the reply before returning), which is what the
  8 B/value term of the sizing covers.

``get_iter`` yields ``(field_path, leaf_values)``: ``field_path`` the MARS keys of one field as
strings, ``leaf_values`` ``[(leaf, float64 values), ...]`` per longitude leaf in tree order, or
``None`` for a field gribjump has no message for.  Which (group, param, level) an item belongs to is
*not* read off ``field_path`` -- its values are MARS strings while the tree (and the plan) carry
typed axis values -- but from the item's position: ``get_iter`` yields one item per (branch, field)
in tree order, the fields of a branch in the cartesian-product order of its compressed axes,
exactly the layout ``collect_field_values`` splits a filled leaf's ``result`` into.
:func:`lazy_unit_fields` rebuilds that key sequence from the pruned tree and zips it with the items.
"""

from __future__ import annotations

import logging
from typing import Iterator

import numpy as np

__all__ = [
    "GroupAssembler",
    "field_key_sequence",
    "has_per_field_consumption",
    "lazy_unit_fields",
    "unit_field_source",
    "whole_unit_fields",
]

logger = logging.getLogger(__name__)


def has_per_field_consumption(datacube) -> bool:
    """True when the datacube can deliver a unit's fields one at a time (``get_iter``)."""
    return callable(getattr(datacube, "get_iter", None))


def group_field_keys(group, prefix: tuple) -> list:
    """The ``collect_field_values`` keys of one group: ``prefix + (param, levelist)``."""
    levels = group.levels or [None]
    has_levels = bool(group.levels)
    return [prefix + (p, lev if has_levels else None) for p in group.params for lev in levels]


class GroupAssembler:
    """Collects a unit's fields and releases each group's fields once they have all arrived.

    ``feed`` returns the groups that are ready, in *plan order* (a group that completes early is
    held back until its predecessors are out, because coverages must be emitted in order).  A key
    may arrive once per branch of the group; the parts are concatenated in arrival order, which is
    tree order, exactly as :func:`~polytope_mars.extract.collect_field_values` concatenates them.
    """

    def __init__(self, groups, prefixes=None):
        self.groups = list(groups)
        prefixes = [tuple(g.key) for g in self.groups] if prefixes is None else list(prefixes)
        #: key -> [group index, ...] (several groups can want the same key only if they share a key)
        self._owners: dict = {}
        #: group index -> number of keys still missing
        self._missing = []
        #: group index -> {key: [parts]}
        self._parts: list = []
        #: group index -> parts still expected per key (one per branch of the group)
        self._parts_per_key = []
        for i, group in enumerate(self.groups):
            keys = group_field_keys(group, prefixes[i])
            for key in keys:
                self._owners.setdefault(key, []).append(i)
            self._missing.append(len(keys))
            self._parts.append({})
            self._parts_per_key.append(max(1, len(getattr(group, "branches", ()) or ())))
        self._next = 0
        #: fields held at once, for observability and tests
        self.max_buffered_fields = 0
        self.n_buffered_fields = 0
        self.n_unknown_fields = 0

    def feed(self, key, value) -> list:
        """Take one field (``key``, ``(values, missing)``); return ``[(group index, fields), ...]``."""
        owners = self._owners.get(key)
        if not owners:
            self.n_unknown_fields += 1
            logger.debug("Field %s does not belong to any group of the unit", (key,))
            return []
        for i in owners:
            parts = self._parts[i].setdefault(key, [])
            parts.append(value)
            if len(parts) == self._parts_per_key[i]:
                # every branch of the group has delivered this field
                self._missing[i] -= 1
            self.n_buffered_fields += 1
        self.max_buffered_fields = max(self.max_buffered_fields, self.n_buffered_fields)
        return self._release()

    def flush(self) -> list:
        """Release every group left, in plan order, with whatever arrived (missing fields stay out)."""
        for i in range(self._next, len(self.groups)):
            self._missing[i] = 0
        return self._release()

    def _release(self) -> list:
        out = []
        while self._next < len(self.groups) and self._missing[self._next] == 0:
            i = self._next
            self._next += 1
            parts = self._parts[i]
            self._parts[i] = {}
            self.n_buffered_fields -= sum(len(p) for p in parts.values())
            out.append((i, {key: _join(values) for key, values in parts.items()}))
        return out

    def complete(self) -> bool:
        return self._next >= len(self.groups)


def _join(parts: list):
    """One ``(values, missing)`` pair out of the parts of a key (one per branch), in arrival order."""
    if len(parts) == 1:
        return parts[0]
    values = np.concatenate([np.asarray(v) for v, _ in parts])
    return values, all(missing for _, missing in parts)


def whole_unit_fields(fields: dict) -> Iterator:
    """``(key, value)`` of an already fetched unit, dropping each field from ``fields`` as it goes."""
    for key in list(fields):
        yield key, fields.pop(key)


# -- the per-field seam (polytope-feature ``get_iter``) ----------------------------------------------


def field_key_sequence(info, key_axes) -> list:
    """The key of every item ``get_iter`` yields for a tree, in order.

    One item per (branch, field): the branches in tree order, a branch's fields in the cartesian
    product of its compressed axes (outermost axis first) -- the layout
    :func:`~polytope_mars.extract.collect_field_values` splits a filled leaf's ``result`` into.
    """
    keys = []
    for branch in info.branches:
        axes = [a for a, _ in branch.path]
        combos = list(np.ndindex(*[len(v) for _, v in branch.path])) if branch.path else [()]
        for combo in combos:
            values = {a: branch.path[i][1][j] for i, (a, j) in enumerate(zip(axes, combo))}
            keys.append(tuple(values.get(a) for a in key_axes))
    return keys


def _field_values(leaf_values) -> tuple:
    """``(float64 array, missing)`` of one item, as ``collect_field_values`` reports a field."""
    if leaf_values is None:
        return np.empty(0), True  # gribjump has no message for this field
    arrays = [np.asarray(values, dtype=np.float64) for _, values in leaf_values]
    if not arrays:
        return np.empty(0), True
    return (arrays[0] if len(arrays) == 1 else np.concatenate(arrays)), False


def lazy_unit_fields(datacube, tree, key_axes, context=None, **kwargs) -> Iterator:
    """``(key, (values, missing))`` per field, straight from ``datacube.get_iter``.

    The seam where polytope-feature's per-field extraction plugs in: nothing of the unit beyond the
    field in flight and the groups still incomplete is held on the Python heap.  The keys come from
    the tree, not from the yielded MARS path (see the module doc), and the item count is checked
    against it.
    """
    from .coverage_plan import analyse_tree

    expected = field_key_sequence(analyse_tree(tree), list(key_axes))
    n = 0
    for _path, leaf_values in datacube.get_iter(tree, context, **kwargs):
        if n >= len(expected):
            raise RuntimeError(f"datacube.get_iter yielded more than the {len(expected)} fields of the unit")
        yield expected[n], _field_values(leaf_values)
        n += 1
    if n != len(expected):
        raise RuntimeError(f"datacube.get_iter yielded {n} of the unit's {len(expected)} fields")


def unit_field_source(datacube, enabled: bool = True) -> str:
    """``"get_iter"`` when the datacube can stream fields and that is enabled, else ``"get"``."""
    return "get_iter" if enabled and has_per_field_consumption(datacube) else "get"
