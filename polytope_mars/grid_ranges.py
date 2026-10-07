"""How many index ranges one field of a (prepared) request tree costs gribjump.

gribjump is asked for *ranges* of grid indices, not for points: ``FDBDatacube._gribjump_requests``
turns every longitude leaf into one request range per run of consecutive grid indices, and an
``ExtractionResult`` holds one ``std::vector<double>`` plus one ``std::vector<std::bitset<64>>``
per range (``gribjump/src/gribjump/ExtractionData.h``).  The C++ residency of a call is therefore
``n_fields x (8 x n_points + n_points/8 + c_range x n_ranges)``, and the range count is what the
sizing (:mod:`polytope_mars.sizing`) needs on top of the point count.

How many ranges a field needs depends on the grid *and* on the shape of the request: a latitude
line of a bounding box on an octahedral grid is one range (O1280 Europe box: 222,960 points in
1,080 ranges), while HEALPix nested scatters the same box over nearly as many ranges as points
(H1024 Europe box: ~480k points in ~300k ranges).  No per-grid constant can stand in for it, so it
is counted from the prepared tree, which already holds the final points in their final order.

The count mirrors ``FDBDatacube.get_2nd_last_values`` / ``get_merged_2nd_last_values`` (grid indices
through the axis' own ``unmap_path_key``, so the mapper does the arithmetic, not this module) and
``sort_fdb_request_ranges`` (duplicates removed first occurrence first, then one range per run of
consecutive indices).  ``tests/test_grid_ranges.py`` pins the result against the ranges the fake
gribjump actually receives.

Counting walks every point of a branch once, so :class:`RangeCounter` memoises the result per
spatial shape: the groups of one MultiPoint request share their spatial sub-tree.
"""

from __future__ import annotations

import logging
from typing import Iterator, List

import numpy as np
from polytope_feature.datacube.tensor_index_tree import MergedTensorIndexNode

__all__ = ["RangeCounter", "branch_ranges", "spatial_range_counts"]

logger = logging.getLogger(__name__)


def _leaf_indices(lat_node) -> Iterator[np.ndarray]:
    """Grid indices of every longitude leaf of one latitude node (``get_2nd_last_values``)."""
    leaf_path: dict = {}
    unwanted: dict = {}
    key_value_path = {lat_node.axis.name: lat_node.values}
    key_value_path, leaf_path, unwanted = lat_node.axis.unmap_path_key(key_value_path, leaf_path, unwanted)
    leaf_path.update(key_value_path)
    for leaf in lat_node.children:
        key_value_path = {leaf.axis.name: leaf.values}
        leaf_path["index"] = leaf.indexes
        key_value_path, leaf_path, unwanted = leaf.axis.unmap_path_key(key_value_path, leaf_path, unwanted)
        yield np.asarray(list(key_value_path["values"]), dtype=np.int64)


def _merged_indices(node) -> np.ndarray:
    """Grid indices of one merged lat/lon leaf (``get_merged_2nd_last_values``)."""
    leaf_path: dict = {}
    unwanted: dict = {}
    lat_axis, lon_axis = node.axes[0], node.axes[1]
    key_value_path = {lat_axis.name: node.values[0]}
    key_value_path, leaf_path, unwanted = lat_axis.unmap_path_key(key_value_path, leaf_path, unwanted)
    leaf_path.update(key_value_path)
    key_value_path = {lon_axis.name: node.values[1]}
    leaf_path["index"] = node.indexes
    key_value_path, leaf_path, unwanted = lon_axis.unmap_path_key(key_value_path, leaf_path, unwanted)
    return np.asarray(list(key_value_path["values"]), dtype=np.int64)


def _count_ranges(indices: np.ndarray) -> int:
    """Request ranges of one leaf: runs of consecutive indices (``sort_fdb_request_ranges``)."""
    if indices.size == 0:
        return 0
    ordered = np.sort(indices)
    if abs(ordered[-1] + 1 - ordered[0]) <= ordered.size:
        # the whole leaf spans no more indices than it has points: one contiguous range
        return 1
    return 1 + len(np.flatnonzero(np.diff(ordered) > 1))


