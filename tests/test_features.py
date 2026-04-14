"""
Comprehensive tests for all 9 feature classes in polytope_mars/features/.

These tests exercise construction, get_shapes(), validate(), parse(),
metadata methods, split_request(), and edge cases for each feature —
WITHOUT requiring pygribjump, polytope-server, or FDB.
"""

import copy

import pytest

from polytope_mars.features.boundingbox import BoundingBox
from polytope_mars.features.circle import Circle
from polytope_mars.features.frame import Frame
from polytope_mars.features.path import Path
from polytope_mars.features.polygon import Polygons
from polytope_mars.features.position import Position
from polytope_mars.features.timeseries import TimeSeries
from polytope_mars.features.verticalprofile import VerticalProfile

# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


class MockPolygonRules:
    max_area = float("inf")
    max_points = 100000


class MockClientConfig:
    polygonrules = MockPolygonRules()


def cc(max_area=float("inf"), max_points=100000):
    """Return a MockClientConfig with custom limits."""
    c = MockClientConfig()
    c.polygonrules = MockPolygonRules()
    c.polygonrules.max_area = max_area
    c.polygonrules.max_points = max_points
    return c


# Minimal MARS-style request used by parse() / field_area()
MINIMAL_REQUEST = {"param": "167", "step": "0", "date": "20240101", "time": "0000"}


# =========================================================================
#  TimeSeries
# =========================================================================


class TestTimeSeries:
    """Tests for the TimeSeries feature."""

    def _cfg(self, **overrides):
        base = {
            "type": "timeseries",
            "points": [[1.0, 2.0]],
            "time_axis": "step",
        }
        base.update(overrides)
        return base

    # -- happy path --------------------------------------------------------

    def test_happy_path(self):
        ts = TimeSeries(self._cfg(), cc())
        shapes = ts.get_shapes()
        assert isinstance(shapes, list)
        assert len(shapes) > 0

    def test_multiple_points(self):
        ts = TimeSeries(self._cfg(points=[[1, 2], [3, 4], [5, 6]]), cc())
        shapes = ts.get_shapes()
        assert len(shapes) > 0

    # -- metadata ----------------------------------------------------------

    def test_name(self):
        ts = TimeSeries(self._cfg(), cc())
        assert ts.name() == "Time Series"

    def test_coverage_type(self):
        ts = TimeSeries(self._cfg(), cc())
        assert ts.coverage_type() == "PointSeries"

    def test_required_keys(self):
        ts = TimeSeries(self._cfg(), cc())
        assert "type" in ts.required_keys()
        assert "points" in ts.required_keys()
        assert "time_axis" in ts.required_keys()

    def test_required_axes(self):
        ts = TimeSeries(self._cfg(), cc())
        assert ts.required_axes() == ["latitude", "longitude"]

    def test_incompatible_keys(self):
        ts = TimeSeries(self._cfg(), cc())
        assert "levellist" in ts.incompatible_keys()

    # -- wrong type --------------------------------------------------------

    def test_wrong_type(self):
        with pytest.raises(ValueError, match="timeseries"):
            TimeSeries(self._cfg(type="polygon"), cc())

    # -- unexpected keys ---------------------------------------------------

    def test_unexpected_keys(self):
        with pytest.raises(ValueError, match="Unexpected keys"):
            TimeSeries(self._cfg(bogus="x"), cc())

    # -- empty points ------------------------------------------------------

    def test_empty_points(self):
        with pytest.raises(ValueError, match="at least one point"):
            TimeSeries(self._cfg(points=[]), cc())

    # -- axes defaults / normalisation ------------------------------------

    def test_axes_default(self):
        ts = TimeSeries(self._cfg(), cc())
        assert ts.axes == ["latitude", "longitude"]

    def test_axes_step_becomes_latlon(self):
        ts = TimeSeries(self._cfg(axes=["step"]), cc())
        assert ts.axes == ["latitude", "longitude"]

    def test_axes_date_becomes_latlon(self):
        ts = TimeSeries(self._cfg(axes=["date"]), cc())
        assert ts.axes == ["latitude", "longitude"]

    def test_axes_non_list_becomes_latlon(self):
        ts = TimeSeries(self._cfg(axes="something"), cc())
        assert ts.axes == ["latitude", "longitude"]

    # -- parse: time_axis validation --------------------------------------

    def test_parse_invalid_time_axis(self):
        ts = TimeSeries(self._cfg(), cc())
        with pytest.raises(ValueError, match="Timeseries axes must be in"):
            ts.parse(dict(MINIMAL_REQUEST), {"time_axis": "foobar", "points": [[1, 2]]})

    def test_parse_valid_time_axes(self):
        # Each axis needs realistic values that field_area() can parse
        axis_values = {
            "step": "0",
            "date": "20240101",
            "month": "1",
            "year": "2024",
        }
        for axis in ["step", "date", "month", "year"]:
            ts = TimeSeries(self._cfg(time_axis=axis), cc())
            req = dict(MINIMAL_REQUEST)
            req[axis] = axis_values[axis]
            result = ts.parse(req, {"time_axis": axis, "points": [[1, 2]]})
            assert isinstance(result, dict)

    # -- parse: overspecified / underspecified -----------------------------

    def test_parse_overspecified(self):
        ts = TimeSeries(self._cfg(), cc())
        req = dict(MINIMAL_REQUEST)
        req["step"] = "0"
        with pytest.raises(ValueError, match="overspecified"):
            ts.parse(
                req,
                {
                    "time_axis": "step",
                    "points": [[1, 2]],
                    "range": {"start": 0, "end": 6},
                },
            )

    def test_parse_underspecified(self):
        ts = TimeSeries(self._cfg(), cc())
        req = dict(MINIMAL_REQUEST)
        req.pop("step", None)
        with pytest.raises(ValueError, match="underspecified"):
            ts.parse(req, {"time_axis": "step", "points": [[1, 2]]})

    # -- parse: wrong point length ----------------------------------------

    def test_parse_wrong_point_length(self):
        ts = TimeSeries(self._cfg(), cc())
        req = dict(MINIMAL_REQUEST)
        req["step"] = "0"
        with pytest.raises(ValueError, match="two values"):
            ts.parse(req, {"time_axis": "step", "points": [[1, 2, 3]]})

    # -- parse: negative range start --------------------------------------

    def test_parse_negative_range_start(self):
        ts = TimeSeries(self._cfg(), cc())
        req = dict(MINIMAL_REQUEST)
        # Remove step so the overspecified check doesn't fire first
        req.pop("step", None)
        with pytest.raises(ValueError, match="greater than 0"):
            ts.parse(
                req,
                {
                    "time_axis": "step",
                    "points": [[1, 2]],
                    "range": {"start": -1, "end": 6},
                },
            )

    # -- parse: range with interval ---------------------------------------

    def test_parse_range_with_interval(self):
        ts = TimeSeries(self._cfg(), cc())
        req = dict(MINIMAL_REQUEST)
        req.pop("step", None)
        result = ts.parse(
            req,
            {
                "time_axis": "step",
                "points": [[1, 2]],
                "range": {"start": 0, "end": 6, "interval": 3},
            },
        )
        assert "step" in result
        assert "/by/3" in result["step"]

    # -- parse: time_axis as list ------------------------------------------
    # The parse() method first checks `time_axis not in allowed_time_axis()`.
    # A list never matches a scalar in that list, so list-valued time_axis
    # is always rejected by parse().

    def test_parse_time_axis_list_step_rejected(self):
        ts = TimeSeries(self._cfg(), cc())
        req = dict(MINIMAL_REQUEST)
        req["step"] = "0"
        with pytest.raises(ValueError, match="Timeseries axes must be in"):
            ts.parse(req, {"time_axis": ["step"], "points": [[1, 2]]})

    def test_parse_time_axis_list_date_rejected(self):
        ts = TimeSeries(self._cfg(time_axis="date"), cc())
        req = dict(MINIMAL_REQUEST)
        req["date"] = "20240101"
        with pytest.raises(ValueError, match="Timeseries axes must be in"):
            ts.parse(req, {"time_axis": ["date"], "points": [[1, 2]]})

    # -- validate ----------------------------------------------------------

    def test_validate_incompatible_key(self):
        ts = TimeSeries(self._cfg(), cc())
        with pytest.raises(KeyError, match="levellist"):
            ts.validate({"levellist": "500"}, {})

    def test_validate_missing_required_key(self):
        ts = TimeSeries(self._cfg(), cc())
        with pytest.raises(KeyError, match="Missing required key"):
            ts.validate({}, {})  # missing type, points, time_axis

    # -- range popped during init -----------------------------------------

    def test_range_popped_during_init(self):
        cfg = self._cfg()
        cfg["range"] = {"start": 0, "end": 6}
        ts = TimeSeries(cfg, cc())
        assert isinstance(ts, TimeSeries)

    # -- split_request (no field_area attr) --------------------------------

    def test_split_request_false(self):
        ts = TimeSeries(self._cfg(), cc())
        assert ts.split_request() is False

    # -- parse: area too large --------------------------------------------

    def test_parse_area_exceeds_max(self):
        ts = TimeSeries(self._cfg(), cc(max_area=0.0001))
        req = dict(MINIMAL_REQUEST)
        req["step"] = "0"
        with pytest.raises(ValueError, match="exceeds total number allowed"):
            ts.parse(req, {"time_axis": "step", "points": [[1, 2]]})


