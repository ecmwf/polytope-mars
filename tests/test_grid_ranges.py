"""Index ranges counted from the prepared tree are the ranges gribjump is actually asked for.

The sizing needs the range count before anything is fetched (:mod:`polytope_mars.sizing`), so
:mod:`polytope_mars.grid_ranges` recomputes what ``FDBDatacube._gribjump_requests`` builds.  These
tests pin the two against each other on every grid family of the corpus: the counter's total must
equal ``timings["n_ranges_requested"]``, which counts the ranges of the requests the fake gribjump
received.
"""

import copy
from pathlib import Path

import pytest

from polytope_mars.coverage_plan import analyse_tree
from polytope_mars.extract import BlockExtractor
from polytope_mars.grid_ranges import RangeCounter, spatial_range_counts
from polytope_mars.testing.golden import build_fake, load_case, make_polytope_mars

GOLDEN = Path(__file__).parent / "golden"


class _Sliced(Exception):
    """Raised by the spy to stop a run once the tree is sliced and prepared."""


def prepared_tree(name):
    """The sliced and prepared tree of a golden case; nothing is extracted."""
    c = copy.deepcopy(load_case(GOLDEN / "cases" / f"{name}.yaml"))
    pm, request = make_polytope_mars(c, build_fake(c))
    holder = {}
    original = BlockExtractor._slice_and_prepare

    def spy(self):
        holder["api"], holder["tree"] = original(self)
        raise _Sliced

    BlockExtractor._slice_and_prepare = spy
    try:
        with pytest.raises(_Sliced):
            b"".join(pm.extract_stream(request))
    finally:
        BlockExtractor._slice_and_prepare = original
    return holder["tree"]


def counted_ranges(tree) -> int:
    """Ranges the whole tree costs: per branch, its ranges once per field of the branch."""
    info = analyse_tree(tree)
    total = 0
    for branch in info.branches:
        n_fields = 1
        for _, values in branch.path:
            n_fields *= len(values)
        total += sum(spatial_range_counts(branch.node)) * n_fields
    return total


def run(name, budget=None):
    c = load_case(GOLDEN / "cases" / f"{name}.yaml")
    fake = build_fake(c)
    pm, request = make_polytope_mars(c, fake, {"limits": {"memory_budget_bytes": budget}})
    b"".join(pm.extract_stream(request))
    return pm


# one case per mapper family and per tree shape (compressed rows, merged polygon rows, levels)
CASES = [
    "efas_bbox_multiparam",  # local_regular, 2 dates x 2 steps x 2 params
    "o1280_bbox_ensemble",  # octahedral, 3 numbers x 2 steps
    "cdt_bbox_sfc",  # healpix_nested, merged date/time axis (one branch per datetime)
    "cdt_bbox_levelist",  # healpix_nested, 2 params x 2 levels
    "efas_polygon_fc",  # local_regular, merged polygon rows
    "cdt_polygon_sfc",  # healpix_nested, merged polygon rows
    "clmn_bbox",  # monthly climate-dt
]


@pytest.mark.parametrize("name", CASES)
def test_counted_ranges_equal_the_ranges_gribjump_is_asked_for(name):
    expected = counted_ranges(prepared_tree(name))
    assert expected > 0
    assert run(name).timings["n_ranges_requested"] == expected
    # the same ranges however the request is cut into units: one unit for everything, and bands
    assert run(name, budget=10**12).timings["n_ranges_requested"] == expected
    assert run(name, budget=1).timings["n_ranges_requested"] == expected


@pytest.mark.parametrize("name", ["cdt_bbox_sfc", "o1280_bbox_ensemble"])
def test_timings_report_the_ranges_of_one_field(name):
    """``n_ranges`` is per field of the largest group: what the sizing multiplies by the unit's fields."""
    tree = prepared_tree(name)
    info = analyse_tree(tree)
    per_branch = sum(spatial_range_counts(info.branches[0].node))
    assert run(name).timings["n_ranges"] == per_branch


def test_the_counter_walks_one_spatial_sub_tree_per_shape():
    """The groups of a request share their spatial sub-tree: counting it once is enough."""
    tree = prepared_tree("cdt_bbox_sfc")  # 4 datetimes, one branch each
    info = analyse_tree(tree)
    counter = RangeCounter()
    counts = [counter.counts(info, [b], [len(info.branches[b].node.children)]) for b in range(len(info.branches))]
    assert len(info.branches) == 4
    assert counter.n_counted == 1, "identical spatial shapes must come from the cache"
    assert all(c == counts[0] for c in counts)


def test_healpix_nested_needs_far_more_ranges_than_a_gaussian_grid():
    """The reason the sizing counts ranges instead of using a per-grid constant."""
    healpix = prepared_tree("cdt_bbox_sfc")
    octahedral = prepared_tree("o1280_bbox_ensemble")
    info = analyse_tree(healpix)
    nested_ranges = sum(spatial_range_counts(info.branches[0].node))
    nested_points = sum(len(leaf.values) for leaf in info.branches[0].node.children[0].children)
    info = analyse_tree(octahedral)
    gaussian_ranges = sum(spatial_range_counts(info.branches[0].node))
    # one range per latitude line on the octahedral box, several per line on HEALPix nested
    assert gaussian_ranges == len(info.branches[0].node.children)
    assert nested_ranges > nested_points
