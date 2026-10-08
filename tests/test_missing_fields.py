"""Missing fields reported by gribjump as ``DataNotFound`` (the remote gribjump) instead of empty results.

The fake raises like the real server by default (``missing_mode="raise"``): any ``extract`` call that
includes a missing field fails as a whole.  The extractor re-fetches the failed unit in smaller pieces; the
output must be what the empty-result reporting (``missing_mode="empty"``) gives.
"""

import copy
import json
from pathlib import Path

import pygribjump
import pytest
from polytope_feature.utility.exceptions import GribJumpNoIndexError

from polytope_mars.extract import is_data_not_found, matched_no_field
from polytope_mars.testing import FakeGribJump
from polytope_mars.testing.golden import build_fake, load_case, make_polytope_mars

GOLDEN = Path(__file__).parent / "golden"


def case(name, missing=None):
    c = load_case(GOLDEN / "cases" / f"{name}.yaml")
    if missing is not None:
        c = copy.deepcopy(c)
        c.setdefault("fake", {})["missing"] = missing
    return c


def expected(name):
    c = case(name)
    folder = "expected_fixed" if c.get("fixes") else "expected"
    return (GOLDEN / folder / f"{name}.covjson").read_bytes()


def run(c, mode="raise", budget=None, fake=None, **limits):
    fake = build_fake(c, missing_mode=mode) if fake is None else fake
    pm, request = make_polytope_mars(c, fake, {"limits": {"memory_budget_bytes": budget, **limits}})
    return b"".join(pm.extract_stream(request)), pm, fake


#: Forces one ``datacube.get`` per (param, level): the path a group that does not fit one call takes.
PER_FIELD = {"budget": 10**12, "max_fields_per_call": 1}


def both_modes(c, budget=None, **limits):
    """(raise-mode run, empty-mode run); asserts the bytes are equal."""
    raised = run(c, "raise", budget, **limits)
    empty = run(c, "empty", budget, **limits)
    assert raised[0] == empty[0]
    return raised, empty


# --- the predicate ---------------------------------------------------------------------------------------


def test_is_data_not_found_matches_gribjump_exception_by_name_and_message():
    msg = (
        "Error in function 'gribjump_extract': GribJumpException: DataNotFound. Matched 0 fields but 1 were requested."
    )
    assert is_data_not_found(pygribjump.GribJumpException(msg))

    class GribJumpException(RuntimeError):  # a stand-in of the same name (no pygribjump needed)
        pass

    class Derived(GribJumpException):
        pass

    assert is_data_not_found(GribJumpException(msg)) and is_data_not_found(Derived(msg))
    assert not is_data_not_found(pygribjump.GribJumpException("BadValue: Grid hash mismatch"))
    assert not is_data_not_found(RuntimeError(msg))  # right message, wrong class
    assert not is_data_not_found(ConnectionError("DataNotFound"))


def test_matched_no_field_reads_the_match_count():
    assert matched_no_field(Exception("DataNotFound. Matched 0 fields but 1 were requested."))
    assert not matched_no_field(Exception("DataNotFound. Matched 1 fields but 2 were requested."))
    assert not matched_no_field(Exception("DataNotFound. Matched 10 fields but 20 were requested."))
    assert not matched_no_field(Exception("DataNotFound"))  # unreadable: the unit is split up


# --- MultiPoint: whole-group unit --------------------------------------------------------------------------


def test_whole_group_fallback_keeps_present_params():
    # 4 groups (2 dates x 2 steps) of 2 params; 228 is missing at step 6 of 20240102.
    (out, pm, fake), (_, pm_empty, fake_empty) = both_modes(case("o1280_bbox_missing_field"))
    assert out == expected("o1280_bbox_missing_field")
    doc = json.loads(out)
    assert [sorted(c["ranges"]) for c in doc["coverages"]] == [["2t", "tp"]] * 3 + [["2t"]]
    # 3 groups in one call each; the 4th: one failed call, then one call per param (167 found, 228 not)
    assert fake.n_extract_calls == pm.timings["n_gribjump_calls"] == 3 + 1 + 2
    assert fake.n_data_not_found == 2
    assert pm.timings["n_fallbacks"] == 1 and pm.timings["n_missing_fields"] == 1
    assert pm.timings["n_groups"] == pm.timings["n_coverages"] == 4
    # the empty-result reporting needs no fallback
    assert fake_empty.n_extract_calls == 4
    assert pm_empty.timings["n_fallbacks"] == 0 and pm_empty.timings["n_missing_fields"] == 1


