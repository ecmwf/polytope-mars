"""Streaming extraction: unit invariance, missing fields, format selection, limits, config aliases.

Runs the golden cases against the fake gribjump with different ``limits``; the bytes must not depend on
how the request was cut into extraction units -- one group per call, several groups per call, or one
call per (param, level) when a whole group does not fit one call.
"""

import copy
import json
from itertools import product
from pathlib import Path

import numpy as np
import pytest

from polytope_mars.api import PolytopeMars
from polytope_mars.config import PolytopeMarsConfig
from polytope_mars.encoders import get_encoder, supported_formats
from polytope_mars.extract import BlockExtractor
from polytope_mars.legacy_format import referencing_coordinates
from polytope_mars.param_db import get_params
from polytope_mars.testing.fake_gribjump import decode_value
from polytope_mars.testing.golden import build_fake, load_case, make_polytope_mars

GOLDEN = Path(__file__).parent / "golden"


def case(name):
    return load_case(GOLDEN / "cases" / f"{name}.yaml")


def expected(name):
    c = case(name)
    folder = "expected_fixed" if c.get("fixes") else "expected"
    return (GOLDEN / folder / f"{name}.covjson").read_bytes()


def parsed(data: bytes) -> dict:
    """CovJSON bytes as a dict; a document that does not parse is a failure of the encoder."""
    try:
        return json.loads(data)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"the encoder produced invalid JSON: {exc}") from exc


#: Sizing knobs that make one unit's budget exactly ``n_values x BYTES_PER_VALUE`` whatever the grid:
#: without a safety factor and with a nominal range cost, gribjump's own term (<= ~9 B/value) never
#: binds, so a test can turn "k groups per call" into a budget without counting index ranges.
BYTES_PER_VALUE = 64
SIZING = {"bytes_per_value": BYTES_PER_VALUE, "bytes_per_range": 1, "safety_factor": 1.0}

#: The two coordinate name sets of ``legacy_format.referencing_coordinates``
LATLON = ("latitude", "longitude", "levelist")
XYZ = ("x", "y", "z")


def run(name, budget=None, fake=None, **limits):
    c = case(name)
    fake = build_fake(c) if fake is None else fake
    update = {"limits": {"memory_budget_bytes": budget, **SIZING, **limits}}
    pm, request = make_polytope_mars(c, fake, update)
    return b"".join(pm.extract_stream(request)), pm, fake


def fields_per_group(name) -> int:
    """``n_params x n_levels`` of one group of ``name``: the fields of one coverage, from the output."""
    doc = parsed(expected(name))
    values = doc["coverages"][0]["domain"]["axes"]["composite"]["values"]
    return len(doc["parameters"]) * len({v[2] for v in values})


#: MultiPoint cases run through every unit layout below.  The Lambert-conformal ``ode_bbox_subhourly`` is
#: not among them: slicing its quadtree costs 7 s per run, its unit planning is the same shape as
#: ``cdt_polygon_sfc``'s (three groups on one axis), and its subhourly step formatting is a
#: ``legacy_format`` concern that two golden cases pin byte for byte.
MULTIPOINT = [
    "efas_bbox_multiparam",
    "efas_bbox_ensemble",
    "o1280_bbox_ensemble",
    "cdt_bbox_levelist",
    "cdt_bbox_sfc",
    "efas_polygon_fc",
    "cdt_polygon_sfc",
    "clmn_bbox",
    "efcl_bbox_hdate",
]


#: Group structure of the MultiPoint cases: (number of groups, extents of the group axes in plan order).
#: ``cdt_*`` requests have their date and time merged into one group axis, so their groups vary on one axis.
GROUP_GRID = {
    "efas_bbox_multiparam": (4, (2, 2)),  # 2 dates x 2 steps
    # class=ce coverages come out (reference, step, number): all members of a step, then the next step
    "efas_bbox_ensemble": (6, (3, 2)),  # 3 steps x 2 numbers, step-major
    "o1280_bbox_ensemble": (6, (3, 2)),  # 3 numbers x 2 steps
    "cdt_bbox_levelist": (1, ()),  # a single group (2 params x 2 levels)
    "cdt_bbox_sfc": (4, (2, 2)),  # 2 dates x 2 times, separate compressed axes (one spatial sub-tree)
    "efas_polygon_fc": (2, (2,)),  # 2 steps
    "cdt_polygon_sfc": (3, (3,)),  # 3 times
    "clmn_bbox": (3, (3,)),  # 3 months
    "efcl_bbox_hdate": (4, (2, 2)),  # 2 hdates x 2 steps
}