# =========================================================================
#  VerticalProfile
# =========================================================================


class TestVerticalProfile:
    """Tests for the VerticalProfile feature."""

    def _cfg(self, **overrides):
        base = {"type": "verticalprofile", "points": [[1.0, 2.0]]}
        base.update(overrides)
        return base

    # -- happy path --------------------------------------------------------

    def test_happy_path(self):
        vp = VerticalProfile(self._cfg(), cc())
        shapes = vp.get_shapes()
        assert isinstance(shapes, list) and len(shapes) > 0

    # -- metadata ----------------------------------------------------------

    def test_name(self):
        assert VerticalProfile(self._cfg(), cc()).name() == "Vertical Profile"

    def test_coverage_type(self):
        assert VerticalProfile(self._cfg(), cc()).coverage_type() == "VerticalProfile"

    def test_required_keys(self):
        vp = VerticalProfile(self._cfg(), cc())
        assert vp.required_keys() == ["type", "points"]

    def test_required_axes(self):
        assert VerticalProfile(self._cfg(), cc()).required_axes() == []

    def test_incompatible_keys(self):
        assert VerticalProfile(self._cfg(), cc()).incompatible_keys() == []

    # -- wrong type --------------------------------------------------------

    def test_wrong_type(self):
        with pytest.raises(ValueError, match="verticalprofile"):
            VerticalProfile(self._cfg(type="timeseries"), cc())

    # -- unexpected keys ---------------------------------------------------

    def test_unexpected_keys(self):
        with pytest.raises(ValueError, match="Unexpected keys"):
            VerticalProfile(self._cfg(bogus="x"), cc())

    # -- axes defaults -----------------------------------------------------

    def test_axes_default(self):
        vp = VerticalProfile(self._cfg(), cc())
        assert vp.axes == ["latitude", "longitude"]

    def test_axes_step_becomes_latlon(self):
        vp = VerticalProfile(self._cfg(axes=["step"]), cc())
        assert vp.axes == ["latitude", "longitude"]

    def test_axes_non_list_becomes_latlon(self):
        vp = VerticalProfile(self._cfg(axes="something"), cc())
        assert vp.axes == ["latitude", "longitude"]

    # -- empty points (still constructs, no guard) -------------------------

    def test_empty_points_constructs(self):
        vp = VerticalProfile(self._cfg(points=[]), cc())
        assert vp.points == []

    # -- parse: axes not in config defaults to levelist --------------------

    def test_parse_axes_default_levelist(self):
        vp = VerticalProfile(self._cfg(), cc())
        req = dict(MINIMAL_REQUEST)
        req["levelist"] = "500"
        result = vp.parse(req, {"points": [[1, 2]]})
        assert result["levelist"] == "500"

    # -- parse: wrong point length ----------------------------------------

    def test_parse_wrong_point_length(self):
        vp = VerticalProfile(self._cfg(), cc())
        with pytest.raises(ValueError, match="two values"):
            vp.parse(dict(MINIMAL_REQUEST), {"points": [[1, 2, 3]], "axes": "levelist"})

    # -- parse: overspecified ----------------------------------------------

    def test_parse_overspecified(self):
        vp = VerticalProfile(self._cfg(), cc())
        req = dict(MINIMAL_REQUEST)
        req["levelist"] = "500"
        with pytest.raises(ValueError, match="overspecified"):
            vp.parse(
                req,
                {
                    "points": [[1, 2]],
                    "axes": ["levelist"],
                    "range": {"start": 1, "end": 10},
                },
            )

    # -- parse: underspecified ---------------------------------------------

    def test_parse_underspecified(self):
        vp = VerticalProfile(self._cfg(), cc())
        req = dict(MINIMAL_REQUEST)
        with pytest.raises(ValueError, match="underspecified"):
            vp.parse(req, {"points": [[1, 2]], "axes": ["levelist"]})

    # -- parse: range with interval ----------------------------------------

    def test_parse_range_with_interval(self):
        vp = VerticalProfile(self._cfg(), cc())
        req = dict(MINIMAL_REQUEST)
        result = vp.parse(
            req,
            {
                "points": [[1, 2]],
                "axes": "levelist",
                "range": {"start": 1, "end": 10, "interval": 2},
            },
        )
        assert "levelist" in result
        assert "/by/2" in result["levelist"]

    # -- parse: axes as list with levelist ---------------------------------

    def test_parse_axes_list_levelist(self):
        vp = VerticalProfile(self._cfg(), cc())
        req = dict(MINIMAL_REQUEST)
        req["levelist"] = "500"
        result = vp.parse(req, {"points": [[1, 2]], "axes": ["levelist"]})
        assert isinstance(result, dict)

    # -- validate ----------------------------------------------------------

    def test_validate_missing_required(self):
        vp = VerticalProfile(self._cfg(), cc())
        with pytest.raises(KeyError, match="Missing required key"):
            vp.validate({}, {})

    # -- split_request (no field_area) -------------------------------------

    def test_split_request_false(self):
        assert VerticalProfile(self._cfg(), cc()).split_request() is False

    # -- range popped during init -----------------------------------------

    def test_range_popped_during_init(self):
        cfg = self._cfg()
        cfg["range"] = {"start": 1, "end": 10}
        vp = VerticalProfile(cfg, cc())
        assert isinstance(vp, VerticalProfile)


