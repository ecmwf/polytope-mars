import sys
import types

from conflator import Conflator

from polytope_mars.config import PolytopeMarsConfig
from polytope_mars.features.boundingbox import BoundingBox


def _ensure_fake_pygribjump():
    if "pygribjump" in sys.modules:
        return
    fake = types.ModuleType("pygribjump")
    fake.GribJump = lambda *a, **k: object()
    sys.modules["pygribjump"] = fake


def _make_conf():
    conf = Conflator(app_name="polytope_mars", model=PolytopeMarsConfig).load()
    return conf


class TestBoundingBoxInterpolationOption:
    def test_no_grid_means_no_interpolation_options(self):
        bb = BoundingBox(
            {"type": "boundingbox", "points": [[0, 0], [1, 1]]},
            _make_conf(),
        )
        assert bb.interpolation_options() is None

    def test_grid_keyword_produces_interpolation_options(self):
        bb = BoundingBox(
            {
                "type": "boundingbox",
                "points": [[0, 0], [1, 1]],
                "grid": {"type": "octahedral", "resolution": 1280, "method": "linear"},
            },
            _make_conf(),
        )
        assert bb.interpolation_options() == {
            "method": "linear",
            "out_grid": {"type": "octahedral", "resolution": 1280},
        }

    def test_grid_keyword_defaults_method_to_linear(self):
        bb = BoundingBox(
            {
                "type": "boundingbox",
                "points": [[0, 0], [1, 1]],
                "grid": {"type": "regular", "resolution": [0.25, 0.25]},
            },
            _make_conf(),
        )
        assert bb.interpolation_options()["method"] == "linear"

    def test_grid_keyword_allows_3d_bbox(self):
        """Higher-dimensional bounding boxes (lat/lon + levelist) are supported: the
        polytope engine slices lat/lon against the output grid and levelist normally,
        in a single pass.
        """
        bb = BoundingBox(
            {
                "type": "boundingbox",
                "points": [[0, 0, 0], [1, 1, 10]],
                "axes": ["latitude", "longitude", "levelist"],
                "grid": {"type": "octahedral", "resolution": 1280},
            },
            _make_conf(),
        )
        assert bb.interpolation_options() == {
            "method": "linear",
            "out_grid": {"type": "octahedral", "resolution": 1280},
        }

    def test_grid_keyword_requires_type_and_resolution(self):
        import pytest

        with pytest.raises(ValueError):
            BoundingBox(
                {
                    "type": "boundingbox",
                    "points": [[0, 0], [1, 1]],
                    "grid": {"type": "octahedral"},
                },
                _make_conf(),
            )


class TestRetrieveDataWiresInterpolationOptions:
    def test_interpolation_options_forwarded_to_polytope(self, monkeypatch):
        _ensure_fake_pygribjump()
        import polytope_mars.api as api_module

        captured = {}

        class FakePolytope:
            def __init__(self, datacube, options, context):
                captured["options"] = options

            def retrieve(self, preq):
                return types.SimpleNamespace(pprint=lambda: "<fake tree>")

        class FakeEncoder:
            def encode(self, *a, **k):
                return self

            def from_polytope(self, result):
                return {"fake": "coverage"}

        monkeypatch.setattr(api_module, "Polytope", FakePolytope)
        monkeypatch.setattr(api_module, "Covjsonkit", lambda *a, **k: FakeEncoder())
        monkeypatch.setattr(api_module.gj, "GribJump", lambda: object())

        pm = api_module.PolytopeMars(_make_conf().model_dump())
        feature = BoundingBox(
            {
                "type": "boundingbox",
                "points": [[0, 0], [1, 1]],
                "grid": {"type": "octahedral", "resolution": 1280, "method": "nearest-neighbour"},
            },
            _make_conf(),
        )
        request = {
            "class": "od",
            "stream": "oper",
            "type": "fc",
            "date": "20240101",
            "time": "0000",
            "levtype": "sfc",
            "expver": "0001",
            "domain": "g",
            "param": "167",
            "step": "0",
        }
        pm.retrieve_data(request, "boundingbox", feature)

        assert captured["options"]["interpolation"] == {
            "method": "nearest-neighbour",
            "out_grid": {"type": "octahedral", "resolution": 1280},
        }

    def test_no_interpolation_option_when_grid_not_requested(self, monkeypatch):
        _ensure_fake_pygribjump()
        import polytope_mars.api as api_module

        captured = {}

        class FakePolytope:
            def __init__(self, datacube, options, context):
                captured["options"] = options

            def retrieve(self, preq):
                return types.SimpleNamespace(pprint=lambda: "<fake tree>")

        class FakeEncoder:
            def encode(self, *a, **k):
                return self

            def from_polytope(self, result):
                return {"fake": "coverage"}

        monkeypatch.setattr(api_module, "Polytope", FakePolytope)
        monkeypatch.setattr(api_module, "Covjsonkit", lambda *a, **k: FakeEncoder())
        monkeypatch.setattr(api_module.gj, "GribJump", lambda: object())

        pm = api_module.PolytopeMars(_make_conf().model_dump())
        feature = BoundingBox(
            {"type": "boundingbox", "points": [[0, 0], [1, 1]]},
            _make_conf(),
        )
        request = {
            "class": "od",
            "stream": "oper",
            "type": "fc",
            "date": "20240101",
            "time": "0000",
            "levtype": "sfc",
            "expver": "0001",
            "domain": "g",
            "param": "167",
            "step": "0",
        }
        pm.retrieve_data(request, "boundingbox", feature)

        assert captured["options"].get("interpolation") is None


