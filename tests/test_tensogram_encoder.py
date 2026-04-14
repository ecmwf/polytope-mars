"""Tests for the tensogram encoder — no FDB/GribJump dependency required."""

import os
import tempfile

import numpy as np
import pytest

from polytope_mars.encoders.tensogram_encoder import (
    TensogramEncoder,
    TensogramResult,
    _numpy_dtype_to_tensogram,
)

# ===================================================================
# Helpers: mock TensorIndexTree nodes
# ===================================================================


class MockAxis:
    """Minimal stand-in for a polytope axis."""

    def __init__(self, name):
        self.name = name


class MockTree:
    """Minimal stand-in for a TensorIndexTree node.

    ``children`` is a list of MockTree.
    ``result`` is only set on leaf nodes (where children is empty).
    """

    def __init__(self, axis_name, values, children=None, result=None):
        self.axis = MockAxis(axis_name)
        self.values = list(values)
        self.children = children if children is not None else []
        self.result = result


def _build_simple_timeseries_tree():
    """Build a minimal tree for a single-point, 2-param, 3-step timeseries.

    Tree shape (simplified):
        root -> class=od -> date=20240101T000000 -> number=1
            -> param=[167, 165] -> step=[0, 1, 2]
                -> latitude=51.5 -> longitude=-0.1  (leaf)

    Leaf result layout (interleaved):
        For 1 level, 1 number, 2 params, 3 steps → 6 values
        Order: param0-step0, param0-step1, param0-step2, param1-step0, ...
    """
    # Leaf: longitude node with interleaved data
    # 2 params × 3 steps = 6 values, 1 longitude point
    leaf = MockTree("longitude", [-0.1], result=[293.5, 294.0, 294.5, 3.2, 3.5, 3.1])

    lat = MockTree("latitude", [51.5], children=[leaf])
    step = MockTree("step", [0, 1, 2], children=[lat])
    param = MockTree("param", [167, 165], children=[step])
    number = MockTree("number", [1], children=[param])
    date = MockTree("date", ["20240101T000000"], children=[number])
    root = MockTree("class", ["od"], children=[date])
    return root


def _build_multipoint_tree():
    """Build a minimal tree for a 3-point bounding box, 1 param, 1 step.

    Leaf result: 3 values (one per lon point).
    """
    leaf = MockTree(
        "longitude",
        [-1.0, 0.0, 1.0],
        result=[290.0, 291.0, 292.0],
    )
    lat = MockTree("latitude", [50.0], children=[leaf])
    step = MockTree("step", [0], children=[lat])
    param = MockTree("param", [167], children=[step])
    number = MockTree("number", [1], children=[param])
    date = MockTree("date", ["20240101T000000"], children=[number])
    root = MockTree("class", ["od"], children=[date])
    return root


def _build_verticalprofile_tree():
    """Vertical profile: 1 point, 2 levels, 1 param, 1 step.

    Leaf result: level0-lon0, level1-lon0 → 2 values.
    """
    leaf = MockTree("longitude", [-0.1], result=[293.5, 250.0])
    lat = MockTree("latitude", [51.5], children=[leaf])
    step = MockTree("step", [0], children=[lat])
    param = MockTree("param", [167], children=[step])
    levelist = MockTree("levelist", [1000, 500], children=[param])
    number = MockTree("number", [1], children=[levelist])
    date = MockTree("date", ["20240101T000000"], children=[number])
    root = MockTree("class", ["od"], children=[date])
    return root


# ===================================================================
# Tests: TensogramResult wrapper
# ===================================================================


