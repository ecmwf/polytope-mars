"""Preparing band by band gives the same bytes as preparing the whole tree.

``FDBDatacube.prepare`` computes a grid index per point, so preparing the whole tree of a large
field costs more than the field's values.  A banded request therefore leaves the tree unprepared and
prepares each band's pruned copy instead (``BlockExtractor._multipoint_source``).  The output must
not notice: a band is a run of whole latitude nodes of the same tree, and ``prepare`` only reorders
points inside a leaf and drops duplicate grid indices.

The one case where the two could differ is a duplicate index shared by two *different* latitude
nodes, which only a call holding both can drop.  The overlap case of polytope-feature's
``tests/test_pruned_get.py`` (a box whose longitudes wrap past the full circle) duplicates points
*within* each latitude line, not across lines, so it comes out identical as well; the extractor
counts cross-node duplicates and falls back to a whole-tree prepare if it ever finds any.
"""

import copy

import pytest

from polytope_mars.api import PolytopeMars
from polytope_mars.extract import BlockExtractor
from polytope_mars.grid_ranges import RangeCounter
from polytope_mars.testing import fake_gribjump_config_dict, make_fake_gribjump

CDT = {
    "activity": "projections",
    "class": "d1",
    "dataset": "climate-dt",
    "experiment": "ssp3-7.0",
    "expver": "0001",
    "generation": "1",
    "model": "ifs-nemo",
    "realization": "1",
    "resolution": "high",
    "type": "fc",
    "stream": "clte",
    "levtype": "sfc",
    "date": "20200101",
    "time": "0000/1200",
    "param": "167/165",
}
OD = {
    "class": "od",
    "stream": "oper",
    "type": "fc",
    "levtype": "sfc",
    "expver": "0001",
    "domain": "g",
    "date": "20240101",
    "time": "0000",
    "step": "0/6",
    "param": "167/165",
}


def bbox(points):
    return {"type": "boundingbox", "points": points}


#: (grid, request) per mapper family; small boxes, several latitude lines and several fields
SHAPES = {
    "healpix_1024": (
        "healpix_1024",
        {**CDT, "feature": bbox([[50.0, 0.0], [49.0, 2.0]])},
    ),
    "octahedral_1280": (
        "octahedral_1280",
        {**OD, "feature": bbox([[50.0, 0.0], [49.0, 2.0]])},
    ),
    # longitudes wrapping past the full circle: each latitude line holds duplicate points
    "octahedral_overlap": (
        "octahedral_1280",
        {**OD, "feature": bbox([[50.0, -9.0], [49.5, 360.0]])},
    ),
}


def run(name, budget, whole_tree=None, monkeypatch=None):
    """``(bytes, timings, prepare calls)`` of one shape; ``whole_tree`` forces the prepare mode."""
    grid, request = SHAPES[name]
    request = copy.deepcopy(request)
    fake = make_fake_gribjump(grid)
    config = fake_gribjump_config_dict(grid, request)
    config["limits"] = {"memory_budget_bytes": budget, "bytes_per_value": 64, "safety_factor": 1.0}
    pm = PolytopeMars(config, datacube_factory=lambda: fake)

    calls = []
    original_prepare = BlockExtractor._prepare

    def spy(self, datacube, tree, **kwargs):
        calls.append(kwargs)
        return original_prepare(self, datacube, tree, **kwargs)

    original_mode = BlockExtractor._prepare_whole_tree
    BlockExtractor._prepare = spy
    if whole_tree is not None:
        BlockExtractor._prepare_whole_tree = lambda self, banded: whole_tree
    try:
        out = b"".join(pm.extract_stream(request))
    finally:
        BlockExtractor._prepare = original_prepare
        BlockExtractor._prepare_whole_tree = original_mode
    return out, dict(pm.timings), calls


@pytest.mark.parametrize("name", ["healpix_1024", "octahedral_1280", "octahedral_overlap"])
def test_per_band_prepare_gives_the_same_bytes_as_a_whole_tree_prepare(name):
    """One latitude node per band, prepared per band, is byte-identical to the prepared whole tree."""
    per_band, timings, calls = run(name, budget=1)
    whole, whole_timings, whole_calls = run(name, budget=1, whole_tree=True)
    assert per_band == whole
    assert timings["prepare_mode"] == "per_band"
    assert whole_timings["prepare_mode"] == "whole_tree"
    assert timings["n_bands"] == whole_timings["n_bands"] > timings["n_groups"]
    # nothing is prepared whole in the banded mode: every prepare is one band of one field
    assert calls and all(c.get("latitude_range") and c.get("select") for c in calls)
    assert whole_calls == [{}]


@pytest.mark.parametrize("name", ["healpix_1024", "octahedral_1280"])
def test_the_same_bytes_at_every_band_size(name):
    reference = run(name, budget=None)[0]
    for budget in (1, 64 * 8, 64 * 64, 10**9):
        out, timings, _ = run(name, budget=budget)
        assert out == reference, f"budget {budget} changed the bytes"


def test_an_overlapping_box_duplicates_points_inside_a_latitude_node_only():
    """Why per-band prepare is safe for the seam/overlap case of polytope-feature's tests."""
    from polytope_mars.coverage_plan import analyse_tree
    from polytope_mars.extract import spatial_counts

    grid, request = SHAPES["octahedral_overlap"]
    request = copy.deepcopy(request)
    fake = make_fake_gribjump(grid)
    pm = PolytopeMars(fake_gribjump_config_dict(grid, request), datacube_factory=lambda: fake)
    holder = {}
    original = BlockExtractor._slice

    def spy(self):
        holder["api"], holder["tree"] = original(self)
        return holder["api"], holder["tree"]

    BlockExtractor._slice = spy
    try:
        b"".join(pm.extract_stream(request))
    finally:
        BlockExtractor._slice = original

    tree = holder["tree"]
    info = analyse_tree(tree)
    counter = RangeCounter()
    counts = spatial_counts(info, [0])
    counter.counts(info, [0], counts)
    assert not counter.cross_node_duplicates, "an overlapping box duplicates points within a line"
