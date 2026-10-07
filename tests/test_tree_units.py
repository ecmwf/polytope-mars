"""Extraction units of several field groups: the planner, the multi-value tree pruning, and the
compressed-axes order the per-(group, param, level) split relies on.

The split assumes one rule about ``polytope_feature``: a leaf's ``result`` holds its points once per
field of the branch, the fields in C-order over the branch's compressed axes in tree order (root to
leaf).  ``FDBDatacube._gribjump_requests`` builds the requests with ``product()`` over the leaf path's
keys, which ``get_fdb_requests`` inserts while it descends the tree, and
``assign_fdb_output_to_nodes`` appends the results in that order.  The first test pins it on real
``FDBDatacube`` output instead of trusting the reading.
"""

import copy
from pathlib import Path

import numpy as np
import pytest

from polytope_mars.coverage_plan import analyse_tree, spatial_children
from polytope_mars.extract import BlockExtractor, collect_field_values
from polytope_mars.testing.fake_gribjump import decode_value
from polytope_mars.testing.golden import build_fake, load_case, make_polytope_mars
from polytope_mars.tree_units import GroupSpec, plan_units, prune_values, unit_select

GOLDEN = Path(__file__).parent / "golden"


class _Sliced(Exception):
    """Raised by the spy to stop a run once the tree is sliced and prepared."""


def prepared(name, monkeypatch, **request_update):
    """``(datacube, prepared tree, fake)`` of a golden case; nothing is extracted yet."""
    c = copy.deepcopy(load_case(GOLDEN / "cases" / f"{name}.yaml"))
    c["request"].update(request_update)
    fake = build_fake(c)
    pm, request = make_polytope_mars(c, fake)
    holder = {}
    original = BlockExtractor._slice_and_prepare

    def spy(self):
        holder["api"], holder["tree"] = original(self)
        raise _Sliced

    monkeypatch.setattr(BlockExtractor, "_slice_and_prepare", spy)
    with pytest.raises(_Sliced):
        b"".join(pm.extract_stream(request))
    return holder["api"].datacube, holder["tree"], fake


def first_leaf(tree):
    branch = analyse_tree(tree).branches[0]
    return spatial_children(branch.node)[0].children[0]


# --- the order the fields of one leaf arrive in --------------------------------------------------------


def test_compressed_axes_expand_as_a_product_in_tree_order(monkeypatch):
    datacube, tree, fake = prepared("efas_bbox_multiparam", monkeypatch, date="20240101", step="6/12/18")
    branch = analyse_tree(tree).branches[0]
    compressed = [(axis, values) for axis, values in branch.path if len(values) > 1]
    assert [axis for axis, _ in compressed] == ["param", "step"], "tree order: param above step"

    filled = datacube.get(tree.prune())
    leaf = first_leaf(filled)
    n = len(leaf.values)
    fields = [(param, step) for param in ("240023", "240024") for step in ("6", "12", "18")]
    assert len(leaf.result) == len(fields) * n

    got = []
    for i in range(len(fields)):
        chunk = np.asarray(leaf.result[i * n : (i + 1) * n], dtype=np.float64)  # noqa: E203
        ids = {decode_value(v)[0] for v in chunk}
        assert len(ids) == 1, f"field {i} of the leaf mixes {len(ids)} fields"
        path = fake.fields[ids.pop()]
        got.append((str(path["param"]), str(path["step"])))
    assert got == fields


# --- planning the units ----------------------------------------------------------------------------------


def group_spec(key, n_points=10, params=("1",), levels=(), bytes_per_point=1):
    n_fields = len(params) * (len(levels) or 1)
    return GroupSpec(
        key=key,
        shape=(n_points, params, levels),
        nbytes=n_points * n_fields * bytes_per_point,
        counts=(n_points,),
    )


def units(specs, budget, **kwargs) -> str:
    """The planned units as ``"<start>+<groups> ..."``, e.g. ``"0+3 3+3 6+1"``."""
    return " ".join(f"{start}+{length}" for start, length in plan_units(specs, budget, **kwargs))


def test_without_a_budget_every_unit_is_one_group():
    specs = [group_spec((i,)) for i in range(5)]
    assert units(specs, None) == "0+1 1+1 2+1 3+1 4+1"