def test_whole_group_with_all_params_missing_has_no_coverage():
    c = case("o1280_bbox_missing_field", missing=[{"date": "20240102", "step": "6"}])
    (out, pm, fake), _ = both_modes(c)
    doc = json.loads(out)
    assert len(doc["coverages"]) == 3
    assert [cov["mars:metadata"]["step"] for cov in doc["coverages"]] == [0, 6, 0]
    # "Matched 0 fields": the failed call is enough, nothing is re-fetched
    assert fake.n_extract_calls == 3 + 1 and fake.n_data_not_found == 1
    assert pm.timings["n_missing_fields"] == 2 and pm.timings["n_fallbacks"] == 0
    assert pm.timings["n_groups"] == 3


def test_single_field_group_missing_costs_one_call():
    # one param: the failed call itself says the field is missing, nothing is re-fetched
    (out, pm, fake), _ = both_modes(case("o1280_bbox_missing_last_date"))
    assert out == expected("o1280_bbox_missing_last_date")
    assert fake.n_extract_calls == 2 and fake.n_data_not_found == 1
    assert pm.timings["n_fallbacks"] == 0 and pm.timings["n_missing_fields"] == 1


def ten_group_case(missing):
    """EFAS bbox, one date x 10 steps x 2 params (10 field groups), with ``missing`` fields."""
    c = copy.deepcopy(case("efas_bbox_multiparam"))
    c["request"]["date"] = "20240101"
    c["request"]["step"] = "/".join(str(6 * i) for i in range(1, 11))
    c.setdefault("fake", {})["missing"] = missing
    return c


def test_multi_group_unit_falls_back_per_group():
    # all fields of step 24 are missing: the unit of 10 groups is re-fetched one group at a time
    c = ten_group_case([{"step": "24"}])
    (out, pm, fake), _ = both_modes(c, budget=10**12)
    doc = json.loads(out)
    assert [cov["mars:metadata"]["step"] for cov in doc["coverages"]] == [6, 12, 18, 30, 36, 42, 48, 54, 60]
    assert all(sorted(cov["ranges"]) == ["dis06", "dis24"] for cov in doc["coverages"])
    assert out == run(c, "raise")[0]  # same bytes as one unit per group
    # the unit's failed call, then one call per group; step 24 says "Matched 0 fields" and is not split
    assert fake.n_extract_calls == 1 + 10 and fake.n_data_not_found == 2
    assert pm.timings["n_fallbacks"] == 1 and pm.timings["n_missing_fields"] == 2
    assert pm.timings["n_groups"] == 9 and pm.timings["groups_per_unit_max"] == 10


def test_multi_group_unit_fallback_keeps_the_params_that_exist():
    # only dis24 is missing at step 24: that group keeps dis06, the other nine keep both params
    c = ten_group_case([{"step": "24", "param": "240024"}])
    (out, pm, fake), _ = both_modes(c, budget=10**12)
    doc = json.loads(out)
    ranges = {cov["mars:metadata"]["step"]: sorted(cov["ranges"]) for cov in doc["coverages"]}
    assert ranges[24] == ["dis06"]
    assert all(r == ["dis06", "dis24"] for step, r in ranges.items() if step != 24)
    assert out == run(c, "raise")[0]
    # unit + 9 groups + the failing group (1 call) + its two per-param band-0 peeks
    assert fake.n_extract_calls == 1 + 9 + 1 + 2 and fake.n_data_not_found == 3
    assert pm.timings["n_fallbacks"] == 2 and pm.timings["n_missing_fields"] == 1