class TestTensogramResult:
    def test_empty(self):
        r = TensogramResult()
        assert len(r) == 0
        assert r.messages == []
        assert r.to_bytes() == b""

    def test_add_and_iterate(self):
        r = TensogramResult()
        r.add_message(b"msg1")
        r.add_message(b"msg2")
        assert len(r) == 2
        assert list(r) == [b"msg1", b"msg2"]

    def test_to_bytes(self):
        r = TensogramResult()
        r.add_message(b"aaa")
        r.add_message(b"bbb")
        assert r.to_bytes() == b"aaabbb"

    def test_to_file(self):
        r = TensogramResult()
        r.add_message(b"hello")
        r.add_message(b"world")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".tgm") as f:
            path = f.name
        try:
            r.to_file(path)
            with open(path, "rb") as f:
                assert f.read() == b"helloworld"
        finally:
            os.unlink(path)

    def test_merge(self):
        r1 = TensogramResult()
        r1.add_message(b"a")
        r2 = TensogramResult()
        r2.add_message(b"b")
        r2.add_message(b"c")
        r1.merge(r2)
        assert len(r1) == 3
        assert list(r1) == [b"a", b"b", b"c"]

    def test_messages_returns_copy(self):
        r = TensogramResult()
        r.add_message(b"x")
        msgs = r.messages
        msgs.append(b"y")
        assert len(r) == 1  # original unchanged

    def test_repr(self):
        r = TensogramResult()
        r.add_message(b"x")
        assert "1 messages" in repr(r)


# ===================================================================
# Tests: TensogramEncoder — tree walking (no tensogram import needed)
# ===================================================================


class TestTreeWalking:
    """Test the walk_tree method by inspecting fields/coords/mars_metadata/range_dict."""

    def test_timeseries_walk(self):
        tree = _build_simple_timeseries_tree()
        enc = TensogramEncoder({"param_db": "ecmwf"}, "timeseries")

        fields = {
            "lat": 0,
            "param": [],
            "number": [0],
            "step": [0],
            "dates": [],
            "levels": [0],
        }
        coords = {}
        mars_metadata = {}
        range_dict = {}

        enc.walk_tree(tree, fields, coords, mars_metadata, range_dict)

        assert fields["lat"] == 51.5
        assert fields["param"] == [167, 165]
        assert fields["step"] == [0, 1, 2]
        assert fields["number"] == [1]
        assert len(fields["dates"]) == 1
        assert "20240101T000000Z" in fields["dates"]

        # MARS metadata captures non-coordinate, non-leaf axes
        # Note: the root node's own axis is not visited (walk_tree processes children).
        # "number" and "step" are captured from interior nodes.
        assert mars_metadata.get("number") == 1
        assert "Forecast date" in mars_metadata

        # Coords should have the composite points
        date_key = "20240101T000000Z"
        assert date_key in coords
        assert len(coords[date_key]["composite"]) == 1
        assert coords[date_key]["composite"][0] == [51.5, -0.1]

        # range_dict should have 2 params × 3 steps = 6 keys
        assert len(range_dict) == 6
        # Check one entry
        key = ("20240101T000000Z", 0, 1, 167, 0)
        assert key in range_dict
        assert range_dict[key] == [293.5]

    def test_multipoint_walk(self):
        tree = _build_multipoint_tree()
        enc = TensogramEncoder({"param_db": "ecmwf"}, "boundingbox")

        fields = {
            "lat": 0,
            "param": [],
            "number": [0],
            "step": [0],
            "dates": [],
            "levels": [0],
        }
        coords = {}
        mars_metadata = {}
        range_dict = {}

        enc.walk_tree(tree, fields, coords, mars_metadata, range_dict)

        assert fields["param"] == [167]
        assert fields["step"] == [0]

        date_key = "20240101T000000Z"
        composite = coords[date_key]["composite"]
        assert len(composite) == 3  # 3 longitude points
        assert composite[0] == [50.0, -1.0]
        assert composite[2] == [50.0, 1.0]

        # One range_dict entry: (date, level=0, number=1, param=167, step=0)
        key = ("20240101T000000Z", 0, 1, 167, 0)
        assert key in range_dict
        assert range_dict[key] == [290.0, 291.0, 292.0]

    def test_verticalprofile_walk(self):
        tree = _build_verticalprofile_tree()
        enc = TensogramEncoder({"param_db": "ecmwf"}, "verticalprofile")

        fields = {
            "lat": 0,
            "param": [],
            "number": [0],
            "step": [0],
            "dates": [],
            "levels": [0],
        }
        coords = {}
        mars_metadata = {}
        range_dict = {}

        enc.walk_tree(tree, fields, coords, mars_metadata, range_dict)

        assert fields["levels"] == [1000, 500]
        assert fields["param"] == [167]

        # Two range_dict entries: one per level
        key1 = ("20240101T000000Z", 1000, 1, 167, 0)
        key2 = ("20240101T000000Z", 500, 1, 167, 0)
        assert key1 in range_dict
        assert key2 in range_dict
        assert range_dict[key1] == [293.5]
        assert range_dict[key2] == [250.0]

    def test_all_none_leaf_skipped(self):
        """A leaf with all-None result should not populate range_dict."""
        leaf = MockTree("longitude", [-0.1], result=[None, None])
        lat = MockTree("latitude", [51.5], children=[leaf])
        param = MockTree("param", [167], children=[lat])
        step = MockTree("step", [0, 1], children=[param])
        number = MockTree("number", [1], children=[step])
        date = MockTree("date", ["20240101T000000"], children=[number])
        root = MockTree("class", ["od"], children=[date])

        enc = TensogramEncoder({"param_db": "ecmwf"}, "timeseries")
        fields = {
            "lat": 0,
            "param": [],
            "number": [0],
            "step": [0],
            "dates": [],
            "levels": [0],
        }
        coords = {}
        mars_metadata = {}
        range_dict = {}

        enc.walk_tree(root, fields, coords, mars_metadata, range_dict)
        assert len(range_dict) == 0


