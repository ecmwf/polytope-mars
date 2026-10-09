"""Consuming a unit's fields one at a time: the assembler, and the ``get_iter`` seam.

A multi-group unit is fetched by one call but emitted group by group: each group's blocks go out as
soon as its (param, level) fields have arrived, so the Python heap holds the incomplete groups only.
With ``limits.per_field_consumption`` the fields come from ``FDBDatacube.get_iter`` one at a time;
by default they come from one ``FDBDatacube.get`` (the whole unit at once) through the same
consumer, so both paths must produce the same bytes.
"""

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


def has_get_iter() -> bool:
    """Whether this polytope-feature offers ``FDBDatacube.get_iter`` at all."""
    from polytope_feature.datacube.backends.fdb import FDBDatacube

    return hasattr(FDBDatacube, "get_iter")


def expected_bytes(name):
    case = load_case(GOLDEN / "cases" / f"{name}.yaml")
    folder = "expected_fixed" if case.get("fixes") else "expected"
    return (GOLDEN / folder / f"{name}.covjson").read_bytes()


def run(name, per_field, budget=10**12, request_update=None, **limits):
    case = load_case(GOLDEN / "cases" / f"{name}.yaml")
    case["request"].update(request_update or {})
    fake = build_fake(case)
    limits = {"memory_budget_bytes": budget, **limits}
    if per_field is not None:
        limits["per_field_consumption"] = per_field
    pm, request = make_polytope_mars(case, fake, {"limits": limits})
    return b"".join(pm.extract_stream(request)), pm, fake


def test_the_per_field_path_is_the_default():
    """``limits.per_field_consumption`` is on, so a multi-group unit streams its fields."""
    out, pm, _ = run("efas_bbox_multiparam", per_field=None)
    assert out == expected_bytes("efas_bbox_multiparam")
    assert pm.timings["unit_source"] == "get_iter"


def test_the_whole_unit_path_is_the_opt_out():
    out, pm, _ = run("efas_bbox_multiparam", per_field=False)
    assert out == expected_bytes("efas_bbox_multiparam")
    assert pm.timings["unit_source"] == "get"


def test_a_whole_request_in_one_call_is_consumed_field_by_field():
    """Six groups fetched by one call and emitted as their fields arrive: identical output.

    The same cases at this budget are byte-checked by
    ``tests/test_streaming.py::test_large_budget_is_one_unit_for_all_groups``; what this adds is that
    the fields came through ``get_iter`` one at a time.
    """
    out, pm, fake = run("o1280_bbox_ensemble", per_field=True)
    if pm.timings["unit_source"] == "get":
        # a polytope-feature without FDBDatacube.get_iter falls back to fetching the whole unit
        pytest.skip(f"whole-unit path: get_iter is {has_get_iter()}")
    assert out == expected_bytes("o1280_bbox_ensemble")
    assert fake.n_extract_calls == pm.timings["n_units"] == 1
    assert pm.timings["buffered_fields_max"] >= 1


def test_a_unit_whose_groups_are_separate_branches_buffers_one_group():
    """climate-dt hourly fields: one branch per datetime, so a group is complete before the next starts."""
    out, pm, _ = run("cdt_bbox_sfc", per_field=True)
    if pm.timings["unit_source"] == "get":
        pytest.skip(f"whole-unit path: get_iter is {has_get_iter()}")
    assert out == expected_bytes("cdt_bbox_sfc")
    case = load_case(GOLDEN / "cases" / "cdt_bbox_sfc.yaml")
    params_per_group = len(str(case["request"]["param"]).split("/"))
    assert pm.timings["n_groups"] == 4
    assert pm.timings["buffered_fields_max"] <= params_per_group


def test_only_one_groups_fields_are_alive_at_a_time():
    """What the sizing of the per-field path rests on: the unit's other groups are not on the heap.

    A ten-group unit (one EFAS step per group) is fetched by one call and every field array handed
    over by ``get_iter`` is weak-referenced: while the stream runs, only the fields of the group
    being emitted (plus the one in flight) are ever alive, whatever the unit's size.
    """
    import gc
    import weakref

    from polytope_mars import extract as extract_mod

    live: list = []
    original = extract_mod.lazy_unit_fields

    def tracking(datacube, tree, key_axes, context=None, **kwargs):
        for key, (values, missing) in original(datacube, tree, key_axes, context, **kwargs):
            live.append(weakref.ref(values))
            yield key, (values, missing)

    steps = "/".join(str(s) for s in range(6, 66, 6))  # ten groups of one field
    extract_mod.lazy_unit_fields = tracking
    alive = []
    try:
        case = load_case(GOLDEN / "cases" / "efas_bbox_fc_steps.yaml")
        case["request"]["step"] = steps
        fake = build_fake(case)
        update = {"limits": {"memory_budget_bytes": 10**12, "per_field_consumption": True}}
        pm, request = make_polytope_mars(case, fake, update)
        for _chunk in pm.extract_stream(request):
            gc.collect()
            alive.append(sum(1 for ref in live if ref() is not None))
    finally:
        extract_mod.lazy_unit_fields = original

    if pm.timings["unit_source"] == "get":
        pytest.skip(f"whole-unit path: get_iter is {has_get_iter()}")
    assert pm.timings["n_groups"] == 10 and fake.n_extract_calls == 1
    assert len(live) == 10, "one field per group was streamed"
    assert max(alive) <= 2, f"fields alive at once over the stream: {alive}"
    gc.collect()
    assert sum(1 for ref in live if ref() is not None) == 0, "every field is released by the end"


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
