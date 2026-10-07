"""Consuming a unit's fields one at a time: the assembler, and the ``get_iter`` seam.

A multi-group unit is fetched by one call but emitted group by group: each group's blocks go out as
soon as its (param, level) fields have arrived, so the Python heap holds the incomplete groups only.
With ``limits.per_field_consumption`` the fields come from ``FDBDatacube.get_iter`` one at a time;
by default they come from one ``FDBDatacube.get`` (the whole unit at once) through the same
consumer, so both paths must produce the same bytes.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from polytope_mars.field_stream import GroupAssembler, field_key_sequence, has_per_field_consumption, unit_field_source
from polytope_mars.testing.golden import build_fake, load_case, make_polytope_mars

GOLDEN = Path(__file__).parent / "golden"


def group(key, params=("1", "2"), levels=(), branches=(0,)):
    return SimpleNamespace(key=key, params=params, levels=levels, branches=branches)


def field(values=(1.0, 2.0), missing=False):
    return np.asarray(values), missing


# --- the assembler ----------------------------------------------------------------------------------


def key(group_value, param="1", level=None) -> tuple:
    """A ``collect_field_values`` key: the group's group-axis values, then param and levelist."""
    return (group_value, param, level)


def test_a_group_is_released_as_soon_as_its_fields_have_arrived():
    a = GroupAssembler([group((0,)), group((1,))])
    first, second = key(0, "1"), key(0, "2")
    assert a.feed(first, field()) == []  # one param of group 0 still missing
    released = a.feed(second, field())
    assert [i for i, _ in released] == [0]
    assert sorted(released[0][1]) == sorted([first, second])
    assert a.n_buffered_fields == 0, "a released group's fields are handed over, not kept"
    assert not a.complete()
    a.feed(key(1, "1"), field())
    out = a.feed(key(1, "2"), field())
    assert [i for i, _ in out] == [1]
    assert a.complete()


def test_groups_are_released_in_plan_order_however_the_fields_arrive():
    """A coverage cannot be written before its predecessors: a group that completes early waits."""
    a = GroupAssembler([group((0,)), group((1,))])
    a.feed(key(1, "1"), field())
    out = a.feed(key(1, "2"), field())
    assert out == [], "group 1 is complete but group 0 is not out yet"
    a.feed(key(0, "1"), field())
    released = a.feed(key(0, "2"), field())
    assert [i for i, _ in released] == [0, 1]
    assert a.max_buffered_fields == 4


def test_only_the_incomplete_groups_are_buffered():
    """What makes the per-field path bounded: with group axes outermost, one group is held at a time."""
    groups = [group((i,)) for i in range(50)]
    a = GroupAssembler(groups)
    for i in range(50):
        a.feed(key(i, "1"), field())
        a.feed(key(i, "2"), field())
    assert a.max_buffered_fields == 2, "never more than one group's fields at once"
    assert a.complete()


def test_the_parts_of_a_key_are_concatenated_in_arrival_order():
    """A group spanning two branches gets one part per branch, in tree order, as ``get`` would."""
    a = GroupAssembler([group((0,), params=("1",), branches=(0, 1))])
    out = a.feed(key(0), field([1.0, 2.0]))
    assert out == [], "one branch of two"
    released = a.feed(key(0), field([3.0]))
    values, missing = released[0][1][key(0)]
    assert list(values) == [1.0, 2.0, 3.0] and not missing


def test_flush_releases_what_is_left_so_a_missing_field_cannot_hang_a_group():
    a = GroupAssembler([group((0,)), group((1,))])
    a.feed(key(0, "1"), field())
    released = a.flush()
    assert [i for i, _ in released] == [0, 1]
    assert list(released[0][1]) == [key(0, "1")] and released[1][1] == {}


def test_a_field_that_belongs_to_no_group_is_dropped():
    a = GroupAssembler([group((0,))])
    out = a.feed(key(9, "1"), field())
    assert out == []
    assert a.n_unknown_fields == 1 and a.n_buffered_fields == 0


# --- the key sequence the lazy path relies on ---------------------------------------------------------


