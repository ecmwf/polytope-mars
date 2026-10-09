"""Reading the spatial node of a prepared request tree.

polytope-feature's ``prepare`` replaces the spatial layers of every branch -- latitude -> longitude,
one layer per grid row -- by a single array-backed node, so a branch has one spatial child per
sub-tree rather than a row per latitude:

* ``BulkGridTensorIndexNode`` for structured grids (the hullslicer tree's rows, folded in
  ``FDBDatacube.prepare``);
* ``BulkMergedTensorIndexNode`` for point clouds (the quadtree slicer builds it while slicing).

Both expose the whole sub-tree as arrays -- ``coordinates`` (N, 2) of ``(latitude, longitude)`` in
output order, ``indexes`` (N,) of canonical grid indexes, one ``result`` array per field of the call --
so every per-point walk of the tree is an array read.  This module is the only place that knows
their attribute names; everything else in polytope-mars goes through it.

The gribjump index ranges a field costs come from the same arrays: ``FDBDatacube`` derives them from
one sort of the node's indexes (``get_spatial_node_values``), so the count is the number of gaps in
those indexes plus one -- exact, not estimated, and the only input the memory model
(:mod:`polytope_mars.sizing`) needs besides the point count.
"""

from __future__ import annotations

import numpy as np
from polytope_feature.datacube.tensor_index_tree import BulkMergedTensorIndexNode

__all__ = [
    "RangeCounts",
    "coordinates",
    "field_results",
    "is_spatial_node",
    "node_bytes",
    "point_count",
    "range_count",
    "tree_summary",
]


def is_spatial_node(node) -> bool:
    """True for the array-backed spatial node of a prepared sub-tree (either kind)."""
    return isinstance(node, BulkMergedTensorIndexNode)


def coordinates(node) -> tuple:
    """``(lat, lon)`` of a spatial sub-tree, in output order: two views on ``node.coordinates``."""
    coords = node.coordinates
    return coords[:, 0], coords[:, 1]


def point_count(node) -> int:
    """Points of a spatial sub-tree (the points of one field of its branch)."""
    count: int = node.point_count
    return count


def range_count(node) -> int:
    """gribjump index ranges one field of ``node`` asks for: the gaps in its sorted grid indexes.

    Mirrors ``FDBDatacube.get_spatial_node_values``, including its shortcut: on a grid a request
    covers in ascending index order (anything but HEALPix nested, in practice) the node's indexes are
    already sorted, so the count needs no sort at all.
    """
    stored = node.indexes
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
    """The ``result`` arrays of a filled spatial node: one per field of the call, in product order.

    ``FDBDatacube.get`` appends one array of ``point_count`` values per field, the fields in the
    ``itertools.product`` order of the compressed axes above the node (outermost first), which is the
    order :func:`polytope_mars.extract.collect_field_values` splits a unit's fields into.  A field
    gribjump had no message for is an object array of ``None``.
    """
    result = node.result
    if len(result) != n_fields:
        raise RuntimeError(f"Spatial node holds {len(result)} fields, expected {n_fields}")
    return result


class RangeCounts:
    """:func:`range_count` per spatial node, counted once per node.

    The groups of one request share their spatial sub-trees (a MultiPoint box has one per branch and
    the group axes are compressed inside a branch), so a request walks a node's indexes once.
    """

    def __init__(self):
        self._cache: dict = {}

    def of(self, node) -> int:
        key = id(node)
        count = self._cache.get(key)
        if count is None:
            count = self._cache[key] = range_count(node)
        return count


def node_bytes(node) -> int:
    """Bytes a spatial node's own arrays hold: ``coordinates`` (16 B/point) + ``indexes`` (8 B/point).

    The ``lat_values``/``lon_values`` the walker reads are views on ``coordinates``, and the
    ``result`` arrays belong to the call in flight, not to the tree.
    """
    total = 0
    for name in ("coordinates", "indexes"):
        nbytes = getattr(getattr(node, name, None), "nbytes", 0)
        if isinstance(nbytes, int):
            total += nbytes
    return total


def tree_summary(tree) -> tuple[int, int, int]:
    """``(spatial sub-trees, points, bytes)`` of a prepared tree, counting every spatial node once.

    The bytes are the measured form of what :func:`polytope_mars.limits.estimate_tree_bytes` predicts
    before slicing: with one node per sub-tree it is what the request's points cost as arrays.  A
    leaf that is not a spatial node means the tree was not prepared by polytope-feature's
    ``FDBDatacube`` and nothing in polytope-mars can read it.
    """
    nodes, points, total, seen = 0, 0, 0, set()
    stack = [tree]
    while stack:
        node = stack.pop()
        if is_spatial_node(node):
            if id(node) not in seen:
                seen.add(id(node))
                nodes += 1
                points += point_count(node)
                total += node_bytes(node)
            continue
        if not node.children and node is not tree:
            raise RuntimeError(f"Leaf {node!r} is not an array-backed spatial node; the tree was not prepared")
        stack.extend(node.children)
    return nodes, points, total