class TestOtherFeaturesInterpolationOption:
    """Verifies the "grid" option (via Feature._pop_grid_option/interpolation_options)
    also works for shapes other than BoundingBox, since the polytope engine now
    supports interpolating any 2D lat/lon shape (Disk, Polygon, Point, ...).
    """

    def test_circle_grid_option(self):
        from polytope_mars.features.circle import Circle

        circle = Circle(
            {
                "type": "circle",
                "center": [[10, 20]],
                "radius": 5,
                "grid": {"type": "octahedral", "resolution": 1280, "method": "linear"},
            },
            _make_conf(),
        )
        assert circle.interpolation_options() == {
            "method": "linear",
            "out_grid": {"type": "octahedral", "resolution": 1280},
        }

    def test_circle_grid_option_allows_3d(self):
        """Higher-dimensional shapes (eg. a circle spanning latitude/longitude/levelist)
        are supported too - the polytope engine slices the lat/lon part of the shape
        against the output grid and the rest (eg. levelist) normally, in one pass.
        """
        from polytope_mars.features.circle import Circle

        circle = Circle(
            {
                "type": "circle",
                "center": [[10, 20, 5]],
                "radius": 5,
                "axes": ["latitude", "longitude", "levelist"],
                "grid": {"type": "octahedral", "resolution": 1280},
            },
            _make_conf(),
        )
        assert circle.interpolation_options() == {
            "method": "linear",
            "out_grid": {"type": "octahedral", "resolution": 1280},
        }

    def test_circle_grid_option_requires_lat_lon_axes(self):
        import pytest

        from polytope_mars.features.circle import Circle

        with pytest.raises(ValueError):
            Circle(
                {
                    "type": "circle",
                    "center": [[10, 5]],
                    "radius": 5,
                    "axes": ["latitude", "levelist"],
                    "grid": {"type": "octahedral", "resolution": 1280},
                },
                _make_conf(),
            )

    def test_polygon_grid_option(self):
        from polytope_mars.features.polygon import Polygons

        polygon = Polygons(
            {
                "type": "polygon",
                "shape": [[0, 0], [1, 0], [1, 1]],
                "grid": {"type": "regular", "resolution": [0.25, 0.25], "method": "nearest-neighbour"},
            },
            _make_conf(),
        )
        assert polygon.interpolation_options() == {
            "method": "nearest-neighbour",
            "out_grid": {"type": "regular", "resolution": [0.25, 0.25]},
        }

    def test_position_grid_option(self):
        from polytope_mars.features.position import Position

        position = Position(
            {
                "type": "position",
                "points": [[10, 20]],
                "grid": {"type": "octahedral", "resolution": 1280},
            },
            _make_conf(),
        )
        assert position.interpolation_options() == {
            "method": "linear",
            "out_grid": {"type": "octahedral", "resolution": 1280},
        }
        # Position's shapes are unaffected by the grid option: still a nearest-neighbour
        # Point shape, which the interpolated-retrieval path knows how to slice too.
        shapes = position.get_shapes()
        assert len(shapes) == 1
        assert shapes[0].method == "nearest"

    def test_no_grid_option_for_any_feature_is_none(self):
        from polytope_mars.features.circle import Circle
        from polytope_mars.features.polygon import Polygons
        from polytope_mars.features.position import Position

        circle = Circle({"type": "circle", "center": [[10, 20]], "radius": 5}, _make_conf())
        polygon = Polygons({"type": "polygon", "shape": [[0, 0], [1, 0], [1, 1]]}, _make_conf())
        position = Position({"type": "position", "points": [[10, 20]]}, _make_conf())

        assert circle.interpolation_options() is None
        assert polygon.interpolation_options() is None
        assert position.interpolation_options() is None


