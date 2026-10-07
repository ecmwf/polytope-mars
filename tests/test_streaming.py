"""Streaming extraction: unit/band invariance, missing fields, format selection, limits, config aliases.

Runs the golden cases against the fake gribjump with different ``limits.memory_budget_bytes``; the bytes
must not depend on how the request was cut into extraction units and bands.
"""

import copy
import json
from pathlib import Path

import numpy as np
import pytest

from polytope_mars.api import PolytopeMars
from polytope_mars.config import PolytopeMarsConfig
from polytope_mars.encoders import get_encoder, supported_formats
from polytope_mars.extract import BlockExtractor
from polytope_mars.testing.golden import build_fake, load_case, make_polytope_mars

GOLDEN = Path(__file__).parent / "golden"


def case(name):
    return load_case(GOLDEN / "cases" / f"{name}.yaml")


def expected(name):
    c = case(name)
    folder = "expected_fixed" if c.get("fixes") else "expected"
    return (GOLDEN / folder / f"{name}.covjson").read_bytes()


def run(name, budget=None, fake=None, **limits):
    c = case(name)
    fake = build_fake(c) if fake is None else fake
    update = {"limits": {"memory_budget_bytes": budget, **limits}}
    pm, request = make_polytope_mars(c, fake, update)
    return b"".join(pm.extract_stream(request)), pm, fake


def n_spatial_nodes(doc):
    """Spatial nodes per coverage: distinct latitudes of a box/polygon (one node per latitude line)."""
    cov = doc["coverages"][0]
    return len({tuple(v[:1]) for v in cov["domain"]["axes"]["composite"]["values"]})


MULTIPOINT = [
    "efas_bbox_multiparam",
    "o1280_bbox_ensemble",
    "cdt_bbox_levelist",
    "cdt_bbox_sfc",
    "efas_polygon_fc",
    "cdt_polygon_sfc",
    "clmn_bbox",
    "efcl_bbox_hdate",
    "ode_bbox_subhourly",
]


@pytest.mark.parametrize("name", MULTIPOINT)
def test_one_unit_per_group_without_budget(name):
    out, pm, fake = run(name)
    assert out == expected(name)
    t = pm.timings
    assert fake.n_extract_calls == t["n_units"] == t["n_groups"] == t["n_coverages"] == t["n_gribjump_calls"]
    assert t["n_bands"] == t["n_groups"]


@pytest.mark.parametrize("name", MULTIPOINT)
def test_large_budget_is_one_unit_per_group(name):
    out, pm, fake = run(name, budget=10**12)
    assert out == expected(name)
    assert fake.n_extract_calls == pm.timings["n_groups"]


@pytest.mark.parametrize("name", MULTIPOINT)
def test_band_invariance(name):
    """~3 bands per group and one spatial node per band give the same bytes as one unit per group."""
    ref = expected(name)
    doc = json.loads(ref)
    n_groups = len(doc["coverages"])
    cov = doc["coverages"][0]
    n_fields = len(doc["parameters"])
    levels = {v[2] for v in cov["domain"]["axes"]["composite"]["values"]}
    n_fields *= len(levels)
    n_points = len(cov["domain"]["axes"]["composite"]["values"]) // len(levels)
    bpp = PolytopeMarsConfig().limits.bytes_per_point.for_mapper(None)  # all grids here use 64 or 160

    # one spatial node per band (a latitude line; a single point on merged lat/lon grids)
    out, pm, fake = run(name, budget=1)
    assert out == ref
    nodes = n_spatial_nodes(doc) if name != "ode_bbox_subhourly" else n_points
    assert pm.timings["n_bands"] == n_groups * nodes
    assert fake.n_extract_calls == pm.timings["n_units"] == n_fields * pm.timings["n_bands"]

    # roughly three bands per group
    budget = 3 * bpp * (n_fields + 1) * max(1, n_points // 3)
    budget = min(budget, n_points * n_fields * bpp - 1)
    out, pm, fake = run(name, budget=budget)
    assert out == ref
    assert n_groups < pm.timings["n_bands"] <= n_groups * nodes
    assert fake.n_extract_calls == n_fields * pm.timings["n_bands"]


@pytest.mark.parametrize("missing_mode", ["raise", "empty"])
@pytest.mark.parametrize("budget", [None, 1, 2000])
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
def test_missing_fields_and_points_through_both_unit_paths(name, budget, missing_mode):
    out, pm, fake = run(name, budget=budget, fake=build_fake(case(name), missing_mode=missing_mode))
    assert out == expected(name)
    assert b"NaN" not in out


def test_band0_peek_fetches_a_missing_field_once():
    # 228 at step 6 of 20240102 is missing: with one band per latitude line (4 lines), the missing field
    # costs one call (band 0) and the present one 4.
    out, pm, fake = run("o1280_bbox_missing_field", budget=1)
    assert out == expected("o1280_bbox_missing_field")
    assert pm.timings["n_groups"] == 4
    assert fake.n_extract_calls == 3 * 2 * 4 + (1 + 4)


def test_all_absent_group_emits_no_coverage():
    out, pm, fake = run("o1280_bbox_missing_last_date", budget=1)
    doc = json.loads(out)
    assert [c["domain"]["axes"]["t"]["values"] for c in doc["coverages"]] == [["2024-01-01T00:00:00Z"]]
    assert pm.timings["n_groups"] == 1


def test_bitmap_nan_points_are_null():
    doc = json.loads(run("o1280_bbox_nan_points", budget=1)[0])
    values = doc["coverages"][0]["ranges"]["2t"]["values"]
    assert values.count(None) == 4 and all(v is None or np.isfinite(v) for v in values)


# --- polygons sliced into one longitude leaf per latitude line -----------------------------------------------


@pytest.mark.parametrize("name", ["efas_polygon_fc", "cdt_polygon_sfc", "cdt_polygon_single_param"])
def test_polygons_use_merged_rows_and_stay_identical(name, monkeypatch):
    leaf_sizes = []
    original = BlockExtractor._slice_and_prepare

    def spy(self):
        api, tree = original(self)
        assert api._merge_union_rows
        leaf_sizes.extend(len(leaf.values) for leaf in tree.leaves)
        return api, tree

    monkeypatch.setattr(BlockExtractor, "_slice_and_prepare", spy)
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
    request["format"] = "tensogram"
    with pytest.raises(ValueError, match=r"'tensogram'.*covjson"):
        pm.extract_stream(request)
    with pytest.raises(ValueError, match="tensogram"):
        pm.extract(dict(request))
    assert fake.n_axes_calls == 0  # rejected before any datacube work


def test_get_encoder_registry():
    assert supported_formats() == ("covjson",)
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
    bpp = conf.limits.bytes_per_point
    assert bpp.for_mapper("healpix_nested") == 160
    assert bpp.for_mapper("octahedral") == bpp.for_mapper("regular") == 64


def test_timings_are_reset_per_request():
    c = case("o1280_bbox_ensemble")
    pm, request = make_polytope_mars(c)
    pm.extract(copy.deepcopy(request))
    first = dict(pm.timings)
    pm.extract(copy.deepcopy(request))
    assert pm.timings["n_groups"] == first["n_groups"] == 6
    assert isinstance(PolytopeMars, type)