def test_the_key_sequence_matches_how_a_filled_leaf_is_split():
    """``get_iter`` yields (branch, field) in the order ``collect_field_values`` splits a leaf's result."""
    from polytope_mars.coverage_plan import analyse_tree
    from polytope_mars.extract import BlockExtractor, collect_field_values

    case = load_case(GOLDEN / "cases" / "efas_bbox_multiparam.yaml")
    fake = build_fake(case)
    pm, request = make_polytope_mars(case, fake)
    holder = {}
    original = BlockExtractor._slice

    def spy(self):
        api, tree = original(self)
        holder["datacube"], holder["tree"] = api.datacube, self._prepare(api.datacube, tree)
        return api, holder["tree"]

    BlockExtractor._slice = spy
    try:
        b"".join(pm.extract_stream(request))
    finally:
        BlockExtractor._slice = original

    tree, datacube = holder["tree"], holder["datacube"]
    key_axes = ["date", "step", "param", "levelist"]
    expected = field_key_sequence(analyse_tree(tree), key_axes)
    filled = datacube.get(tree.prune())
    assert sorted(set(expected)) == sorted(collect_field_values(filled, key_axes))


# --- the seam: FDBDatacube.get_iter --------------------------------------------------------------------


MULTIPOINT = ["efas_bbox_multiparam", "o1280_bbox_ensemble", "cdt_bbox_sfc", "cdt_bbox_levelist", "efas_polygon_fc"]


def has_get_iter() -> bool:
    """Whether this polytope-feature offers ``FDBDatacube.get_iter`` at all."""
    from polytope_feature.datacube.backends.fdb import FDBDatacube

    return hasattr(FDBDatacube, "get_iter")


def expected_bytes(name):
    case = load_case(GOLDEN / "cases" / f"{name}.yaml")
    folder = "expected_fixed" if case.get("fixes") else "expected"
    return (GOLDEN / folder / f"{name}.covjson").read_bytes()


def run(name, per_field, budget=10**12, **limits):
    case = load_case(GOLDEN / "cases" / f"{name}.yaml")
    fake = build_fake(case)
    update = {"limits": {"memory_budget_bytes": budget, "per_field_consumption": per_field, **limits}}
    pm, request = make_polytope_mars(case, fake, update)
    return b"".join(pm.extract_stream(request)), pm, fake


def test_the_whole_unit_path_is_the_default():
    out, pm, _ = run("efas_bbox_multiparam", per_field=False)
    assert out == expected_bytes("efas_bbox_multiparam")
    assert pm.timings["unit_source"] == "get"


@pytest.mark.parametrize("name", MULTIPOINT)
def test_per_field_consumption_gives_the_same_bytes(name):
    """The whole request in one call, consumed field by field: identical output."""
    out, pm, fake = run(name, per_field=True)
    if pm.timings["unit_source"] == "get":
        # a single-group request never takes the multi-group path (nothing to stream), and a
        # polytope-feature without FDBDatacube.get_iter falls back to fetching the whole unit
        pytest.skip(f"whole-unit path: {pm.timings['n_groups']} group(s), get_iter is {has_get_iter()}")
    assert out == expected_bytes(name)
    assert fake.n_extract_calls == pm.timings["n_units"] == 1
    assert pm.timings["buffered_fields_max"] >= 1


def test_a_unit_whose_groups_are_separate_branches_buffers_one_group():
    """climate-dt hourly fields: one branch per datetime, so a group is complete before the next starts."""
    out, pm, _ = run("cdt_bbox_sfc", per_field=True)
    if pm.timings["unit_source"] == "get":
        pytest.skip(f"whole-unit path: get_iter is {has_get_iter()}")
    assert out == expected_bytes("cdt_bbox_sfc")
    doc = json.loads(out)
    params_per_group = len(doc["parameters"])
    assert pm.timings["n_groups"] == 4
    assert pm.timings["buffered_fields_max"] <= params_per_group


@pytest.mark.parametrize("missing_mode", ["raise", "empty"])
def test_missing_fields_fall_back_the_same_way(missing_mode):
    case = load_case(GOLDEN / "cases" / "o1280_bbox_missing_field.yaml")
    fake = build_fake(case, missing_mode=missing_mode)
    update = {"limits": {"memory_budget_bytes": 10**12, "per_field_consumption": True}}
    pm, request = make_polytope_mars(case, fake, update)
    out = b"".join(pm.extract_stream(request))
    assert out == expected_bytes("o1280_bbox_missing_field")


def test_unit_field_source_reports_the_path():
    assert unit_field_source(SimpleNamespace(), enabled=True) == "get"
    streaming = SimpleNamespace(get_iter=lambda *a, **k: iter(()))
    assert has_per_field_consumption(streaming)
    assert unit_field_source(streaming, enabled=True) == "get_iter"
    assert unit_field_source(streaming, enabled=False) == "get"
