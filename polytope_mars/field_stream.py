"""The fields of one extraction unit, and the group they belong to.

A multi-group unit (DESIGN §2.3) fetches the fields of several field groups in one
``datacube.get``.  The extractor consumes them *per field* and emits a group's blocks as soon as
every (param, level) of that group has arrived, so the Python side only holds the groups that are
still incomplete (:class:`GroupAssembler`), not the whole unit.

Where the fields come from is the seam between polytope-mars and polytope-feature:

* :func:`whole_unit_fields` -- **the path in use today**: one ``FDBDatacube.get`` fills the pruned
  sub-tree and :func:`~polytope_mars.extract.collect_field_values` splits the leaf results per
  (group, param, level).  Every field of the call is on the Python heap before the first block is
  emitted, so the unit's size is what the budget has to cover
  (:class:`~polytope_mars.sizing.UnitSizing` with ``per_field_consumption=False``).
* :func:`lazy_unit_fields` -- used as soon as the datacube offers ``get_iter`` (polytope-feature
  work in progress): the fields arrive one at a time in compressed-axes product order and are
  handed on as they come, so the Python peak is one group whatever the unit's size.  The gribjump
  buffer still holds the whole call (the deployed gribjump decodes the reply before returning),
  which is what the 8 B/value term of the sizing covers.

:func:`unit_field_source` picks the second when the datacube has ``get_iter`` and the first
otherwise, so a polytope-feature release switches the path over without a polytope-mars change.

The expected ``get_iter`` contract, which :func:`lazy_unit_fields` adapts (and
``tests/test_field_stream.py`` pins with a stub datacube):

    ``datacube.get_iter(tree, context=None, select=None, latitude_range=None)`` yields one item per
    field in compressed-axes product order (outermost axis first), each either a
    ``(path: Mapping, values)`` pair or an object with ``.path`` and ``.values``; ``path`` holds the
    field's axis values (``param``, ``levelist``, the group axes), ``values`` its points in tree
    order (a sequence of per-range arrays is concatenated).  A field gribjump does not have yields
    ``None`` values, or an empty sequence, like an empty result does today.
"""

from __future__ import annotations

import logging
from typing import Any, Iterator, Mapping, Optional

import numpy as np

__all__ = [
    "GroupAssembler",
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
            if len(parts) == 0:
                self._missing[i] -= 1
            parts.append(value)
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


def _field_path_and_values(item) -> tuple:
    path = getattr(item, "path", None)
    values = getattr(item, "values", None)
    if path is None and isinstance(item, tuple) and len(item) == 2:
        path, values = item
    if not isinstance(path, Mapping):
        raise TypeError(
            "datacube.get_iter must yield (path mapping, values) pairs or objects with .path/.values, "
            f"got {type(item).__name__}"
        )
    return path, values


def _field_values(values) -> tuple:
    """``(float64 array, missing)`` of one field's values, as ``collect_field_values`` returns them."""
    if values is None:
        return np.empty(0), True
    if isinstance(values, (list, tuple)) and values and isinstance(values[0], (list, tuple, np.ndarray)):
        values = np.concatenate([np.asarray(v) for v in values]) if len(values) > 1 else np.asarray(values[0])
    arr = np.asarray(values)
    if arr.dtype == object:
        missing = arr.size > 0 and all(v is None for v in arr)
        return arr.astype(np.float64), missing
    return arr.astype(np.float64, copy=False), arr.size == 0


def lazy_unit_fields(datacube, tree, key_axes, context=None, **kwargs) -> Iterator:
    """``(key, (values, missing))`` per field, straight from ``datacube.get_iter`` (see the module doc).

    The seam where polytope-feature's per-field extraction plugs in: nothing of the unit beyond the
    field in flight and the groups still incomplete is held on the Python heap.
    """
    axes = list(key_axes)
    for item in datacube.get_iter(tree, context, **kwargs):
        path, values = _field_path_and_values(item)
        key = tuple(_axis_value(path, axis) for axis in axes)
        yield key, _field_values(values)


def _axis_value(path: Mapping, axis: str) -> Optional[Any]:
    value = path.get(axis)
    return value


def unit_field_source(datacube) -> str:
    """``"get_iter"`` when the datacube delivers fields one at a time, else ``"get"``."""
    return "get_iter" if has_per_field_consumption(datacube) else "get"
