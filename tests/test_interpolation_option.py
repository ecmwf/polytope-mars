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

    def test_grid_keyword_requires_2d_bbox(self):
        import pytest

        with pytest.raises(ValueError):
            BoundingBox(
                {
                    "type": "boundingbox",
                    "points": [[0, 0, 0], [1, 1, 10]],
                    "axes": ["latitude", "longitude", "levelist"],
                    "grid": {"type": "octahedral", "resolution": 1280},
                },
                _make_conf(),
            )

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
