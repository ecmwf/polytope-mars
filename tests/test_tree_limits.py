"""The tree-size guard: what a request's own tree costs, estimated before slicing and measured after.

A *branching* axis gets one node, one spatial sub-tree and one slice per value (polytope-feature never
compresses a merged axis, and compresses nothing that is missing from ``compressed_axes_config``), so a
request's tree grows with the product of those axes' value counts -- 720 sub-trees for "Europe hourly for
a month" on a merged date/time axis, an 8 GB tree before the first gribjump call.  These tests pin the
branch count the estimate derives from a request, the refusal it raises, and the exact figure the
prepared tree reports (``timings["tree_bytes"]``).
"""

import copy
import math
import re
from pathlib import Path

import pytest

from polytope_mars.config import PolytopeMarsConfig
from polytope_mars.limits import (
    branching_value_counts,
    estimate_tree_branches,
    estimate_tree_bytes,
    request_value_count,
    tree_byte_limit,
)
from polytope_mars.testing.configs import fake_gribjump_config_dict
from polytope_mars.testing.golden import build_fake, load_case, make_polytope_mars

GOLDEN = Path(__file__).parent / "golden"

#: LUMI's climate-dt block: date and time are merged into one axis, and both are in
#: ``compressed_axes_config`` (which a merged axis ignores).
CDT_OPTIONS = fake_gribjump_config_dict("healpix_1024")["options"]
#: Bologna's EFAS block: date, time and hdate are separate axes, all three compressed.
EFAS_OPTIONS = fake_gribjump_config_dict("efas_local_regular")["options"]

#: "Europe hourly for a month": 30 dates x 24 times.
HOURLY_MONTH = {
    "dataset": "climate-dt",
    "class": "d1",
    "date": "20200101/to/20200130",
    "time": "0000/to/2300",
    "param": "167",
    "levtype": "sfc",
}


def case(name):
    return load_case(GOLDEN / "cases" / f"{name}.yaml")


# --- how many values a request key holds -------------------------------------------------------


@pytest.mark.parametrize(
    "key,value,count",
    [
        ("date", "20200101", 1),
        ("date", "20200101/20200102", 2),
        ("date", "20200101/to/20200130", 30),
        ("date", "20200101/to/20200131/by/10", 4),
        ("time", "0000/to/2300", 24),
        ("time", "0000/1200", 2),
        ("step", "0/to/24/by/6", 5),
        ("step", "0/to/1h/by/30m", 3),
        ("number", "1/to/50", 50),
        ("param", "167/165/228", 3),
        ("levtype", "sfc", 1),
        # Gaps that are documented, not errors: an unbounded or unparseable value counts as one.
        ("time", "ALL", 1),
        ("date", "nonsense/to/worse", 1),
    ],
)
def test_request_value_count_expands_lists_and_ranges(key, value, count):
    assert request_value_count(key, value) == count


# --- which axes branch --------------------------------------------------------------------------


def test_a_merged_date_time_axis_branches_once_per_datetime():
    # 30 dates x 24 times on one merged axis: 720 branches, each with its own spatial sub-tree.
    assert branching_value_counts(HOURLY_MONTH, CDT_OPTIONS) == {"date": 30, "time": 24}
    assert estimate_tree_branches(HOURLY_MONTH, CDT_OPTIONS) == 720


def test_separate_compressed_date_and_time_axes_do_not_branch():
    options = copy.deepcopy(CDT_OPTIONS)
    for axis in options["axis_config"]:
        if axis["axis_name"] == "date":
            axis["transformations"] = [{"name": "type_change", "type": "date"}]
    options["axis_config"].append({"axis_name": "time", "transformations": [{"name": "type_change", "type": "time"}]})
    assert branching_value_counts(HOURLY_MONTH, options) == {}
    assert estimate_tree_branches(HOURLY_MONTH, options) == 1