def test_a_unit_is_the_longest_run_that_fits_the_budget():
    specs = [group_spec((i,)) for i in range(7)]  # 10 bytes per group
    assert units(specs, 30) == "0+3 3+3 6+1"
    assert units(specs, 39) == "0+3 3+3 6+1"
    assert units(specs, 10**9) == "0+7"
    assert units(specs, 9) == "0+1 1+1 2+1 3+1 4+1 5+1 6+1"  # not even one group fits
    assert units(specs, 10**9, max_groups=2) == "0+2 2+2 4+2 6+1"


def test_a_unit_does_not_cross_a_change_of_points_params_or_levels():
    points = [group_spec((0,)), group_spec((1,)), group_spec((2,), n_points=20), group_spec((3,), n_points=20)]
    assert units(points, 10**9) == "0+2 2+2"
    params = [group_spec((0,)), group_spec((1,), params=("1", "2"))]
    assert units(params, 10**9) == "0+1 1+1"
    levels = [group_spec((0,), levels=("500",)), group_spec((1,), levels=("850",))]
    assert units(levels, 10**9) == "0+1 1+1"


def test_a_unit_is_a_cartesian_product_of_its_group_axis_values():
    # 3 numbers x 2 steps, numbers outer: 3 consecutive groups are not a product, 4 are
    specs = [group_spec((number, step)) for number in (1, 2, 3) for step in (0, 6)]
    assert units(specs, 20) == "0+2 2+2 4+2"
    assert units(specs, 30) == "0+2 2+2 4+2"
    assert units(specs, 50) == "0+4 4+2"
    assert units(specs, 60) == "0+6"


def test_a_group_without_a_value_on_every_group_axis_stays_its_own_unit():
    specs = [group_spec(None), group_spec((1,)), group_spec((2,))]
    assert units(specs, 10**9) == "0+1 1+2"


def test_unit_select_lists_the_values_in_plan_order():
    specs = [group_spec((number, step)) for number in (1, 2) for step in (6, 12)]
    whole = unit_select(specs, 0, 4, ["number", "step"])
    assert {axis: list(values) for axis, values in whole.items()} == {"number": [1, 2], "step": [6, 12]}
    tail = unit_select(specs, 2, 2, ["number", "step"])
    assert {axis: list(values) for axis, values in tail.items()} == {"number": [2], "step": [6, 12]}


# --- pruning a tree to the values of a unit ---------------------------------------------------------------


def test_prune_values_keeps_the_selected_values_and_leaves_the_tree_untouched(monkeypatch):
    datacube, tree, fake = prepared("efas_bbox_fc_steps", monkeypatch)  # one branch, steps 6/12/18
    sub = prune_values(tree, {"step": (6, 18)})
    assert list(dict(analyse_tree(sub).branches[0].path)["step"]) == [6, 18]

    fields = collect_field_values(datacube.get(sub), ["step", "param"])
    assert sorted(step for step, _ in fields) == [6, 18]
    assert {len(values) for values, _ in fields.values()} == {36}
    assert all(len(leaf.result) == 0 for leaf in tree.leaves), "the parent tree must stay unfilled"
    assert list(dict(analyse_tree(tree).branches[0].path)["step"]) == [6, 12, 18]


def test_prune_values_selects_whole_branches(monkeypatch):
    # climate-dt merges date and time into one axis and slices one branch per datetime
    datacube, tree, fake = prepared("cdt_bbox_sfc", monkeypatch)
    dates = analyse_tree(tree).values["date"]
    assert len(dates) == 4
    sub = prune_values(tree, {"date": tuple(dates[:2])})
    pruned = analyse_tree(sub)
    assert len(pruned.branches) == 2 and pruned.values["date"] == list(dates[:2])


def test_prune_values_rejects_unknown_values_and_spatial_axes(monkeypatch):
    datacube, tree, fake = prepared("efas_bbox_fc_steps", monkeypatch)
    with pytest.raises(ValueError, match="Values not found in tree: step"):
        prune_values(tree, {"step": (5,)})
    with pytest.raises(ValueError, match="spatial axis 'latitude'"):
        prune_values(tree, {"latitude": (0.0,)})
    with pytest.raises(ValueError, match="root of a tree"):
        prune_values(tree.children[0], {"step": (6,)})