# ===================================================================
# Tests: TensogramEncoder — message building (requires tensogram)
# ===================================================================

try:
    import tensogram

    HAS_TENSOGRAM = True
except ImportError:
    HAS_TENSOGRAM = False


@pytest.mark.skipif(not HAS_TENSOGRAM, reason="tensogram not installed")
class TestTensogramEncoding:
    """End-to-end: walk tree → encode → decode → verify."""

    def test_timeseries_roundtrip(self):
        tree = _build_simple_timeseries_tree()
        enc = TensogramEncoder({"param_db": "ecmwf"}, "timeseries")
        result = enc.from_polytope(tree)

        assert len(result) >= 1

        # Decode the first (and should be only) message
        msg = result.messages[0]
        meta, objects = tensogram.decode(msg)

        # Check metadata
        assert meta.version == 2
        assert meta.extra["source"] == "polytope-mars"
        assert meta.extra["feature_type"] == "timeseries"
        assert meta.extra["domain_type"] == "PointSeries"
        assert "mars" in meta.extra
        assert meta.extra["mars"]["number"] == 1
        assert "Forecast date" in meta.extra["mars"]
        assert "time_values" in meta.extra

        # Check base entries
        assert len(meta.base) == len(objects)
        # First two should be coordinate objects (lat, lon)
        assert meta.base[0]["name"] == "latitude"
        assert meta.base[0]["role"] == "coordinate"
        assert meta.base[1]["name"] == "longitude"
        assert meta.base[1]["role"] == "coordinate"

        # Decode coordinate data
        _, lat_arr = objects[0]
        _, lon_arr = objects[1]
        np.testing.assert_allclose(lat_arr, [51.5])
        np.testing.assert_allclose(lon_arr, [-0.1])

        # Step coordinate
        assert meta.base[2]["name"] == "step"
        _, step_arr = objects[2]
        np.testing.assert_allclose(step_arr, [0, 1, 2])

        # Data objects (params) — order may vary, check by name
        data_entries = [(meta.base[i], objects[i]) for i in range(3, len(objects))]
        assert len(data_entries) == 2  # 2 params

        for base_entry, (_, arr) in data_entries:
            assert base_entry["role"] == "data"
            assert "mars" in base_entry
            assert arr.shape == (3,)  # 3 steps

    def test_multipoint_roundtrip(self):
        tree = _build_multipoint_tree()
        enc = TensogramEncoder({"param_db": "ecmwf"}, "boundingbox")
        result = enc.from_polytope(tree)

        assert len(result) >= 1

        msg = result.messages[0]
        meta, objects = tensogram.decode(msg)

        assert meta.extra["domain_type"] == "MultiPoint"
        assert meta.extra["mars"]["step"] == 0

        # Should have lat[3], lon[3], levelist[3], param[3]
        _, lat_arr = objects[0]
        _, lon_arr = objects[1]
        assert lat_arr.shape == (3,)
        assert lon_arr.shape == (3,)
        np.testing.assert_allclose(lat_arr, [50.0, 50.0, 50.0])
        np.testing.assert_allclose(lon_arr, [-1.0, 0.0, 1.0])

        # Data object
        data_idx = None
        for i, entry in enumerate(meta.base):
            if entry.get("role") == "data":
                data_idx = i
                break
        assert data_idx is not None
        _, data_arr = objects[data_idx]
        np.testing.assert_allclose(data_arr, [290.0, 291.0, 292.0])

    def test_verticalprofile_roundtrip(self):
        tree = _build_verticalprofile_tree()
        enc = TensogramEncoder({"param_db": "ecmwf"}, "verticalprofile")
        result = enc.from_polytope(tree)

        assert len(result) >= 1

        msg = result.messages[0]
        meta, objects = tensogram.decode(msg)

        assert meta.extra["domain_type"] == "VerticalProfile"

        # Should have lat[1], lon[1], levelist[2], param_data[2]
        _, lat_arr = objects[0]
        _, lon_arr = objects[1]
        np.testing.assert_allclose(lat_arr, [51.5])
        np.testing.assert_allclose(lon_arr, [-0.1])

        # Levelist coordinate
        lev_idx = None
        for i, entry in enumerate(meta.base):
            if entry.get("name") == "levelist":
                lev_idx = i
                break
        assert lev_idx is not None
        _, lev_arr = objects[lev_idx]
        np.testing.assert_allclose(lev_arr, [1000.0, 500.0])

        # Data values — one per level
        data_idx = None
        for i, entry in enumerate(meta.base):
            if entry.get("role") == "data":
                data_idx = i
                break
        assert data_idx is not None
        _, data_arr = objects[data_idx]
        np.testing.assert_allclose(data_arr, [293.5, 250.0])

    def test_to_file_and_scan(self):
        """Write to file, then scan to verify message count."""
        tree = _build_simple_timeseries_tree()
        enc = TensogramEncoder({"param_db": "ecmwf"}, "timeseries")
        result = enc.from_polytope(tree)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".tgm") as f:
            path = f.name
        try:
            result.to_file(path)
            with open(path, "rb") as f:
                buf = f.read()
            offsets = tensogram.scan(buf)
            assert len(offsets) == len(result)
        finally:
            os.unlink(path)