def _drop_duplicates(per_leaf: List[np.ndarray]) -> List[np.ndarray]:
    """``remove_duplicates_in_request_ranges``: an index belongs to the first leaf that claims it."""
    total = sum(a.size for a in per_leaf)
    if total == 0:
        return per_leaf
    stacked = np.concatenate(per_leaf) if len(per_leaf) > 1 else per_leaf[0]
    if np.unique(stacked).size == total:
        return per_leaf  # the usual case: no index is asked for twice
    seen: set = set()
    out = []
    for indices in per_leaf:
        keep = [i for i in indices.tolist() if i not in seen]
        seen.update(keep)
        out.append(np.asarray(keep, dtype=np.int64))
    return out


def branch_ranges(branch_node) -> tuple:
    """``(ranges per spatial child, duplicate points across spatial nodes)`` of one field of a branch.

    The flag matters for latitude bands: ``get`` drops a grid index that two leaves ask for, keeping
    the first.  Duplicates inside one latitude node (a box that meets itself at the longitude seam)
    are dropped whatever the bands are, because a band holds whole latitude nodes; duplicates
    *between* latitude nodes are only seen by a call that holds both, i.e. not when the tree is
    prepared band by band (:meth:`polytope_mars.extract.BlockExtractor._multipoint_source`).

    Falls back to one range per point (the most expensive case) when the indices cannot be computed,
    so that an unknown grid never breaks the extraction, only makes it more careful.
    """
    children = [c for c in branch_node.children if isinstance(c, MergedTensorIndexNode) or c.axis.name == "latitude"]
    per_child: List[List[np.ndarray]] = []
    try:
        for child in children:
            if isinstance(child, MergedTensorIndexNode):
                per_child.append([_merged_indices(child)])
            else:
                per_child.append(list(_leaf_indices(child)))
    except Exception as exc:  # pragma: no cover - exotic mappers / tree shapes
        logger.debug("Cannot count gribjump index ranges (%s); assuming one range per point", exc)
        return [_points(child) for child in children], True
    flat = _drop_duplicates([a for leaves in per_child for a in leaves])
    counts, at = [], 0
    for leaves in per_child:
        counts.append(sum(_count_ranges(flat[at + k]) for k in range(len(leaves))))
        at += len(leaves)
    return counts, _duplicates_across_nodes(per_child)


def spatial_range_counts(branch_node) -> List[int]:
    """Request ranges of one field, per spatial child of ``branch_node`` (latitude nodes in order)."""
    return branch_ranges(branch_node)[0]


def _duplicates_across_nodes(per_child: List[List[np.ndarray]]) -> bool:
    """True when two different spatial nodes ask for the same grid index."""
    flat = [a for leaves in per_child for a in leaves]
    if not flat:
        return False
    stacked = np.concatenate(flat) if len(flat) > 1 else flat[0]
    if np.unique(stacked).size == stacked.size:
        return False  # the usual case: no index is asked for twice at all
    per_node = 0
    for leaves in per_child:
        own = np.concatenate(leaves) if len(leaves) > 1 else leaves[0]
        per_node += np.unique(own).size
    return per_node > np.unique(stacked).size


def _points(spatial_child) -> int:
    if isinstance(spatial_child, MergedTensorIndexNode):
        return 1
    return sum(len(leaf.values) for leaf in spatial_child.children)


class RangeCounter:
    """Range counts of a request's groups, memoised per spatial shape (one count per request)."""

    def __init__(self):
        self._cache: dict = {}
        #: spatial sub-trees actually walked (the rest are cache hits)
        self.n_counted = 0
        #: any counted branch asks for the same grid index from two different latitude nodes
        self.cross_node_duplicates = False

    def counts(self, info, branches, point_counts) -> List[int]:
        """Ranges per spatial node of a group, parallel to ``extract.spatial_counts``."""
        key = tuple(point_counts)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        counts: List[int] = []
        for b in branches:
            branch_counts, duplicates = branch_ranges(info.branches[b].node)
            counts.extend(branch_counts)
            self.cross_node_duplicates = self.cross_node_duplicates or duplicates
        self.n_counted += 1
        self._cache[key] = counts
        return counts