def test_an_axis_missing_from_compressed_axes_config_branches():
    options = copy.deepcopy(EFAS_OPTIONS)
    request = {"class": "ce", "date": "20240101/20240102", "time": "0000", "step": "6/12/18", "number": "1/to/10"}
    # every axis of the request is compressed: one sub-tree
    assert estimate_tree_branches(request, options) == 1
    options["compressed_axes_config"] = [a for a in options["compressed_axes_config"] if a != "number"]
    assert branching_value_counts(request, options) == {"number": 10}
    assert estimate_tree_branches(request, options) == 10


def test_the_feature_and_format_keys_are_not_axes():
    request = {**HOURLY_MONTH, "feature": {"type": "boundingbox", "points": [[1, 2], [3, 4]]}, "format": "covjson"}
    assert estimate_tree_branches(request, CDT_OPTIONS) == 720


# --- the byte estimate and the limit ------------------------------------------------------------


class _Box:
    """The parsed-feature interface the estimate uses (:func:`limits.estimate_points_per_field`)."""

    def __init__(self, area_bb, points):
        self.area_bb = area_bb
        self.points = points

    def name(self):
        return "Bounding Box"


def test_estimated_tree_bytes_is_branches_times_points_times_the_constant():
    # a 10x10 degree box over the equator on HEALPix 1024
    box = _Box(area_bb=1.2e6, points=[[5.0, 0.0], [-5.0, 10.0]])
    one = estimate_tree_bytes({"date": "20200101", "time": "0000"}, box, CDT_OPTIONS, 40)
    many = estimate_tree_bytes(HOURLY_MONTH, box, CDT_OPTIONS, 40)
    assert one is not None and many is not None
    assert many == pytest.approx(720 * one)
    assert many / 1e6 > 800  # most of a GB of tree for a request that has fetched nothing yet


def test_a_pole_to_pole_box_has_no_estimate_and_is_not_refused_by_one():
    # get_boundingbox_area returns NaN for [[90, -180], [-90, 180]]: unknown, so neither limit binds
    # (the exact post-prepare check is what covers a whole-world request).
    box = _Box(area_bb=math.nan, points=[[90, -180], [-90, 180]])
    assert estimate_tree_bytes(HOURLY_MONTH, box, CDT_OPTIONS, 40) is None


def test_estimated_tree_bytes_is_unknown_when_the_points_per_field_are():
    class Trajectory:
        def name(self):
            return "Trajectory"

    assert estimate_tree_bytes(HOURLY_MONTH, Trajectory(), CDT_OPTIONS, 40) is None


@pytest.mark.parametrize(
    "limits,expected",
    [
        ({}, None),
        ({"memory_budget_bytes": 1_600_000_000}, 800_000_000),
        ({"max_tree_bytes": 1000}, 1000),
        ({"max_tree_bytes": 1000, "memory_budget_bytes": 1_600_000_000}, 1000),
    ],
)
def test_the_tree_limit_defaults_to_half_the_memory_budget(limits, expected):
    conf = PolytopeMarsConfig.model_validate({"limits": limits})
    assert tree_byte_limit(conf.limits) == expected


def test_a_non_positive_tree_limit_is_rejected():
    with pytest.raises(ValueError, match="max_tree_bytes must be positive"):
        PolytopeMarsConfig.model_validate({"limits": {"max_tree_bytes": 0}})
    with pytest.raises(ValueError, match="bytes_per_point_tree must be positive"):
        PolytopeMarsConfig.model_validate({"limits": {"bytes_per_point_tree": -1}})


# --- the refusals on a real request -------------------------------------------------------------


def test_a_tree_over_the_limit_is_refused_before_slicing():
    c = case("cdt_bbox_sfc")  # 2 dates x 2 times on separate compressed axes: one sub-tree of 21 points
    fake = build_fake(c)
    pm, request = make_polytope_mars(c, fake, {"limits": {"max_tree_bytes": 500}})
    with pytest.raises(ValueError, match="The request tree alone would need about"):
        pm.extract(request)
    # Nothing was sliced: the fake was never even asked for its axes.
    assert fake.n_axes_calls == 0


def _steps_uncompressed(c):
    """``efas_bbox_fc_steps`` with ``step`` taken out of ``compressed_axes_config``: its three steps branch."""
    options = fake_gribjump_config_dict(c["grid"], copy.deepcopy(c["request"]))["options"]
    options["compressed_axes_config"] = [a for a in options["compressed_axes_config"] if a != "step"]
    return options