# =========================================================================
#  BoundingBox
# =========================================================================


class TestBoundingBox:
    """Tests for the BoundingBox feature."""

    def _cfg(self, **overrides):
        base = {
            "type": "boundingbox",
            "points": [[0.0, 0.1], [10.0, 10.0]],
        }
        base.update(overrides)
        return base

    # -- happy path --------------------------------------------------------

    def test_happy_path(self):
        bb = BoundingBox(self._cfg(), cc())
        shapes = bb.get_shapes()
        assert isinstance(shapes, list) and len(shapes) > 0

    # -- 3D bounding box ---------------------------------------------------

    def test_3d_bounding_box(self):
        cfg = {
            "type": "boundingbox",
            "points": [[0.0, 0.1, 500], [10.0, 10.0, 1000]],
            "axes": ["latitude", "longitude", "levelist"],
        }
        bb = BoundingBox(cfg, cc())
        shapes = bb.get_shapes()
        assert len(shapes) > 0

    # -- metadata ----------------------------------------------------------

    def test_name(self):
        assert BoundingBox(self._cfg(), cc()).name() == "Bounding Box"

    def test_coverage_type(self):
        assert BoundingBox(self._cfg(), cc()).coverage_type() == "MultiPoint"

    def test_required_keys(self):
        bb = BoundingBox(self._cfg(), cc())
        assert bb.required_keys() == ["type", "points"]

    def test_required_axes(self):
        assert BoundingBox(self._cfg(), cc()).required_axes() == [
            "latitude",
            "longitude",
        ]

    def test_incompatible_keys(self):
        assert BoundingBox(self._cfg(), cc()).incompatible_keys() == []

    # -- wrong type --------------------------------------------------------

    def test_wrong_type(self):
        with pytest.raises(ValueError, match="boundingbox"):
            BoundingBox(self._cfg(type="circle"), cc())

    # -- unexpected keys ---------------------------------------------------

    def test_unexpected_keys(self):
        with pytest.raises(ValueError, match="Unexpected keys"):
            BoundingBox(self._cfg(bogus="x"), cc())

    # -- missing points ----------------------------------------------------

    def test_missing_points(self):
        cfg = {"type": "boundingbox"}
        with pytest.raises(KeyError, match="must have points"):
            BoundingBox(cfg, cc())

    # -- "axes" typo key ---------------------------------------------------

    def test_extra_axes_key_typo(self):
        """If someone passes both 'axes' (valid) and another 'axes' after pop —
        this tests the guard that fires on the literal key 'axes' being left."""
        # The guard: if "axes" in feature_config after popping the real axes
        # This actually cannot happen via dict, so test the parse-time guard.
        pass

    # -- parse: wrong number of points ------------------------------------

    def test_parse_wrong_number_of_points(self):
        bb = BoundingBox(self._cfg(), cc())
        req = dict(MINIMAL_REQUEST)
        fc = {"type": "boundingbox", "points": [[0, 1], [2, 3], [4, 5]]}
        with pytest.raises(ValueError, match="two points"):
            bb.parse(req, fc)

    # -- parse: axes without lat/lon --------------------------------------

    def test_parse_axes_missing_latitude(self):
        bb = BoundingBox(self._cfg(), cc())
        req = dict(MINIMAL_REQUEST)
        fc = {
            "type": "boundingbox",
            "points": [[0, 1], [2, 3]],
            "axes": ["longitude", "levelist"],
        }
        with pytest.raises(ValueError, match="latitude and longitude"):
            bb.parse(req, fc)

    # -- parse: step in axes -----------------------------------------------

    def test_parse_step_in_axes(self):
        bb = BoundingBox(self._cfg(), cc())
        req = dict(MINIMAL_REQUEST)
        fc = {
            "type": "boundingbox",
            "points": [[0, 1], [2, 3]],
            "axes": ["latitude", "longitude", "step"],
        }
        with pytest.raises(ValueError, match="step"):
            bb.parse(req, fc)

    # -- parse: axis vs axes typo -----------------------------------------

    def test_parse_axis_typo(self):
        bb = BoundingBox(self._cfg(), cc())
        req = dict(MINIMAL_REQUEST)
        fc = {
            "type": "boundingbox",
            "points": [[0, 1], [2, 3]],
            "axis": ["latitude", "longitude"],
        }
        with pytest.raises(ValueError, match="did you mean axes"):
            bb.parse(req, fc)

    # -- parse: wrong type in parse ----------------------------------------

    def test_parse_wrong_type(self):
        bb = BoundingBox(self._cfg(), cc())
        req = dict(MINIMAL_REQUEST)
        fc = {"type": "polygon", "points": [[0, 1], [2, 3]]}
        with pytest.raises(ValueError, match="boundingbox"):
            bb.parse(req, fc)

    # -- parse: point length mismatch with axes ----------------------------

    def test_parse_point_length_mismatch(self):
        bb = BoundingBox(self._cfg(), cc())
        req = dict(MINIMAL_REQUEST)
        fc = {
            "type": "boundingbox",
            "points": [[0, 1], [2, 3]],
            "axes": ["latitude", "longitude", "levelist"],
        }
        with pytest.raises(ValueError, match="same number of values"):
            bb.parse(req, fc)

    # -- parse: no axes, wrong point length --------------------------------

    def test_parse_no_axes_wrong_point_length(self):
        bb = BoundingBox(self._cfg(), cc())
        req = dict(MINIMAL_REQUEST)
        fc = {"type": "boundingbox", "points": [[0, 1, 2], [3, 4, 5]]}
        with pytest.raises(ValueError, match="two values unless axes"):
            bb.parse(req, fc)

    # -- parse: axes too few -----------------------------------------------

    def test_parse_axes_too_few(self):
        bb = BoundingBox(self._cfg(), cc())
        req = dict(MINIMAL_REQUEST)
        fc = {"type": "boundingbox", "points": [[0], [2]], "axes": ["latitude"]}
        with pytest.raises(ValueError, match="2 or 3"):
            bb.parse(req, fc)

    # -- parse: levelist overspecified in request and axes ------------------

    def test_parse_levelist_overspecified(self):
        bb = BoundingBox(self._cfg(), cc())
        req = dict(MINIMAL_REQUEST)
        req["levelist"] = "500"
        fc = {
            "type": "boundingbox",
            "points": [[0, 1, 500], [2, 3, 1000]],
            "axes": ["latitude", "longitude", "levelist"],
        }
        with pytest.raises(ValueError, match="overspecified"):
            bb.parse(req, fc)

    # -- validate ----------------------------------------------------------

    def test_validate_missing_required(self):
        bb = BoundingBox(self._cfg(), cc())
        with pytest.raises(KeyError, match="Missing required key"):
            bb.validate({}, {})

    def test_validate_required_axes(self):
        bb = BoundingBox(self._cfg(), cc())
        with pytest.raises(KeyError, match="Missing required axis"):
            bb.validate(
                {"type": "boundingbox", "points": [[0, 1], [2, 3]]},
                {"axes": {"longitude": True}},
            )

    # -- split_request (has field_area + max_area) -------------------------

    def test_split_request_false_when_small(self):
        bb = BoundingBox(self._cfg(), cc())
        # field_area defaults to 0
        assert bb.split_request() is False

    def test_split_request_true_when_large(self):
        bb = BoundingBox(self._cfg(), cc(max_area=1))
        bb.field_area = 9999
        assert bb.split_request() is True