# ===================================================================
# Tests: helper functions
# ===================================================================


class TestHelpers:
    def test_numpy_dtype_mapping(self):
        assert _numpy_dtype_to_tensogram(np.dtype(np.float32)) == "float32"
        assert _numpy_dtype_to_tensogram(np.dtype(np.float64)) == "float64"
        assert _numpy_dtype_to_tensogram(np.dtype(np.int32)) == "int32"
        assert _numpy_dtype_to_tensogram(np.dtype(np.uint8)) == "uint8"

    def test_numpy_dtype_fallback(self):
        # Unknown dtype should fall back to float64
        assert _numpy_dtype_to_tensogram(np.dtype(np.complex128)) == "float64"

    def test_compute_time_strings(self):
        enc = TensogramEncoder({"param_db": "ecmwf"}, "timeseries")
        times = enc._compute_time_strings("20240101T000000Z", [0, 6, 12], "standard")
        assert len(times) == 3
        assert times[0] == "2024-01-01T00:00:00Z"
        assert times[1] == "2024-01-01T06:00:00Z"
        assert times[2] == "2024-01-01T12:00:00Z"

    def test_compute_time_strings_month(self):
        enc = TensogramEncoder({"param_db": "ecmwf"}, "timeseries")
        times = enc._compute_time_strings("2024-01", [0], "month")
        assert times == ["2024-01"]

    def test_compute_time_strings_unparseable(self):
        enc = TensogramEncoder({"param_db": "ecmwf"}, "timeseries")
        times = enc._compute_time_strings("not-a-date", [0], "standard")
        assert times == ["not-a-date"]