def test_the_refusal_names_the_branches_the_points_and_what_to_do():
    c = case("efas_bbox_fc_steps")
    options = _steps_uncompressed(c)
    pm, request = make_polytope_mars(c, build_fake(c), {"options": options, "limits": {"max_tree_bytes": 100}})
    with pytest.raises(ValueError) as excinfo:
        pm.extract(request)
    message = str(excinfo.value)
    assert "3 separate branches (dates, times or other uncompressed axis values)" in message
    assert re.search(r"about \d+ grid points each", message)
    assert "more than the limit of 100 bytes" in message
    assert "request fewer dates and times per request" in message


def test_a_single_branch_refusal_asks_for_a_smaller_area_instead():
    # One date, one time: nothing to drop but the area, so the message says so.
    c = case("cdt_bbox_levelist")
    pm, request = make_polytope_mars(c, build_fake(c), {"limits": {"max_tree_bytes": 100}})
    with pytest.raises(ValueError, match=r"about 9 grid points\), more than the limit of 100 bytes; "):
        pm.extract(request)
    pm, request = make_polytope_mars(c, build_fake(c), {"limits": {"max_tree_bytes": 100}})
    with pytest.raises(ValueError, match="request a smaller area"):
        pm.extract(request)


def test_a_request_just_under_the_limit_is_extracted():
    # cdt_bbox_sfc: one sub-tree of 21 points.  The estimate is 1 x 21.0 x 40 B; one byte either side
    # of it decides the request, and the prepared tree is 21 x (16 + 8) = 504 B.
    c = case("cdt_bbox_sfc")
    pm, request = make_polytope_mars(c, build_fake(c))
    options = fake_gribjump_config_dict(c["grid"], copy.deepcopy(c["request"]))["options"]
    feature = pm._feature_factory(request["feature"]["type"], copy.deepcopy(request["feature"]), pm.conf)
    estimate = estimate_tree_bytes(request, feature, options, 40)
    below, above = math.floor(estimate), math.floor(estimate) + 1
    pm, request = make_polytope_mars(c, build_fake(c), {"limits": {"max_tree_bytes": below}})
    with pytest.raises(ValueError, match="The request tree alone"):
        pm.extract(copy.deepcopy(request))
    pm, request = make_polytope_mars(c, build_fake(c), {"limits": {"max_tree_bytes": above}})
    coverage = pm.extract(request)
    assert len(coverage["coverages"]) == 4
    assert pm.timings["tree_bytes"] == 21 * 24


def test_three_uncompressed_steps_build_three_sub_trees():
    c = case("efas_bbox_fc_steps")
    pm, request = make_polytope_mars(c, build_fake(c), {"options": _steps_uncompressed(c)})
    pm.extract(request)
    assert pm.timings["n_spatial_subtrees"] == 3
    assert pm.timings["tree_bytes"] == 3 * pm.timings["tree_bytes"] // 3


def test_the_prepared_tree_bytes_are_reported_for_a_golden_case():
    c = case("efas_bbox_multiparam")  # one branch, 9 points per field
    pm, request = make_polytope_mars(c)
    pm.extract(request)
    assert pm.timings["tree_bytes"] == 9 * 24


def test_a_prepared_tree_over_the_limit_is_refused_before_any_gribjump_call():
    # A trajectory has no area, so the pre-slice estimate opts out (estimate_points_per_field is None)
    # and the post-prepare check is the only guard: it still refuses before any value is fetched.
    c = case("o1280_trajectory")
    fake = build_fake(c)
    pm, request = make_polytope_mars(c, fake, {"limits": {"max_tree_bytes": 119}})
    with pytest.raises(ValueError, match="The request tree holds 5 grid points in 1 separate branches"):
        pm.extract(request)
    assert fake.n_extract_calls == 0
    assert pm.timings["tree_bytes"] == 120
    # one byte more and the same request is served
    pm, request = make_polytope_mars(c, build_fake(c), {"limits": {"max_tree_bytes": 120}})
    assert pm.extract(request)["type"] == "CoverageCollection"