def lowest_level_missing(name):
    """``case(name)`` with its first level (string order) missing for every param and group."""
    first = json.loads(expected(name))["coverages"][0]["domain"]["axes"]["composite"]["values"]
    level = sorted({str(v[2]) for v in first})[0]
    return case(name, missing=[{"levelist": level}])


def test_whole_group_fallback_with_a_missing_level():
    # a present param with one missing level keeps its range, with nulls for that level
    c = lowest_level_missing("cdt_bbox_levelist")
    (out, pm, fake), _ = both_modes(c)
    assert out != expected("cdt_bbox_levelist")
    assert b"NaN" not in out
    assert pm.timings["n_fallbacks"] == pm.timings["n_groups"] > 0
    assert run(c, "raise", **PER_FIELD)[0] == out
    assert run(c, "raise", budget=10**12)[0] == out


# --- MultiPoint: one call per (param, level) -----------------------------------------------------------------


def test_a_data_not_found_per_field_call_marks_that_field_missing():
    # 4 groups x 2 params, one call each: the missing field is the call that raises, so nothing is
    # re-fetched and no peek is needed
    (out, pm, fake), _ = both_modes(case("o1280_bbox_missing_field"), **PER_FIELD)
    assert out == expected("o1280_bbox_missing_field")
    assert fake.n_extract_calls == 4 * 2
    assert fake.n_data_not_found == 1
    assert pm.timings["n_missing_fields"] == 1 and pm.timings["n_fallbacks"] == 0


def test_a_missing_level_costs_one_call_on_the_per_field_path():
    c = lowest_level_missing("cdt_bbox_levelist")
    (out, pm, fake), _ = both_modes(c, **PER_FIELD)
    assert fake.n_data_not_found == pm.timings["n_missing_fields"]  # one failed call per missing field
    assert out == run(c, "raise")[0]


class _VanishingFake(FakeGribJump):
    """A field that disappears after its first extraction (found by one call, gone for the next)."""

    def __init__(self, axes_table, vanish: dict):
        super().__init__(axes_table)
        self.vanish = vanish

    def extract(self, requests, ctx=None):
        out = super().extract(requests, ctx)
        if any(all(str(r[0].get(k)) == v for k, v in self.vanish.items()) for r in requests):
            self.missing.append(dict(self.vanish))
        return out


_VanishingFake.__name__ = "GribJump"  # polytope's Datacube.create dispatches on the class name


def test_a_field_that_vanishes_between_calls_is_reported_missing():
    """Every field is fetched by exactly one call, so a field lost after an earlier call is just missing.

    With latitude bands a later band of a field whose band 0 had been found re-raised (the field existed
    a moment ago).  There are no later bands: a ``DataNotFound`` on a one-field call means that field has
    no message, which is the empty-result semantics of DESIGN 2.5.
    """
    c = case("efas_bbox_multiparam")
    fake = _VanishingFake(build_fake(c).cubes, vanish={"param": "240023"})
    pm, request = make_polytope_mars(c, fake, {"limits": {"memory_budget_bytes": 10**12, "max_fields_per_call": 1}})
    out = b"".join(pm.extract_stream(request))
    assert fake.n_data_not_found >= 1
    assert pm.timings["n_missing_fields"] >= 1 and pm.timings["n_fallbacks"] == 0
    assert out != expected("efas_bbox_multiparam") and b"NaN" not in out
    # the param found by the first call keeps its range; the later groups report it missing
    doc = json.loads(out)
    assert [sorted(cov["ranges"]) for cov in doc["coverages"]][0] == ["dis06", "dis24"]


# --- other errors propagate ----------------------------------------------------------------------------------


class _FailingFake(FakeGribJump):
    def __init__(self, axes_table, error: Exception):
        super().__init__(axes_table)
        self.error = error

    def extract(self, requests, ctx=None):
        self.n_extract_calls += 1
        raise self.error


_FailingFake.__name__ = "GribJump"