def group_values(name) -> int:
    """``n_points x n_params x n_levels`` of one group of ``name`` (its values, from the output)."""
    doc = parsed(expected(name))
    values = doc["coverages"][0]["domain"]["axes"]["composite"]["values"]
    n_levels = len({v[2] for v in values})
    return (len(values) // n_levels) * len(doc["parameters"]) * n_levels


def run_with_groups_per_unit(name, k):
    """Run ``name`` with room for exactly ``k`` groups per ``datacube.get``.

    The hard cap on values is what makes "exactly k" exact: a byte budget also has to pay for
    gribjump's own buffer, which depends on the grid's index ranges.
    """
    return run(name, budget=10**12, max_values_per_unit=k * group_values(name))


def predicted_units(extents, max_groups) -> list:
    """Unit sizes for groups laid out over ``extents``, by brute force over the group keys.

    Groups run lexicographically over the group axes; a unit is the longest run of at most
    ``max_groups`` consecutive groups whose keys are exactly the cartesian product of the values they
    use (anything else cannot be expressed by one compressed ``select``).
    """
    keys = list(product(*[range(n) for n in extents])) or [()]
    units, start = [], 0
    while start < len(keys):
        best = 1
        for k in range(2, min(max_groups, len(keys) - start) + 1):
            run = keys[start : start + k]  # noqa: E203
            size = 1
            for axis in range(len(extents)):
                size *= len({key[axis] for key in run})
            if size == k:
                best = k
        units.append(best)
        start += best
    return units


@pytest.mark.parametrize("name", MULTIPOINT)
def test_one_unit_per_group_without_budget(name):
    out, pm, fake = run(name)
    assert out == expected(name)
    t = pm.timings
    assert fake.n_extract_calls == t["n_units"] == t["n_groups"] == t["n_coverages"] == t["n_gribjump_calls"]
    # every MultiPoint case selects one spatial footprint: date and time are separate compressed
    # axes on climate-dt too, so no request branches per datetime
    assert t["n_spatial_subtrees"] == 1
    assert t["groups_per_unit_max"] == 1


@pytest.mark.parametrize("name", MULTIPOINT)
def test_large_budget_is_one_unit_for_all_groups(name):
    out, pm, fake = run(name, budget=10**12)
    assert out == expected(name)
    t = pm.timings
    assert fake.n_extract_calls == t["n_units"] == t["n_gribjump_calls"] == 1
    assert t["groups_per_unit_max"] == t["n_groups"] == t["n_coverages"] == GROUP_GRID[name][0]


@pytest.mark.parametrize("name", MULTIPOINT)
@pytest.mark.parametrize("max_groups", [1, 3, "all"])
def test_unit_invariance_over_consecutive_groups(name, max_groups):
    """One, three and all groups per ``datacube.get`` give the same bytes and the predicted call count."""
    n_groups, extents = GROUP_GRID[name]
    k = n_groups if max_groups == "all" else max_groups
    out, pm, fake = run_with_groups_per_unit(name, k)
    assert out == expected(name)
    units = predicted_units(extents, k)
    t = pm.timings
    assert fake.n_extract_calls == t["n_units"] == t["n_gribjump_calls"] == len(units)
    assert t["groups_per_unit_max"] == max(units)
    assert t["n_groups"] == n_groups


def test_unit_runs_stop_at_a_non_rectangular_group_set():
    """3 numbers x 2 steps with room for 3 groups: units of 2, because 3 of them are not a product."""
    out, pm, fake = run_with_groups_per_unit("o1280_bbox_ensemble", 3)
    assert out == expected("o1280_bbox_ensemble")
    assert fake.n_extract_calls == 3 and pm.timings["groups_per_unit_max"] == 2


def test_multi_group_unit_assigns_every_field_to_its_own_group():
    """The values of a unit are split per (group, param, level): each range holds exactly its own field.

    The fake encodes (field path, grid index) in every value, so a range built from the wrong stride of
    the compressed-axes product would carry another group's or param's field id.
    """
    out, pm, fake = run("efas_bbox_multiparam", budget=10**12)
    assert out == expected("efas_bbox_multiparam")
    assert fake.n_extract_calls == 1 and pm.timings["groups_per_unit_max"] == 4
    doc = parsed(out)
    params = get_params("ecmwf")
    shortnames = {params[pid]["shortname"]: pid for pid in case("efas_bbox_multiparam")["request"]["param"].split("/")}
    seen = set()
    for cov in doc["coverages"]:
        meta = cov["mars:metadata"]
        date = str(meta["Forecast date"])[:10].replace("-", "")
        for name, rng in cov["ranges"].items():
            ids = {decode_value(v)[0] for v in rng["values"]}
            assert len(ids) == 1, f"{name} of {meta} mixes {len(ids)} fields"
            path = fake.fields[ids.pop()]
            assert str(path["param"]) == shortnames[name]
            assert str(path["step"]) == str(meta["step"])
            assert str(path["date"]) == date
            seen.add((path["date"], path["step"], path["param"]))
    assert len(seen) == 8  # 2 dates x 2 steps x 2 params, each used by exactly one range


@pytest.mark.parametrize("name", MULTIPOINT)
def test_one_call_per_field_gives_the_same_bytes(name):
    """A group whose fields do not fit one call is fetched one (param, level) at a time: same bytes.

    ``max_fields_per_call = 1`` is the exact way to force it whatever the grid: the budget also has to
    pay for gribjump's buffer and the encoder's fragments, which dwarf a 9-point golden case.
    """
    ref = expected(name)
    n_groups = len(parsed(ref)["coverages"])
    n_fields = fields_per_group(name)

    out, pm, fake = run(name, budget=10**12, max_fields_per_call=1)
    assert out == ref
    assert pm.timings["n_groups"] == n_groups
    # one call per field of every group, whether the group went through the whole-group path (a
    # single-field group fits) or through the per-(param, level) path
    assert fake.n_extract_calls == pm.timings["n_units"] == n_groups * n_fields
    assert pm.timings["fields_per_unit_max"] == 1


@pytest.mark.parametrize("name", ["efas_bbox_multiparam", "cdt_bbox_levelist"])
def test_a_field_too_large_for_the_budget_is_refused(name):
    """A field is never split, so one that does not fit the budget is a client error, not a smaller call.

    The budget is 4 kB rather than 1 B so that the request still gets past the tree guard (half the
    budget, against a tree of at most 21 points x 40 B here): what is refused is the field.
    """
    fake = build_fake(case(name))
    with pytest.raises(ValueError, match=r"One field of this request covers \d+ grid points"):
        run(name, budget=4000, fake=fake)
    assert fake.n_extract_calls == 0, "refused before anything is fetched"


@pytest.mark.parametrize("fields_per_call", [None, 1])
@pytest.mark.parametrize("budget", [None, 10**12])
@pytest.mark.parametrize(
    "name",
    [
        "o1280_bbox_missing_field",
        "efas_bbox_missing_field",
        "o1280_bbox_missing_last_date",
        "cdt_bbox_missing_field",
        "o1280_bbox_nan_points",
        "efas_bbox_nan_points",
    ],
)
def test_missing_fields_and_points_through_both_unit_paths(name, budget, fields_per_call):
    """Missing fields and bitmap-missing points are the same bytes however the call is cut up.

    The reporting mode of a missing field (``DataNotFound`` or an empty result) is covered for these
    cases by ``tests/test_missing_fields.py``, which also pins the call counts of each mode.
    """
    limits = {} if fields_per_call is None else {"max_fields_per_call": fields_per_call}
    out, pm, fake = run(name, budget=budget, fake=build_fake(case(name)), **limits)
    assert out == expected(name)
    assert b"NaN" not in out


def test_a_missing_field_costs_one_call_on_the_per_field_path():
    # 228 at step 6 of 20240102 is missing: with one call per (param, level) every field of every group
    # costs exactly one call, and the missing one says so by raising DataNotFound.
    out, pm, fake = run("o1280_bbox_missing_field", budget=10**12, max_fields_per_call=1)
    assert out == expected("o1280_bbox_missing_field")
    assert pm.timings["n_groups"] == 4
    assert fake.n_extract_calls == 4 * 2 and fake.n_data_not_found == 1
    assert pm.timings["n_missing_fields"] == 1 and pm.timings["n_fallbacks"] == 0


def test_all_absent_group_emits_no_coverage():
    out, pm, fake = run("o1280_bbox_missing_last_date", budget=10**12, max_fields_per_call=1)
    doc = parsed(out)
    assert [c["domain"]["axes"]["t"]["values"] for c in doc["coverages"]] == [["2024-01-01T00:00:00Z"]]
    assert pm.timings["n_groups"] == 1


def test_bitmap_nan_points_are_null():
    doc = parsed(run("o1280_bbox_nan_points", budget=10**12, max_fields_per_call=1)[0])
    values = doc["coverages"][0]["ranges"]["2t"]["values"]
    assert values.count(None) == 4 and all(v is None or np.isfinite(v) for v in values)


# --- polygons sliced into one longitude leaf per latitude line -----------------------------------------------


@pytest.mark.parametrize("name", ["efas_polygon_fc", "cdt_polygon_sfc", "cdt_polygon_single_param"])
def test_polygons_use_merged_rows_and_stay_identical(name, monkeypatch):
    leaf_sizes = []
    original = BlockExtractor._slice

    def spy(self):
        api, tree = original(self)
        assert api._merge_union_rows
        leaf_sizes.extend(len(leaf.values) for leaf in tree.leaves)
        return api, tree

    monkeypatch.setattr(BlockExtractor, "_slice", spy)
    out, _, _ = run(name)
    assert out == expected(name)
    assert max(leaf_sizes) > 1, "polygon rows were not merged into multi-point leaves"


# --- format, early bytes, limits ---------------------------------------------------------------------------


def test_format_default_explicit_and_unknown():
    c = case("o1280_bbox_ensemble")
    pm, request = make_polytope_mars(c)
    assert b"".join(pm.extract_stream(request)) == expected("o1280_bbox_ensemble")
    assert pm.content_type == "application/prs.coverage+json" and pm.file_extension == "covjson"

    pm, request = make_polytope_mars(c)
    request["format"] = "covjson"
    assert b"".join(pm.extract_stream(request)) == expected("o1280_bbox_ensemble")

    fake = build_fake(c)
    pm, request = make_polytope_mars(c, fake)
    request["format"] = "netcdf"
    with pytest.raises(ValueError, match=r"'netcdf'.*covjson, tensogram"):
        pm.extract_stream(request)
    with pytest.raises(ValueError, match="netcdf"):
        pm.extract(dict(request))
    assert fake.n_axes_calls == 0  # rejected before any datacube work


def test_get_encoder_registry():
    assert list(supported_formats()) == ["covjson", "tensogram"]
    enc = get_encoder("covjson", PolytopeMarsConfig())
    assert enc.content_type == "application/prs.coverage+json"
    with pytest.raises(ValueError, match="Unsupported output format 'netcdf'"):
        get_encoder("netcdf", None)


def test_header_bytes_come_before_datacube_work():
    c = case("efas_bbox_fc_steps")
    fake = build_fake(c)
    pm, request = make_polytope_mars(c, fake)
    stream = pm.extract_stream(request)
    first = next(stream)
    assert first.startswith(b'{"type": "CoverageCollection", "domainType": "MultiPoint", "coverages": [')
    assert fake.n_axes_calls == 0 and fake.n_extract_calls == 0
    assert first + b"".join(stream) == expected("efas_bbox_fc_steps")
    assert pm.timings["first_byte_ms"] >= 0


def test_extract_equals_json_dumps_of_stream():
    c = case("cdt_bbox_levelist")
    pm, request = make_polytope_mars(c)
    streamed = b"".join(pm.extract_stream(copy.deepcopy(request)))
    pm, request = make_polytope_mars(c)
    assert json.dumps(pm.extract(request)).encode() == streamed


@pytest.mark.parametrize(
    "domain,feature,role,coords",
    [
        ("MultiPoint", "boundingbox", "date", LATLON),
        ("MultiPoint", "circle", "month", LATLON),
        ("MultiPoint", "polygon", "hdate", LATLON),
        ("MultiPoint", "polygon", "date", XYZ),
        ("MultiPoint", "polygon", "step", XYZ),
        ("MultiPoint", "shapefile", "date", XYZ),
        ("MultiPoint", "boundingbox", "month", XYZ),
        ("PointSeries", "timeseries", "date", LATLON),
        ("PointSeries", "timeseries", "step", XYZ),
        ("PointSeries", "position", "month", XYZ),
        ("VerticalProfile", "verticalprofile", "date", LATLON),
        ("Trajectory", "trajectory", "hdate", LATLON),
        ("Trajectory", "trajectory", "date", ("t", "x", "y", "z")),
    ],
)
def test_the_referencing_coordinates_of_each_legacy_encoder(domain, feature, role, coords):
    """Preserved quirk 8: the names a collection declares follow the legacy encoder that served it."""
    assert referencing_coordinates(domain, feature, role) == coords


def test_the_header_carries_the_referencing_coordinates():
    """covjsonkit writes what the header says, so the rule lives here and not in the encoder."""
    doc = parsed(run("cdt_polygon_sfc")[0])  # a polygon on the step time axis: x/y/z
    assert doc["referencing"][0]["coordinates"] == list(XYZ)
    assert doc["coverages"][0]["domain"]["axes"]["composite"]["coordinates"] == list(XYZ)
    doc = parsed(run("efas_bbox_multiparam")[0])  # a class=ce box: latitude/longitude/levelist
    assert doc["referencing"][0]["coordinates"] == list(LATLON)


def test_max_points_per_field_is_enforced_before_slicing():
    c = case("efas_bbox_multiparam")  # 9 points per field
    fake = build_fake(c)
    pm, request = make_polytope_mars(c, fake, {"limits": {"max_points_per_field": 2}})
    with pytest.raises(ValueError, match="grid points per field"):
        pm.extract(request)
    assert fake.n_axes_calls == 0
    out, _, _ = run("efas_bbox_multiparam", max_points_per_field=1000)
    assert out == expected("efas_bbox_multiparam")


def test_max_polygon_points():
    c = case("efas_polygon_fc")
    pm, request = make_polytope_mars(c, config_update={"limits": {"max_polygon_points": 3}})
    with pytest.raises(ValueError, match="exceeds the maximum of 3"):
        pm.extract(request)


def test_deprecated_config_keys_map_onto_new_sections():
    conf = PolytopeMarsConfig.model_validate(
        {"coverageconfig": {"param_db": "dwd"}, "polygonrules": {"max_points": 10, "max_area": 1.0}}
    )
    assert conf.encoders.covjson.param_db == "dwd"
    assert conf.limits.max_polygon_points == 10
    assert conf.limits.memory_budget_bytes is None and conf.limits.max_points_per_field is None
    conf = PolytopeMarsConfig.model_validate(
        {"coverageconfig": {"param_db": "dwd"}, "encoders": {"covjson": {"param_db": "ecmwf"}}}
    )
    assert conf.encoders.covjson.param_db == "ecmwf"  # explicit new section wins
    conf = PolytopeMarsConfig.model_validate({})
    assert conf.limits.max_polygon_points == 3600
    assert conf.limits.bytes_per_value == 32 and conf.limits.bytes_per_range == 96
    assert conf.limits.max_fields_per_call == 1024
    assert conf.limits.safety_factor == 1.5 and conf.limits.max_values_per_unit == 256_000_000


def test_timings_are_reset_per_request():
    c = case("o1280_bbox_ensemble")
    pm, request = make_polytope_mars(c)
    pm.extract(copy.deepcopy(request))
    first = dict(pm.timings)
    pm.extract(copy.deepcopy(request))
    assert pm.timings["n_groups"] == first["n_groups"] == 6
    assert isinstance(PolytopeMars, type)