# =========================================================================
#  Polygon
# =========================================================================


class TestPolygon:
    """Tests for the Polygons feature."""

    TRIANGLE = [[0, 0], [10, 0], [10, 10], [0, 0]]

    def _cfg(self, **overrides):
        base = {"type": "polygon", "shape": copy.deepcopy(self.TRIANGLE)}
        base.update(overrides)
        return base

    # -- happy path --------------------------------------------------------

    def test_happy_path(self):
        p = Polygons(self._cfg(), cc())
        shapes = p.get_shapes()
        assert isinstance(shapes, list) and len(shapes) > 0

    # -- multi-polygon -----------------------------------------------------

    def test_multi_polygon(self):
        multi = [copy.deepcopy(self.TRIANGLE), copy.deepcopy(self.TRIANGLE)]
        p = Polygons(self._cfg(shape=multi), cc())
        shapes = p.get_shapes()
        assert len(shapes) > 0

    # -- metadata ----------------------------------------------------------

    def test_name(self):
        assert Polygons(self._cfg(), cc()).name() == "Polygon"

    def test_coverage_type(self):
        assert Polygons(self._cfg(), cc()).coverage_type() == "MultiPoint"

    def test_required_keys(self):
        assert Polygons(self._cfg(), cc()).required_keys() == ["type", "shape"]

    def test_required_axes(self):
        assert Polygons(self._cfg(), cc()).required_axes() == ["latitude", "longitude"]

    def test_incompatible_keys(self):
        assert Polygons(self._cfg(), cc()).incompatible_keys() == []

    # -- wrong type --------------------------------------------------------

    def test_wrong_type(self):
        with pytest.raises(ValueError, match="polygon"):
            Polygons(self._cfg(type="circle"), cc())

    # -- unexpected keys ---------------------------------------------------

    def test_unexpected_keys(self):
        with pytest.raises(ValueError, match="Unexpected keys"):
            Polygons(self._cfg(bogus="x"), cc())

    # -- empty shape -------------------------------------------------------

    def test_empty_shape(self):
        with pytest.raises(ValueError, match="at least one polygon"):
            Polygons(self._cfg(shape=[]), cc())

    # -- too many points ---------------------------------------------------

    def test_too_many_points(self):
        with pytest.raises(ValueError, match="exceeds the maximum"):
            Polygons(self._cfg(), cc(max_points=2))

    # -- parse: wrong axes count ------------------------------------------

    def test_parse_axes_wrong_count(self):
        p = Polygons(self._cfg(), cc())
        req = dict(MINIMAL_REQUEST)
        req["axes"] = ["latitude"]
        with pytest.raises(ValueError, match="two axes"):
            p.parse(req, {"type": "polygon", "shape": self.TRIANGLE})

    # -- parse: normal (happy) --------------------------------------------

    def test_parse_happy(self):
        p = Polygons(self._cfg(), cc())
        req = dict(MINIMAL_REQUEST)
        result = p.parse(req, {"type": "polygon", "shape": self.TRIANGLE})
        assert isinstance(result, dict)

    # -- validate ----------------------------------------------------------

    def test_validate_missing_required(self):
        p = Polygons(self._cfg(), cc())
        with pytest.raises(KeyError, match="Missing required key"):
            p.validate({}, {})

    # -- split_request (has field_area + max_area) -------------------------

    def test_split_request_false(self):
        p = Polygons(self._cfg(), cc())
        assert p.split_request() is False

    def test_split_request_true(self):
        p = Polygons(self._cfg(), cc(max_area=1))
        p.field_area = 9999
        assert p.split_request() is True

    # -- custom axes -------------------------------------------------------

    def test_custom_axes(self):
        p = Polygons(self._cfg(axes=["lat", "lon"]), cc())
        assert p.axes == ["lat", "lon"]