@pytest.mark.parametrize(
    "name, limits",
    [
        ("o1280_bbox_missing_field", {}),  # whole-group unit
        ("o1280_bbox_missing_field", PER_FIELD),  # one call per (param, level)
        ("o1280_timeseries_steps", {}),  # point feature, whole tree
    ],
)
@pytest.mark.parametrize(
    "error, raised",
    [
        (pygribjump.GribJumpException("Error in function 'gribjump_extract': Missing JumpInfo"), GribJumpNoIndexError),
        (
            pygribjump.GribJumpException("Error in function 'gribjump_extract': SeriousBug"),
            pygribjump.GribJumpException,
        ),
        (RuntimeError("DataNotFound but not from gribjump"), RuntimeError),
        (ConnectionError("fdbprod:9123 refused"), ConnectionError),
    ],
)
def test_other_exceptions_propagate(name, limits, error, raised):
    c = case(name)
    fake = _FailingFake(build_fake(c).cubes, error=error)
    with pytest.raises(raised):
        run(c, fake=fake, **limits)
    assert fake.n_extract_calls == 1


# --- point features: whole tree ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name, missing",
    [
        ("o1280_timeseries_steps", [{"param": "165"}]),  # one param missing everywhere
        ("o1280_timeseries_steps", [{"param": "165", "step": "6"}]),  # one instant of one param
        ("o1280_timeseries_steps", [{"step": "6"}]),  # one instant of every param
        ("cdt_timeseries", [{"param": "165", "time": "1200"}]),
        ("o1280_verticalprofile", [{"param": "130", "levelist": "850"}]),  # one level of one param
        ("o1280_verticalprofile", [{"param": "157"}]),
        ("o1280_position_steps", [{"step": "6"}]),
        ("efcl_timeseries_hdate", [{"hdate": "20250102"}]),
        ("o1280_trajectory", [{"param": "167"}]),  # everything missing: "Matched 0 fields", no fallback
    ],
)
def test_point_feature_fallback_equals_empty_results(name, missing):
    c = case(name, missing=missing)
    (out, pm, fake), (_, pm_empty, fake_empty) = both_modes(c)
    assert fake.n_data_not_found >= 1 and fake_empty.n_extract_calls == 1
    assert (pm.timings["n_fallbacks"] >= 1) == (name != "o1280_trajectory")
    assert pm.timings["n_missing_fields"] == pm_empty.timings["n_missing_fields"] >= 1
    assert out != expected(name)


def test_point_feature_param_missing_everywhere_costs_one_call_per_param():
    c = case("o1280_timeseries_steps", missing=[{"param": "165"}])
    (out, pm, fake), _ = both_modes(c)
    doc = json.loads(out)
    assert doc["coverages"] and all(sorted(cov["ranges"]) == ["2t"] for cov in doc["coverages"])
    # whole tree (failed) + per param: 167 found, 165 "Matched 0 fields" (not split further)
    assert fake.n_extract_calls == 1 + 2 and fake.n_data_not_found == 2
    assert pm.timings["n_fallbacks"] == 1
    assert pm.timings["n_missing_fields"] == pm.timings["n_groups"]  # 165 at every instant


def test_point_feature_partly_missing_param_is_split_per_group():
    c = case("o1280_timeseries_steps", missing=[{"param": "165", "step": "6"}])
    (out, pm, fake), _ = both_modes(c)
    groups = pm.timings["n_groups"]
    # whole tree + per param (165 fails, partly found) + per (instant, 165)
    assert fake.n_extract_calls == 1 + 2 + groups and fake.n_data_not_found == 3
    assert pm.timings["n_fallbacks"] == 2 and pm.timings["n_missing_fields"] == 1


def test_point_feature_missing_level_is_split_per_level():
    c = case("o1280_verticalprofile", missing=[{"param": "130", "levelist": "850"}])
    (out, pm, fake), _ = both_modes(c)
    doc = json.loads(out)
    assert sorted(doc["coverages"][0]["ranges"]) == ["r", "t"]
    assert doc["coverages"][0]["ranges"]["t"]["values"].count(None) == 1
    assert pm.timings["n_missing_fields"] == 1
