"""Reading the spatial layers of a prepared request tree: one array-backed node per sub-tree.

polytope-mars slices and prepares every request with ``options["bulk_grid_leaves"] = True``
(:meth:`polytope_mars.extract.BlockExtractor._slice`), so the spatial layers of a branch are a single
node instead of a latitude -> longitude layer per grid row:

* ``BulkGridTensorIndexNode`` for structured grids (the hullslicer tree's rows, folded in
  ``FDBDatacube.prepare``);
* ``BulkMergedTensorIndexNode`` for point clouds (the quadtree slicer builds it while slicing).

Both expose the whole sub-tree as arrays -- ``coordinates`` (N, 2) of ``(latitude, longitude)`` in
output order, ``indexes`` (N,) of canonical grid indexes, one ``result`` array per field of the call --
so every per-point walk of the tree becomes an array read.  This module is the only place that knows
their attribute names; everything else in polytope-mars goes through it.

The gribjump index ranges a field costs come from the same arrays: ``FDBDatacube`` derives them from
one sort of the node's indexes (``get_bulk_merged_values``), so the count is the number of gaps in
those indexes plus one -- exact, not estimated, and the only input the memory model
(:mod:`polytope_mars.sizing`) needs besides the point count.
"""

from __future__ import annotations

import numpy as np
from polytope_feature.datacube.tensor_index_tree import BulkMergedTensorIndexNode

__all__ = [
    "RangeCounts",
    "bulk_node",
    "coordinates",
    "field_results",
    "is_bulk",
    "point_count",
    "range_count",
]


def is_bulk(node) -> bool:
    """True for a bulk spatial node (either kind)."""
    return isinstance(node, BulkMergedTensorIndexNode)


def bulk_node(node):
    """``node`` itself, checked to be a bulk spatial node."""
    if not is_bulk(node):
        raise RuntimeError(
            f"Spatial node {node!r} is not a bulk node; polytope-mars reads trees sliced and prepared "
            "with options['bulk_grid_leaves'] = True"
        )
    return node


def coordinates(node) -> tuple:
    """``(lat, lon)`` of a spatial sub-tree, in output order: two views on ``node.coordinates``."""
    coords = bulk_node(node).coordinates
    return coords[:, 0], coords[:, 1]


def point_count(node) -> int:
    """Points of a spatial sub-tree (the points of one field of its branch)."""
    count: int = bulk_node(node).point_count
    return count


def range_count(node) -> int:
    """gribjump index ranges one field of ``node`` asks for: the gaps in its sorted grid indexes.

    Mirrors ``FDBDatacube.get_bulk_merged_values``, including its shortcut: on a grid a request
    covers in ascending index order (anything but HEALPix nested, in practice) the node's indexes are
    already sorted, so the count needs no sort at all.
    """
    stored = bulk_node(node).indexes
    if stored is None or len(stored) == 0:
        return 0
    indexes = np.asarray(stored, dtype=np.int64)
    diff = np.diff(indexes)
    if diff.size == 0:
        return 1
    if not bool(np.all(diff > 0)):
        diff = np.diff(np.sort(indexes))
    return 1 + len(np.flatnonzero(diff > 1))


def field_results(node, n_fields: int) -> list:
    """The ``result`` arrays of a filled bulk node: one per field of the call, in product order.

    ``FDBDatacube.get`` appends one array of ``point_count`` values per field, the fields in the
    ``itertools.product`` order of the compressed axes above the node (outermost first), which is the
    order :func:`polytope_mars.extract.collect_field_values` splits a unit's fields into.  A field
    gribjump had no message for is an object array of ``None``.
    """
    result = bulk_node(node).result
    if len(result) != n_fields:
        raise RuntimeError(f"Bulk node holds {len(result)} fields, expected {n_fields}")
    return result


class RangeCounts:
    """:func:`range_count` per spatial node, counted once per node.

    The groups of one request share their spatial sub-trees (a MultiPoint box has one per branch and
    the group axes are compressed inside a branch), so a request walks a node's indexes once.
    """

    def __init__(self):
        self._cache: dict = {}
        #: nodes actually counted (the rest are cache hits)
        self.n_counted = 0

    def of(self, node) -> int:
        key = id(node)
        count = self._cache.get(key)
        if count is None:
            count = self._cache[key] = range_count(node)
            self.n_counted += 1
        return count