# ===================================================================
# Tests: import guard
# ===================================================================


class TestImportGuard:
    def test_missing_tensogram_gives_clear_error(self, monkeypatch):
        """Simulate tensogram not being installed."""
        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "tensogram":
                raise ImportError("No module named 'tensogram'")
            return real_import(name, *args, **kwargs)

        enc = TensogramEncoder({"param_db": "ecmwf"}, "timeseries")
        enc._tensogram = None  # force re-import

        monkeypatch.setattr(builtins, "__import__", mock_import)
        with pytest.raises(ImportError, match="tensogram.*not installed"):
            enc._import_tensogram()


# ===================================================================
# Tests: format validation in api.py
# ===================================================================

try:
    import pygribjump  # noqa: F401

    HAS_PYGRIBJUMP = True
except ImportError:
    HAS_PYGRIBJUMP = False


@pytest.mark.skipif(not HAS_PYGRIBJUMP, reason="pygribjump not installed")
class TestFormatValidation:
    """These tests import polytope_mars.api which requires pygribjump."""

    def test_invalid_format_raises(self):
        """Constructing a request with an unsupported format should raise."""
        from unittest.mock import MagicMock

        from polytope_mars.api import PolytopeMars

        request = {
            "format": "xml",
            "feature": {"type": "timeseries", "points": [[0, 0]], "time_axis": "step"},
            "class": "od",
            "param": "167",
            "step": "0",
        }

        pm = PolytopeMars.__new__(PolytopeMars)
        pm.log_context = None
        pm.id = "-1"
        pm.conf = MagicMock()
        pm.conf.polygonrules.max_area = float("inf")
        pm.coverage = {}
        pm.split_request = False

        with pytest.raises(ValueError, match="Unsupported format"):
            pm.extract(request)

    def test_covjson_format_accepted(self):
        """format='covjson' should not raise a format error."""
        from unittest.mock import MagicMock

        from polytope_mars.api import PolytopeMars

        request = {
            "format": "covjson",
            "feature": {"type": "timeseries", "points": [[0, 0]], "time_axis": "step"},
            "class": "od",
            "param": "167",
            "step": "0",
        }

        pm = PolytopeMars.__new__(PolytopeMars)
        pm.log_context = None
        pm.id = "-1"
        pm.conf = MagicMock()
        pm.conf.polygonrules.max_area = float("inf")
        pm.coverage = {}
        pm.split_request = False

        # This should get past format validation and fail later
        try:
            pm.extract(request)
        except (ValueError, KeyError, AttributeError, TypeError, NotImplementedError):
            pass
        assert pm.format == "covjson"

    def test_tensogram_format_accepted(self):
        """format='tensogram' should not raise a format error."""
        from unittest.mock import MagicMock

        from polytope_mars.api import PolytopeMars

        request = {
            "format": "tensogram",
            "feature": {"type": "timeseries", "points": [[0, 0]], "time_axis": "step"},
            "class": "od",
            "param": "167",
            "step": "0",
        }

        pm = PolytopeMars.__new__(PolytopeMars)
        pm.log_context = None
        pm.id = "-1"
        pm.conf = MagicMock()
        pm.conf.polygonrules.max_area = float("inf")
        pm.coverage = {}
        pm.split_request = False

        try:
            pm.extract(request)
        except (
            ValueError,
            KeyError,
            AttributeError,
            TypeError,
            NotImplementedError,
            ImportError,
        ):
            pass
        assert pm.format == "tensogram"