class TestRemainingFeaturesInterpolationOption:
    """Frame, Path (trajectory), TimeSeries and VerticalProfile also support the
    "grid" keyword via the shared Feature._pop_grid_option()/interpolation_options().
    """

    def test_frame_grid_option(self):
        from polytope_mars.features.frame import Frame

        frame = Frame(
            {
                "type": "frame",
                "outer_box": [[0, 0], [10, 10]],
                "inner_box": [[2, 2], [8, 8]],
                "grid": {"type": "octahedral", "resolution": 1280},
            },
            _make_conf(),
        )
        assert frame.interpolation_options() == {
            "method": "linear",
            "out_grid": {"type": "octahedral", "resolution": 1280},
        }

    def test_frame_no_grid_option(self):
        from polytope_mars.features.frame import Frame

        frame = Frame(
            {"type": "frame", "outer_box": [[0, 0], [10, 10]], "inner_box": [[2, 2], [8, 8]]},
            _make_conf(),
        )
        assert frame.interpolation_options() is None

    def test_path_grid_option_2d(self):
        from polytope_mars.features.path import Path

        path = Path(
            {
                "type": "trajectory",
                "points": [[0, 0], [1, 1]],
                "axes": ["latitude", "longitude"],
                "inflation": 1,
                "grid": {"type": "octahedral", "resolution": 1280, "method": "nearest-neighbour"},
            },
            _make_conf(),
        )
        assert path.interpolation_options() == {
            "method": "nearest-neighbour",
            "out_grid": {"type": "octahedral", "resolution": 1280},
        }

    def test_path_grid_option_4d(self):
        """A higher-dimensional trajectory (lat/lon/levelist/step) can use the grid
        option too - the polytope engine slices lat/lon against the output grid and
        levelist/step normally, in a single pass.
        """
        from polytope_mars.features.path import Path

        path = Path(
            {
                "type": "trajectory",
                "points": [[0, 0, 0, 0], [1, 1, 1, 1]],
                "inflation": 1,
                "grid": {"type": "octahedral", "resolution": 1280},
            },
            _make_conf(),
        )
        assert path.interpolation_options() == {
            "method": "linear",
            "out_grid": {"type": "octahedral", "resolution": 1280},
        }

    def test_timeseries_grid_option(self):
        from polytope_mars.features.timeseries import TimeSeries

        ts = TimeSeries(
            {
                "type": "timeseries",
                "points": [[0, 0]],
                "time_axis": "step",
                "grid": {"type": "regular", "resolution": [0.25, 0.25]},
            },
            _make_conf(),
        )
        assert ts.interpolation_options() == {
            "method": "linear",
            "out_grid": {"type": "regular", "resolution": [0.25, 0.25]},
        }
        # Still a nearest-neighbour Point shape, which interpolated retrieval handles too.
        shapes = ts.get_shapes()
        assert len(shapes) == 1
        assert shapes[0].method == "nearest"

    def test_verticalprofile_grid_option(self):
        from polytope_mars.features.verticalprofile import VerticalProfile

        vp = VerticalProfile(
            {
                "type": "verticalprofile",
                "points": [[0, 0]],
                "grid": {"type": "octahedral", "resolution": 1280},
            },
            _make_conf(),
        )
        assert vp.interpolation_options() == {
            "method": "linear",
            "out_grid": {"type": "octahedral", "resolution": 1280},
        }

    def test_no_grid_option_defaults_to_none(self):
        from polytope_mars.features.path import Path
        from polytope_mars.features.timeseries import TimeSeries
        from polytope_mars.features.verticalprofile import VerticalProfile

        path = Path(
            {"type": "trajectory", "points": [[0, 0], [1, 1]], "axes": ["latitude", "longitude"], "inflation": 1},
            _make_conf(),
        )
        ts = TimeSeries({"type": "timeseries", "points": [[0, 0]], "time_axis": "step"}, _make_conf())
        vp = VerticalProfile({"type": "verticalprofile", "points": [[0, 0]]}, _make_conf())

        assert path.interpolation_options() is None
        assert ts.interpolation_options() is None
        assert vp.interpolation_options() is None