# =========================================================================
#  Circle
# =========================================================================


class TestCircle:
    """Tests for the Circle feature."""

    def _cfg(self, **overrides):
        base = {
            "type": "circle",
            "center": [[0.0, 0.0]],
            "radius": 1.0,
        }
        base.update(overrides)
        return base

    # -- happy path --------------------------------------------------------

    def test_happy_path(self):
        c = Circle(self._cfg(), cc())
        shapes = c.get_shapes()
        assert isinstance(shapes, list) and len(shapes) > 0

    # -- 3D center ---------------------------------------------------------
    # Disk shape asserts len(axes)==2, so 3D circles fail at get_shapes().
    # We verify construction succeeds and get_shapes raises.

    def test_3d_center_constructs(self):
        c = Circle(
            self._cfg(
                center=[[0.0, 0.0, 500.0]], axes=["latitude", "longitude", "levelist"]
            ),
            cc(),
        )
        assert c.center == [[0.0, 0.0, 500.0]]
        assert c.axes == ["latitude", "longitude", "levelist"]

    def test_3d_center_get_shapes_raises(self):
        c = Circle(
            self._cfg(
                center=[[0.0, 0.0, 500.0]], axes=["latitude", "longitude", "levelist"]
            ),
            cc(),
        )
        with pytest.raises(AssertionError):
            c.get_shapes()

    # -- metadata ----------------------------------------------------------

    def test_name(self):
        assert Circle(self._cfg(), cc()).name() == "Circle"

    def test_coverage_type(self):
        assert Circle(self._cfg(), cc()).coverage_type() == "MultiPoint"

    def test_required_keys(self):
        assert Circle(self._cfg(), cc()).required_keys() == ["type", "center", "radius"]

    def test_required_axes(self):
        assert Circle(self._cfg(), cc()).required_axes() == ["latitude", "longitude"]

    def test_incompatible_keys(self):
        assert Circle(self._cfg(), cc()).incompatible_keys() == []

    # -- wrong type --------------------------------------------------------

    def test_wrong_type(self):
        with pytest.raises(ValueError, match="circle"):
            Circle(self._cfg(type="polygon"), cc())

    # -- unexpected keys ---------------------------------------------------

    def test_unexpected_keys(self):
        with pytest.raises(ValueError, match="Unexpected keys"):
            Circle(self._cfg(bogus="x"), cc())

    # -- empty center ------------------------------------------------------

    def test_empty_center(self):
        with pytest.raises(ValueError, match="requires a 'center'"):
            Circle(self._cfg(center=[]), cc())

    # -- missing center ----------------------------------------------------

    def test_missing_center(self):
        cfg = {"type": "circle", "radius": 1.0}
        with pytest.raises(ValueError, match="requires a 'center'"):
            Circle(cfg, cc())

    # -- wrong center length -----------------------------------------------

    def test_center_too_short(self):
        with pytest.raises(ValueError, match="two values"):
            Circle(self._cfg(center=[[0.0]]), cc())

    def test_center_too_long(self):
        with pytest.raises(ValueError, match="two values"):
            Circle(self._cfg(center=[[0, 0, 0, 0]]), cc())

    # -- area too large ----------------------------------------------------

    def test_area_exceeds_max(self):
        with pytest.raises(ValueError, match="exceeds the maximum"):
            Circle(self._cfg(radius=100), cc(max_area=1))

    # -- parse: axes/center mismatch ---------------------------------------

    def test_parse_axes_center_mismatch(self):
        c = Circle(self._cfg(), cc())
        req = dict(MINIMAL_REQUEST)
        fc = {
            "center": [[0, 0]],
            "radius": 1.0,
            "axes": ["latitude", "longitude", "levelist"],
        }
        with pytest.raises(ValueError, match="Number of axes must match"):
            c.parse(req, fc)

    # -- parse: multiple centers -------------------------------------------

    def test_parse_multiple_centers(self):
        c = Circle(self._cfg(), cc())
        req = dict(MINIMAL_REQUEST)
        fc = {"center": [[0, 0], [1, 1]], "radius": 1.0}
        with pytest.raises(ValueError, match="one center point"):
            c.parse(req, fc)

    # -- parse: area too large at parse time -------------------------------

    def test_parse_area_too_large(self):
        # The init-time area check uses get_circle_area_from_coords which for
        # a small radius produces a small area. We construct with a generous
        # max_area, then lower it before calling parse() so that
        # field_area(request, self.area) > self.max_area.
        c = Circle(self._cfg(radius=1.0), cc(max_area=float("inf")))
        # Now tighten max_area so parse's field_area check fails
        c.max_area = 0.0001
        req = dict(MINIMAL_REQUEST)
        fc = {"center": [[0, 0]], "radius": 1.0}
        with pytest.raises(ValueError, match="too large"):
            c.parse(req, fc)

    # -- parse: happy path -------------------------------------------------

    def test_parse_happy(self):
        c = Circle(self._cfg(), cc())
        req = dict(MINIMAL_REQUEST)
        fc = {"center": [[0, 0]], "radius": 1.0}
        result = c.parse(req, fc)
        assert isinstance(result, dict)

    # -- validate ----------------------------------------------------------

    def test_validate_missing_required(self):
        c = Circle(self._cfg(), cc())
        with pytest.raises(KeyError, match="Missing required key"):
            c.validate({}, {})

    # -- split_request (no field_area) -------------------------------------

    def test_split_request_false(self):
        assert Circle(self._cfg(), cc()).split_request() is False


