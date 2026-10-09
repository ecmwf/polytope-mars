"""Extraction units of several field groups: the planner, the multi-value tree pruning, and the
compressed-axes order the per-(group, param, level) split relies on.

The split assumes one rule about ``polytope_feature``: a bulk spatial node's ``result`` holds one array
of its points per field of the branch, the fields in C-order over the branch's compressed axes in tree
order (root to leaf).  ``FDBDatacube._gribjump_requests`` builds the requests with ``product()`` over
the leaf path's keys, which ``get_fdb_requests`` inserts while it descends the tree, and
``assign_bulk_result`` appends the results in that order.  The first test pins it on real
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
from polytope_mars.tree_units import GroupSpec, plan_units, unit_select

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
    original = BlockExtractor._slice

    def spy(self):
        api, tree = original(self)
        holder["api"], holder["tree"] = api, self._prepare(api.datacube, tree)
        raise _Sliced

    monkeypatch.setattr(BlockExtractor, "_slice", spy)
    with pytest.raises(_Sliced):
        b"".join(pm.extract_stream(request))
    return holder["api"].datacube, holder["tree"], fake


def first_spatial_node(tree):
    """The first bulk spatial node of a tree: one array-backed node per spatial sub-tree."""
    branch = analyse_tree(tree).branches[0]
    return spatial_children(branch.node)[0]


# --- the order the fields of one leaf arrive in --------------------------------------------------------


def test_compressed_axes_expand_as_a_product_in_tree_order(monkeypatch):
    datacube, tree, fake = prepared("efas_bbox_multiparam", monkeypatch, date="20240101", step="6/12/18")
    branch = analyse_tree(tree).branches[0]
    compressed = [(axis, values) for axis, values in branch.path if len(values) > 1]
    assert [axis for axis, _ in compressed] == ["param", "step"], "tree order: param above step"

    filled = datacube.get(tree.prune())
    node = first_spatial_node(filled)
    fields = [(param, step) for param in ("240023", "240024") for step in ("6", "12", "18")]
    assert len(node.result) == len(fields), "one result array per field of the branch"

    got = []
    for i, values in enumerate(node.result):
        chunk = np.asarray(values, dtype=np.float64)
        assert len(chunk) == node.point_count
        ids = {decode_value(v)[0] for v in chunk}
        assert len(ids) == 1, f"field {i} of the node mixes {len(ids)} fields"
        path = fake.fields[ids.pop()]
        got.append((str(path["param"]), str(path["step"])))
    assert got == fields


def extract_calls(name, fields_per_call, **limits) -> list:
    """The ``(number, step)`` pairs each ``gribjump.extract`` call asked for, in call order."""
    c = load_case(GOLDEN / "cases" / f"{name}.yaml")
    fake = build_fake(c)
    calls: list = []
    original = fake.extract

    def spy(requests, ctx=None):
        requests = list(requests)
        pairs = {(int(r[0]["number"]), int(r[0]["step"])) for r in requests}
        calls.append(sorted(pairs))
        return original(requests, ctx)

    fake.extract = spy
    update = {"limits": {"memory_budget_bytes": 10**12, "max_fields_per_call": fields_per_call, **limits}}
    pm, request = make_polytope_mars(c, fake, update)
    b"".join(pm.extract_stream(request))
    return calls


def test_an_efas_ensemble_unit_batches_the_members_of_one_step():
    """class=ce coverages come out (reference, step, number), so a unit is members at one step.

    The Volga ensemble shape (50 members x 60 steps): consecutive groups are the members of one
    step, so one call fetches several *members* of the same step, and a call can only cover two
    steps once it has room for every member of one.
    """
    # room for two groups (2 members x 2 params per group)
    assert extract_calls("efas_bbox_ensemble", 4) == [
        [(1, 6), (2, 6)],
        [(1, 12), (2, 12)],
        [(1, 18), (2, 18)],
    ]
    # room for four groups: both members of two steps (a 2 x 2 rectangle of the group axes)
    assert extract_calls("efas_bbox_ensemble", 8) == [
        [(1, 6), (1, 12), (2, 6), (2, 12)],
        [(1, 18), (2, 18)],
    ]


# --- planning the units ----------------------------------------------------------------------------------


def group_spec(key, max_groups=1, n_points=10, params=("1",), levels=()):
    return GroupSpec(
        key=key,
        shape=(n_points, params, levels),
        max_groups=max_groups,
        counts=(n_points,),
        range_counts=(1,),
    )


def units(specs, **kwargs) -> str:
    """The planned units as ``"<start>+<groups> ..."``, e.g. ``"0+3 3+3 6+1"``."""
    return " ".join(f"{start}+{length}" for start, length in plan_units(specs, **kwargs))


def run_of(n, **kwargs) -> list:
    """``n`` consecutive groups on one group axis, all of the same shape."""
    return [group_spec((i,), **kwargs) for i in range(n)]


def test_groups_that_pay_for_one_call_each_are_their_own_unit():
    """``GroupSpec.max_groups`` 1 -- what the sizing gives without a budget -- is one call per group."""
    assert units(run_of(5)) == "0+1 1+1 2+1 3+1 4+1"


def test_a_unit_is_the_longest_run_the_memory_model_pays_for():
    assert units(run_of(7, max_groups=3)) == "0+3 3+3 6+1"
    assert units(run_of(7, max_groups=10**9)) == "0+7"
    # a group that does not fit even alone stays its own unit (it is fetched one field per call)
    assert units(run_of(3, max_groups=0)) == "0+1 1+1 2+1"
    assert units(run_of(7, max_groups=10**9), max_groups=2) == "0+2 2+2 4+2 6+1"


def test_a_unit_does_not_cross_a_change_of_points_params_or_levels():
    big = 10**9
    points = [group_spec((i,), max_groups=big) for i in (0, 1)]
    points += [group_spec((i,), max_groups=big, n_points=20) for i in (2, 3)]
    assert units(points) == "0+2 2+2"
    params = [group_spec((0,), max_groups=big), group_spec((1,), max_groups=big, params=("1", "2"))]
    assert units(params) == "0+1 1+1"
    levels = [group_spec((0,), max_groups=big, levels=("500",)), group_spec((1,), max_groups=big, levels=("850",))]
    assert units(levels) == "0+1 1+1"


def test_a_unit_is_a_cartesian_product_of_its_group_axis_values():
    # 3 numbers x 2 steps, numbers outer: 3 consecutive groups are not a product, 4 are
    def specs(max_groups):
        return [group_spec((number, step), max_groups=max_groups) for number in (1, 2, 3) for step in (0, 6)]

    assert units(specs(2)) == "0+2 2+2 4+2"
    assert units(specs(3)) == "0+2 2+2 4+2"
    assert units(specs(5)) == "0+4 4+2"
    assert units(specs(6)) == "0+6"


def test_a_group_without_a_value_on_every_group_axis_stays_its_own_unit():
    specs = [group_spec(None, max_groups=10**9)] + [group_spec((i,), max_groups=10**9) for i in (1, 2)]
    assert units(specs) == "0+1 1+2"


def test_unit_select_lists_the_values_in_plan_order():
    specs = [group_spec((number, step)) for number in (1, 2) for step in (6, 12)]
    whole = unit_select(specs, 0, 4, ["number", "step"])
    assert {axis: list(values) for axis, values in whole.items()} == {"number": [1, 2], "step": [6, 12]}
    tail = unit_select(specs, 2, 2, ["number", "step"])
    assert {axis: list(values) for axis, values in tail.items()} == {"number": [2], "step": [6, 12]}


# --- pruning a tree to the values of a unit ---------------------------------------------------------------


def test_pruning_to_a_units_values_leaves_the_tree_untouched(monkeypatch):
    datacube, tree, fake = prepared("efas_bbox_fc_steps", monkeypatch)  # one branch, steps 6/12/18
    sub = tree.prune(select={"step": (6, 18)})
    assert list(dict(analyse_tree(sub).branches[0].path)["step"]) == [6, 18]

    fields = collect_field_values(datacube.get(sub), ["step", "param"])
    assert sorted(step for step, _ in fields) == [6, 18]
    assert {len(values) for values, _ in fields.values()} == {36}
    assert len(first_spatial_node(tree).result) == 0, "the parent tree must stay unfilled"
    assert list(dict(analyse_tree(tree).branches[0].path)["step"]) == [6, 12, 18]


def test_pruning_to_a_units_values_selects_whole_branches(monkeypatch):
    # climate-dt date and time are separate compressed axes: 2 dates x 2 times in one spatial sub-tree
    datacube, tree, fake = prepared("cdt_bbox_sfc", monkeypatch)
    info = analyse_tree(tree)
    dates = info.values["date"]
    assert len(dates) == 2 and len(info.values["time"]) == 2 and len(info.branches) == 1
    sub = tree.prune(select={"date": (dates[0],)})
    pruned = analyse_tree(sub)
    assert len(pruned.branches) == 1 and pruned.values["date"] == [dates[0]] and len(pruned.values["time"]) == 2


def test_pruning_rejects_unknown_values_and_spatial_axes(monkeypatch):
    datacube, tree, fake = prepared("efas_bbox_fc_steps", monkeypatch)
    with pytest.raises(ValueError, match="Values not found in tree: step"):
        tree.prune(select={"step": (5,)})
    with pytest.raises(ValueError, match="spatial axis 'latitude'"):
        tree.prune(select={"latitude": (0.0,)})
    with pytest.raises(ValueError, match="root of a tree"):
        tree.children[0].prune(select={"step": (6,)})