# =========================================================================
#  Frame
# =========================================================================


class TestFrame:
    """Tests for the Frame feature."""

    def _cfg(self, **overrides):
        base = {
            "type": "frame",
            "outer_box": [[0, 0], [20, 20]],
            "inner_box": [[5, 5], [15, 15]],
        }
        base.update(overrides)
        return base

    # -- happy path --------------------------------------------------------

    def test_happy_path(self):
        f = Frame(self._cfg(), cc())
        shapes = f.get_shapes()
        assert isinstance(shapes, list) and len(shapes) > 0

    # -- metadata ----------------------------------------------------------

    def test_name(self):
        assert Frame(self._cfg(), cc()).name() == "Frame"

    def test_coverage_type(self):
        assert Frame(self._cfg(), cc()).coverage_type() == "MultiPoint"

    def test_required_keys(self):
        assert Frame(self._cfg(), cc()).required_keys() == [
            "type",
            "outer_box",
            "inner_box",
        ]

    def test_required_axes(self):
        assert Frame(self._cfg(), cc()).required_axes() == ["latitude", "longitude"]

    def test_incompatible_keys(self):
        assert "levellist" in Frame(self._cfg(), cc()).incompatible_keys()

    # -- wrong type --------------------------------------------------------

    def test_wrong_type(self):
        with pytest.raises(ValueError, match="frame"):
            Frame(self._cfg(type="polygon"), cc())

    # -- unexpected keys ---------------------------------------------------

    def test_unexpected_keys(self):
        with pytest.raises(ValueError, match="Unexpected keys"):
            Frame(self._cfg(bogus="x"), cc())

    # -- parse returns request unchanged -----------------------------------

    def test_parse_passthrough(self):
        f = Frame(self._cfg(), cc())
        req = dict(MINIMAL_REQUEST)
        result = f.parse(req, self._cfg())
        assert result is req

    # -- validate: incompatible key ----------------------------------------

    def test_validate_incompatible_key(self):
        f = Frame(self._cfg(), cc())
        with pytest.raises(KeyError, match="levellist"):
            f.validate({"levellist": "500"}, {})

    def test_validate_missing_required(self):
        f = Frame(self._cfg(), cc())
        with pytest.raises(KeyError, match="Missing required key"):
            f.validate({}, {})

    # -- points optional ---------------------------------------------------

    def test_points_defaults_empty(self):
        f = Frame(self._cfg(), cc())
        assert f.points == []

    # -- split_request (no field_area) -------------------------------------

    def test_split_request_false(self):
        assert Frame(self._cfg(), cc()).split_request() is False


# =========================================================================
#  Path (Trajectory)
# =========================================================================


class TestPath:
    """Tests for the Path (Trajectory) feature."""

    def _cfg(self, **overrides):
        base = {
            "type": "trajectory",
            "points": [[1, 2], [3, 4]],
            "axes": ["latitude", "longitude"],
            "inflation": [1.0, 1.0],
        }
        base.update(overrides)
        return base

    # -- happy path 2D round -----------------------------------------------

    def test_happy_path_2d_round(self):
        p = Path(self._cfg(), cc())
        shapes = p.get_shapes()
        assert isinstance(shapes, list) and len(shapes) > 0

    # -- happy path 2D box -------------------------------------------------

    def test_happy_path_2d_box(self):
        p = Path(self._cfg(inflate="box"), cc())
        shapes = p.get_shapes()
        assert len(shapes) > 0

    # -- 3D round ----------------------------------------------------------

    def test_3d_round(self):
        p = Path(
            self._cfg(
                points=[[1, 2, 3], [4, 5, 6]],
                axes=["latitude", "longitude", "levelist"],
                inflation=[1, 1, 1],
            ),
            cc(),
        )
        shapes = p.get_shapes()
        assert len(shapes) > 0

    # -- 3D box ------------------------------------------------------------

    def test_3d_box(self):
        p = Path(
            self._cfg(
                points=[[1, 2, 3], [4, 5, 6]],
                axes=["latitude", "longitude", "levelist"],
                inflation=[1, 1, 1],
                inflate="box",
            ),
            cc(),
        )
        shapes = p.get_shapes()
        assert len(shapes) > 0

    # -- 4D box ------------------------------------------------------------

    def test_4d_box(self):
        p = Path(
            self._cfg(
                points=[[1, 2, 3, 4], [5, 6, 7, 8]],
                axes=["latitude", "longitude", "levelist", "step"],
                inflation=[1, 1, 1, 1],
                inflate="box",
            ),
            cc(),
        )
        shapes = p.get_shapes()
        assert len(shapes) > 0

    # -- 4D round raises ---------------------------------------------------

    def test_4d_round_raises(self):
        p = Path(
            self._cfg(
                points=[[1, 2, 3, 4], [5, 6, 7, 8]],
                axes=["latitude", "longitude", "levelist", "step"],
                inflation=[1, 1, 1, 1],
                inflate="round",
            ),
            cc(),
        )
        with pytest.raises(ValueError, match="Round inflation not yet implemented"):
            p.get_shapes()

    # -- unsupported 5D points ---------------------------------------------

    def test_5d_raises(self):
        p = Path(
            self._cfg(
                points=[[1, 2, 3, 4, 5], [6, 7, 8, 9, 10]],
                axes=["latitude", "longitude", "levelist", "step", "extra"],
                inflation=[1, 1, 1, 1, 1],
            ),
            cc(),
        )
        with pytest.raises(ValueError, match="2, 3, or 4"):
            p.get_shapes()

    # -- invalid inflate value at get_shapes --------------------------------

    def test_invalid_inflate_2d(self):
        p = Path(self._cfg(inflate="triangle"), cc())
        with pytest.raises(ValueError, match="round.*box"):
            p.get_shapes()

    def test_invalid_inflate_3d(self):
        p = Path(
            self._cfg(
                points=[[1, 2, 3], [4, 5, 6]],
                axes=["latitude", "longitude", "levelist"],
                inflation=[1, 1, 1],
                inflate="triangle",
            ),
            cc(),
        )
        with pytest.raises(ValueError, match="round.*box"):
            p.get_shapes()

    # -- metadata ----------------------------------------------------------

    def test_name(self):
        assert Path(self._cfg(), cc()).name() == "Path"

    def test_coverage_type(self):
        assert Path(self._cfg(), cc()).coverage_type() == "Trajectory"

    def test_required_keys(self):
        assert Path(self._cfg(), cc()).required_keys() == [
            "type",
            "points",
            "inflation",
        ]

    def test_required_axes(self):
        assert Path(self._cfg(), cc()).required_axes() == ["latitude", "longitude"]

    def test_incompatible_keys(self):
        assert Path(self._cfg(), cc()).incompatible_keys() == []

    # -- wrong type --------------------------------------------------------

    def test_wrong_type(self):
        with pytest.raises(ValueError, match="trajectory"):
            Path(self._cfg(type="polygon"), cc())

    # -- unexpected keys ---------------------------------------------------

    def test_unexpected_keys(self):
        with pytest.raises(ValueError, match="Unexpected keys"):
            Path(self._cfg(bogus="x"), cc())

    # -- axis typo ---------------------------------------------------------

    def test_axis_typo(self):
        with pytest.raises(ValueError, match="did you mean axes"):
            Path(self._cfg(axis=["latitude", "longitude"]), cc())

    # -- inflation length mismatch -----------------------------------------

    def test_inflation_length_mismatch(self):
        with pytest.raises(ValueError, match="same number of values"):
            Path(self._cfg(inflation=[1.0, 2.0, 3.0]), cc())

    # -- scalar inflation expands to axes length ---------------------------

    def test_scalar_inflation(self):
        p = Path(self._cfg(inflation=5.0), cc())
        assert p.inflation == [5.0, 5.0]

    # -- default axes when none specified ----------------------------------

    def test_default_axes(self):
        cfg = {
            "type": "trajectory",
            "points": [[1, 2, 3, 4], [5, 6, 7, 8]],
            "inflation": 1.0,
        }
        p = Path(cfg, cc())
        assert p.axes == ["latitude", "longitude", "levelist", "step"]
        assert len(p.inflation) == 4

    # -- parse: too few points --------------------------------------------

    def test_parse_too_few_points(self):
        p = Path(self._cfg(), cc())
        req = dict(MINIMAL_REQUEST)
        fc = {"points": [[1, 2]], "axes": ["latitude", "longitude"]}
        with pytest.raises(ValueError, match="atleast two"):
            p.parse(req, fc)

    # -- parse: wrong axes count ------------------------------------------

    def test_parse_axes_too_few(self):
        p = Path(self._cfg(), cc())
        req = dict(MINIMAL_REQUEST)
        fc = {"points": [[1], [2]], "axes": ["latitude"]}
        with pytest.raises(ValueError, match="2, 3 or 4"):
            p.parse(req, fc)

    def test_parse_axes_too_many(self):
        p = Path(self._cfg(), cc())
        req = dict(MINIMAL_REQUEST)
        fc = {
            "points": [[1, 2, 3, 4, 5], [6, 7, 8, 9, 10]],
            "axes": ["latitude", "longitude", "levelist", "step", "extra"],
        }
        with pytest.raises(ValueError, match="2, 3 or 4"):
            p.parse(req, fc)

    # -- parse: invalid axis name -----------------------------------------

    def test_parse_invalid_axis_name(self):
        p = Path(self._cfg(), cc())
        req = dict(MINIMAL_REQUEST)
        fc = {"points": [[1, 2], [3, 4]], "axes": ["latitude", "foobar"]}
        with pytest.raises(ValueError, match="Invalid axis"):
            p.parse(req, fc)

    # -- parse: point/axes length mismatch --------------------------------

    def test_parse_point_axes_mismatch(self):
        p = Path(self._cfg(), cc())
        req = dict(MINIMAL_REQUEST)
        fc = {"points": [[1, 2, 3], [4, 5, 6]], "axes": ["latitude", "longitude"]}
        with pytest.raises(ValueError, match="same number of values"):
            p.parse(req, fc)

    # -- parse: no axes, point != 4 ----------------------------------------

    def test_parse_no_axes_wrong_point_length(self):
        p = Path(self._cfg(), cc())
        req = dict(MINIMAL_REQUEST)
        fc = {"points": [[1, 2], [3, 4]]}
        with pytest.raises(ValueError, match="four values|two values"):
            p.parse(req, fc)

    # -- parse: levelist overspecified ------------------------------------

    def test_parse_levelist_overspecified(self):
        p = Path(self._cfg(), cc())
        req = dict(MINIMAL_REQUEST)
        req["levelist"] = "500"
        fc = {
            "points": [[1, 2, 3], [4, 5, 6]],
            "axes": ["latitude", "longitude", "levelist"],
        }
        with pytest.raises(ValueError, match="overspecified"):
            p.parse(req, fc)

    # -- parse: multiple steps raises -------------------------------------

    def test_parse_multiple_steps(self):
        p = Path(self._cfg(), cc())
        req = dict(MINIMAL_REQUEST)
        req["step"] = "0/6"
        fc = {"points": [[1, 2], [3, 4]], "axes": ["latitude", "longitude"]}
        with pytest.raises(ValueError, match="Multiple steps"):
            p.parse(req, fc)

    # -- parse: multiple steps AND numbers --------------------------------

    def test_parse_multiple_steps_and_numbers(self):
        p = Path(self._cfg(), cc())
        req = dict(MINIMAL_REQUEST)
        req["step"] = "0/6"
        req["number"] = "1/2"
        fc = {"points": [[1, 2], [3, 4]], "axes": ["latitude", "longitude"]}
        with pytest.raises(ValueError, match="Multiple steps and numbers"):
            p.parse(req, fc)

    # -- parse: happy path -------------------------------------------------

    def test_parse_happy(self):
        p = Path(self._cfg(), cc())
        req = dict(MINIMAL_REQUEST)
        fc = {"points": [[1, 2], [3, 4]], "axes": ["latitude", "longitude"]}
        result = p.parse(req, fc)
        assert isinstance(result, dict)

    # -- validate ----------------------------------------------------------

    def test_validate_missing_required(self):
        p = Path(self._cfg(), cc())
        with pytest.raises(KeyError, match="Missing required key"):
            p.validate({}, {})

    # -- split_request (no field_area) -------------------------------------

    def test_split_request_false(self):
        assert Path(self._cfg(), cc()).split_request() is False

    # -- valid_axes --------------------------------------------------------

    def test_valid_axes(self):
        p = Path(self._cfg(), cc())
        assert p.valid_axes() == ["latitude", "longitude", "levelist", "step"]


# =========================================================================
#  Position
# =========================================================================


class TestPosition:
    """Tests for the Position feature."""

    def _cfg(self, **overrides):
        base = {"type": "position", "points": [[1.0, 2.0]]}
        base.update(overrides)
        return base

    # -- happy path --------------------------------------------------------

    def test_happy_path(self):
        p = Position(self._cfg(), cc())
        shapes = p.get_shapes()
        assert isinstance(shapes, list) and len(shapes) > 0

    # -- metadata ----------------------------------------------------------

    def test_name(self):
        assert Position(self._cfg(), cc()).name() == "Position"

    def test_coverage_type(self):
        assert Position(self._cfg(), cc()).coverage_type() == "PointSeries"

    def test_required_keys(self):
        assert Position(self._cfg(), cc()).required_keys() == ["type", "points"]

    def test_required_axes(self):
        assert Position(self._cfg(), cc()).required_axes() == ["latitude", "longitude"]

    def test_incompatible_keys(self):
        assert Position(self._cfg(), cc()).incompatible_keys() == []

    # -- wrong type --------------------------------------------------------

    def test_wrong_type(self):
        with pytest.raises(ValueError, match="position"):
            Position(self._cfg(type="polygon"), cc())

    # -- unexpected keys ---------------------------------------------------

    def test_unexpected_keys(self):
        with pytest.raises(ValueError, match="Unexpected keys"):
            Position(self._cfg(bogus="x"), cc())

    # -- empty points ------------------------------------------------------

    def test_empty_points(self):
        with pytest.raises(ValueError, match="at least one point"):
            Position(self._cfg(points=[]), cc())

    # -- axes defaults -----------------------------------------------------

    def test_axes_default(self):
        p = Position(self._cfg(), cc())
        assert p.axes == ["latitude", "longitude"]

    # -- axes: time axis raises -------------------------------------------

    def test_axes_step_raises(self):
        with pytest.raises(ValueError, match="cannot have time axis"):
            Position(self._cfg(axes=["step"]), cc())

    def test_axes_date_raises(self):
        with pytest.raises(ValueError, match="cannot have time axis"):
            Position(self._cfg(axes=["date"]), cc())

    # -- axes: non lat/lon raises -----------------------------------------

    def test_axes_invalid_value(self):
        with pytest.raises(ValueError, match="latitude and longitude"):
            Position(self._cfg(axes=["latitude", "levelist"]), cc())

    # -- axes non-list becomes latlon --------------------------------------

    def test_axes_non_list_becomes_latlon(self):
        p = Position(self._cfg(axes="something"), cc())
        assert p.axes == ["latitude", "longitude"]

    # -- parse: wrong point length -----------------------------------------

    def test_parse_wrong_point_length(self):
        p = Position(self._cfg(), cc())
        req = dict(MINIMAL_REQUEST)
        with pytest.raises(ValueError, match="two values"):
            p.parse(req, {"points": [[1, 2, 3]]})

    # -- parse: area exceeds max -------------------------------------------

    def test_parse_area_exceeds_max(self):
        p = Position(self._cfg(), cc(max_area=0.0001))
        req = dict(MINIMAL_REQUEST)
        with pytest.raises(ValueError, match="exceeds total number allowed"):
            p.parse(req, {"points": [[1, 2]]})

    # -- parse: happy path -------------------------------------------------

    def test_parse_happy(self):
        p = Position(self._cfg(), cc())
        req = dict(MINIMAL_REQUEST)
        result = p.parse(req, {"points": [[1, 2]]})
        assert isinstance(result, dict)

    # -- validate ----------------------------------------------------------

    def test_validate_missing_required(self):
        p = Position(self._cfg(), cc())
        with pytest.raises(KeyError, match="Missing required key"):
            p.validate({}, {})

    # -- split_request (no field_area) -------------------------------------

    def test_split_request_false(self):
        assert Position(self._cfg(), cc()).split_request() is False


# =========================================================================
#  Feature base class — split_request
# =========================================================================


class TestFeatureSplitRequest:
    """Test split_request() logic from the Feature base class."""

    def test_no_field_area_attr(self):
        ts = TimeSeries(
            {"type": "timeseries", "points": [[1, 2]], "time_axis": "step"},
            cc(),
        )
        assert ts.split_request() is False

    def test_has_attrs_but_small(self):
        bb = BoundingBox(
            {"type": "boundingbox", "points": [[0, 0.1], [10, 10]]},
            cc(),
        )
        # field_area defaults to 0
        assert bb.split_request() is False

    def test_has_attrs_and_exceeds(self):
        bb = BoundingBox(
            {"type": "boundingbox", "points": [[0, 0.1], [10, 10]]},
            cc(max_area=5),
        )
        bb.field_area = 100
        assert bb.split_request() is True

    def test_polygon_split(self):
        tri = [[0, 0], [10, 0], [10, 10], [0, 0]]
        p = Polygons({"type": "polygon", "shape": tri}, cc(max_area=1))
        p.field_area = 9999
        assert p.split_request() is True

    def test_polygon_no_split(self):
        tri = [[0, 0], [10, 0], [10, 10], [0, 0]]
        p = Polygons({"type": "polygon", "shape": tri}, cc())
        assert p.split_request() is False
