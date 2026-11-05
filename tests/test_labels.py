"""Tests for the optional 'labels' field in the timeseries feature dictionary."""

import copy
from datetime import datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest
from conflator import Conflator
from polytope_feature import shapes
from polytope_feature.polytope import Polytope, Request

import polytope_mars.api as pm_api
from polytope_mars.api import PolytopeMars
from polytope_mars.config import PolytopeMarsConfig


class TestLabelsValidation:
    """Unit tests for labels parsing and validation (no data retrieval)."""

    def setup_method(self):
        today = datetime.today()
        yesterday = today - timedelta(days=1)
        self.date = yesterday.strftime("%Y%m%d")

        self.request = {
            "class": "od",
            "stream": "enfo",
            "type": "pf",
            "date": self.date,
            "time": "0000",
            "levtype": "sfc",
            "expver": "0001",
            "domain": "g",
            "param": "167",
            "number": "1",
            "feature": {
                "type": "timeseries",
                "points": [[-9.10, 38.78], [51.5, 6.5]],
                "labels": ["Lisbon", "Dusseldorf"],
                "time_axis": "step",
                "axes": ["latitude", "longitude"],
                "range": {"start": 0, "end": 3},
            },
        }

        self.options = {
            "axis_config": [
                {
                    "axis_name": "date",
                    "transformations": [{"name": "merge", "other_axis": "time", "linkers": ["T", "00"]}],
                },
                {
                    "axis_name": "values",
                    "transformations": [
                        {
                            "name": "mapper",
                            "type": "octahedral",
                            "resolution": 1280,
                            "axes": ["latitude", "longitude"],
                        }
                    ],
                },
                {"axis_name": "levelist", "transformations": [{"name": "type_change", "type": "str"}]},
                {"axis_name": "latitude", "transformations": [{"name": "reverse", "is_reverse": True}]},
                {"axis_name": "longitude", "transformations": [{"name": "cyclic", "range": [0, 360]}]},
                {"axis_name": "step", "transformations": [{"name": "type_change", "type": "int"}]},
                {"axis_name": "number", "transformations": [{"name": "type_change", "type": "int"}]},
            ],
            "compressed_axes_config": [
                "longitude",
                "latitude",
                "levtype",
                "step",
                "date",
                "domain",
                "expver",
                "param",
                "class",
                "stream",
                "type",
                "number",
            ],
            "pre_path": {
                "class": "od",
                "expver": "0001",
                "levtype": "sfc",
                "stream": "enfo",
                "type": "pf",
                "domain": "g",
            },
        }

        conf = Conflator(app_name="polytope_mars", model=PolytopeMarsConfig).load()
        self.cf = conf.model_dump()
        self.cf["options"] = self.options

    def _build_request_shapes(self, request):
        """Build the polytope Request from a polytope-mars request dict (without data retrieval)."""
        pm = PolytopeMars(self.cf)
        request = copy.deepcopy(request)
        feature_config = request.pop("feature")
        feature_config_copy = feature_config.copy()
        feature_type = feature_config["type"]

        # Replicate the time_axis pre-processing from api.py
        if feature_type == "timeseries":
            if "axes" in feature_config:
                if feature_config["axes"] == "step":
                    del feature_config["axes"]
                    del feature_config_copy["axes"]
                    feature_config["time_axis"] = "step"
                    feature_config_copy["time_axis"] = "step"

        feature = pm._feature_factory(feature_type, feature_config, pm.conf)
        feature.validate(request, feature_config_copy)
        request = feature.parse(request, feature_config_copy)
        s = pm._create_base_shapes(request, feature_type)
        s.extend(feature.get_shapes())
        return Request(*s), feature

    # -- Basic acceptance tests --

    def test_labels_accepted_in_feature_config(self):
        """Labels field is accepted without error when count matches points."""
        preq, feature = self._build_request_shapes(self.request)
        assert feature.labels == ["Lisbon", "Dusseldorf"]

    def test_labels_none_when_not_provided(self):
        """When labels is omitted, feature.labels is None."""
        request = copy.deepcopy(self.request)
        del request["feature"]["labels"]
        preq, feature = self._build_request_shapes(request)
        assert feature.labels is None

    def test_labels_single_point(self):
        """Labels works with a single point."""
        request = copy.deepcopy(self.request)
        request["feature"]["points"] = [[48.0, 11.0]]
        request["feature"]["labels"] = ["Munich"]
        preq, feature = self._build_request_shapes(request)
        assert feature.labels == ["Munich"]

    def test_labels_many_points(self):
        """Labels works with many points."""
        request = copy.deepcopy(self.request)
        points = [[-9.10, 38.78], [51.5, 6.5], [48.0, 11.0], [40.4, -3.7]]
        labels = ["Lisbon", "Dusseldorf", "Munich", "Madrid"]
        request["feature"]["points"] = points
        request["feature"]["labels"] = labels
        preq, feature = self._build_request_shapes(request)
        assert feature.labels == labels

    # -- Validation error tests --

    def test_labels_mismatch_too_few(self):
        """Raises ValueError when fewer labels than points."""
        request = copy.deepcopy(self.request)
        request["feature"]["labels"] = ["Lisbon"]  # only 1, but 2 points
        with pytest.raises(ValueError, match="Number of labels"):
            self._build_request_shapes(request)

    def test_labels_mismatch_too_many(self):
        """Raises ValueError when more labels than points."""
        request = copy.deepcopy(self.request)
        request["feature"]["labels"] = ["Lisbon", "Dusseldorf", "Munich"]  # 3, but 2 points
        with pytest.raises(ValueError, match="Number of labels"):
            self._build_request_shapes(request)

    def test_labels_empty_list_with_points(self):
        """Raises ValueError when labels is empty but points exist."""
        request = copy.deepcopy(self.request)
        request["feature"]["labels"] = []
        with pytest.raises(ValueError, match="Number of labels"):
            self._build_request_shapes(request)

    # -- Shape construction tests --

    @staticmethod
    def _point_shapes(preq):
        """The single-point Point shapes inside the lat/lon Union built by the timeseries feature."""
        union = next(s for s in preq.shapes if isinstance(s, shapes.Union))
        return list(union._shapes)

    def _tags(self, preq):
        return [p.tag for p in self._point_shapes(preq)]

    def test_labels_passed_as_tag_to_point_shapes(self):
        """Each point is its own nearest-neighbour Point, tagged (index, label)."""
        request = copy.deepcopy(self.request)
        preq, feature = self._build_request_shapes(request)
        points = self._point_shapes(preq)
        assert [p.values for p in points] == [[[-9.10, 38.78]], [[51.5, 6.5]]]
        assert all(p.method == "nearest" for p in points)
        assert self._tags(preq) == [(0, "Lisbon"), (1, "Dusseldorf")]

    def test_no_labels_tags_with_index_only(self):
        """When labels is not provided, points are still tagged with (index, None)."""
        request = copy.deepcopy(self.request)
        del request["feature"]["labels"]
        preq, feature = self._build_request_shapes(request)
        assert self._tags(preq) == [(0, None), (1, None)]

    def test_single_point_tag(self):
        request = copy.deepcopy(self.request)
        request["feature"]["points"] = [[48.0, 11.0]]
        request["feature"]["labels"] = ["Munich"]
        preq, feature = self._build_request_shapes(request)
        assert self._tags(preq) == [(0, "Munich")]

    def test_labels_with_swapped_axes(self):
        """Labels work correctly when axes are [longitude, latitude]."""
        request = copy.deepcopy(self.request)
        request["feature"]["axes"] = ["longitude", "latitude"]
        request["feature"]["points"] = [[38.78, -9.10], [6.5, 51.5]]
        request["feature"]["labels"] = ["Lisbon", "Dusseldorf"]
        preq, feature = self._build_request_shapes(request)
        assert all(p.axes() == ["longitude", "latitude"] for p in self._point_shapes(preq))
        assert self._tags(preq) == [(0, "Lisbon"), (1, "Dusseldorf")]

    def test_labels_numeric_values(self):
        """Labels can be numeric (e.g. station IDs)."""
        request = copy.deepcopy(self.request)
        request["feature"]["labels"] = [12345, 67890]
        preq, feature = self._build_request_shapes(request)
        assert self._tags(preq) == [(0, 12345), (1, 67890)]

    def test_labels_not_allowed_without_points(self):
        """If points is empty but labels is provided, validation fails."""
        request = copy.deepcopy(self.request)
        request["feature"]["points"] = []
        request["feature"]["labels"] = ["Lisbon"]
        # This should fail because points is empty but labels has values
        # The parse step will fail because points[0] doesn't exist
        with pytest.raises((ValueError, IndexError)):
            self._build_request_shapes(request)

    def test_labels_duplicate_values_allowed(self):
        """The same label may be used for more than one point; tags stay unique by index."""
        request = copy.deepcopy(self.request)
        request["feature"]["labels"] = ["Airport", "Airport"]
        preq, feature = self._build_request_shapes(request)
        assert self._tags(preq) == [(0, "Airport"), (1, "Airport")]

    def test_per_point_tags_reach_result_tree(self):
        """Every requested point's tag reaches the tree; points snapping to one grid point keep both tags."""
        gj = pytest.importorskip("pygribjump")
        request = copy.deepcopy(self.request)
        request["feature"]["points"] = [[38.78, -9.10], [38.781, -9.101], [51.5, 6.5]]
        request["feature"]["labels"] = ["Lisbon_A", "Lisbon_B", "Dusseldorf"]
        preq, _ = self._build_request_shapes(request)
        try:
            result = Polytope(datacube=gj.GribJump(), options=self.cf["options"]).retrieve(preq)
        except Exception as e:
            if "gribjump" in str(e).lower() or "fdb" in str(e).lower():
                pytest.skip("GribJump/FDB not available for integration test")
            raise

        tag_sets = set()

        def walk(node):
            if node.axis.name == "longitude":
                tag_sets.add(frozenset(node.tags))
            for child in node.children:
                walk(child)

        walk(result)
        assert frozenset({(0, "Lisbon_A"), (1, "Lisbon_B")}) in tag_sets
        assert frozenset({(2, "Dusseldorf")}) in tag_sets

    def test_labels_must_be_list(self):
        """Raises ValueError when labels is not a list."""
        request = copy.deepcopy(self.request)
        request["feature"]["labels"] = "Lisbon"
        with pytest.raises(ValueError, match="must be a list"):
            self._build_request_shapes(request)

    @pytest.mark.parametrize("bad_label", [None, ["a"], {"a": 1}, 1.5, True])
    def test_labels_invalid_type(self, bad_label):
        """Raises ValueError when a label is not a string or integer."""
        request = copy.deepcopy(self.request)
        request["feature"]["labels"] = ["Lisbon", bad_label]
        with pytest.raises(ValueError, match="strings or integers"):
            self._build_request_shapes(request)


COVJSONKIT_LABELS_XFAIL = pytest.mark.xfail(
    reason="covjsonkit does not yet read (index, label) tags into labelled/duplicated coverages", strict=False
)


class TestLabelsIntegration:
    """Integration tests that verify the full extract pipeline accepts labels.

    These tests use the PolytopeMars API but may skip actual data retrieval
    if gribjump is not available.
    """

    def setup_method(self):
        today = datetime.today()
        yesterday = today - timedelta(days=1)
        self.date = yesterday.strftime("%Y%m%d")

        self.options = {
            "axis_config": [
                {
                    "axis_name": "date",
                    "transformations": [{"name": "merge", "other_axis": "time", "linkers": ["T", "00"]}],
                },
                {
                    "axis_name": "values",
                    "transformations": [
                        {
                            "name": "mapper",
                            "type": "octahedral",
                            "resolution": 1280,
                            "axes": ["latitude", "longitude"],
                        }
                    ],
                },
                {"axis_name": "levelist", "transformations": [{"name": "type_change", "type": "str"}]},
                {"axis_name": "latitude", "transformations": [{"name": "reverse", "is_reverse": True}]},
                {"axis_name": "longitude", "transformations": [{"name": "cyclic", "range": [0, 360]}]},
                {"axis_name": "step", "transformations": [{"name": "type_change", "type": "int"}]},
                {"axis_name": "number", "transformations": [{"name": "type_change", "type": "int"}]},
            ],
            "compressed_axes_config": [
                "longitude",
                "latitude",
                "levtype",
                "step",
                "date",
                "domain",
                "expver",
                "param",
                "class",
                "stream",
                "type",
                "number",
            ],
            "pre_path": {
                "class": "od",
                "expver": "0001",
                "levtype": "sfc",
                "stream": "enfo",
                "type": "pf",
                "domain": "g",
            },
        }

        conf = Conflator(app_name="polytope_mars", model=PolytopeMarsConfig).load()
        self.cf = conf.model_dump()
        self.cf["options"] = self.options

    def test_extract_with_labels(self):
        """Full extract pipeline accepts labels without error."""
        request = {
            "class": "od",
            "stream": "enfo",
            "type": "pf",
            "date": self.date,
            "time": "0000",
            "levtype": "sfc",
            "expver": "0001",
            "domain": "g",
            "param": "167",
            "number": "1",
            "feature": {
                "type": "timeseries",
                "points": [[-9.10, 38.78], [51.5, 6.5]],
                "labels": ["Lisbon", "Dusseldorf"],
                "time_axis": "step",
                "axes": ["latitude", "longitude"],
                "range": {"start": 0, "end": 3},
            },
        }
        try:
            result = PolytopeMars(self.cf).extract(request)
            assert result is not None
        except Exception as e:
            # If gribjump/FDB is not available, the test should not fail on that
            if "GribJump" in str(type(e).__name__) or "fdb" in str(e).lower() or "gribjump" in str(e).lower():
                pytest.skip("GribJump/FDB not available for integration test")
            raise

    def test_extract_without_labels_still_works(self):
        """Full extract pipeline still works when labels is not provided."""
        request = {
            "class": "od",
            "stream": "enfo",
            "type": "pf",
            "date": self.date,
            "time": "0000",
            "levtype": "sfc",
            "expver": "0001",
            "domain": "g",
            "param": "167",
            "number": "1",
            "feature": {
                "type": "timeseries",
                "points": [[-9.10, 38.78]],
                "time_axis": "step",
                "axes": ["latitude", "longitude"],
                "range": {"start": 0, "end": 3},
            },
        }
        try:
            result = PolytopeMars(self.cf).extract(request)
            assert result is not None
        except Exception as e:
            if "GribJump" in str(type(e).__name__) or "fdb" in str(e).lower() or "gribjump" in str(e).lower():
                pytest.skip("GribJump/FDB not available for integration test")
            raise

    @COVJSONKIT_LABELS_XFAIL
    def test_merged_points_duplicate_coverages(self):
        """When two points snap to the same grid cell, each label gets its own coverage."""
        request = {
            "class": "od",
            "stream": "enfo",
            "type": "pf",
            "date": self.date,
            "time": "0000",
            "levtype": "sfc",
            "expver": "0001",
            "domain": "g",
            "param": "167",
            "number": "1",
            "feature": {
                "type": "timeseries",
                # Two points very close together (snap to same grid point) + one distinct
                "points": [[-9.10, 38.78], [-9.11, 38.79], [51.5, 6.5]],
                "labels": ["Lisbon_StationA", "Lisbon_StationB", "Dusseldorf"],
                "time_axis": "step",
                "axes": ["latitude", "longitude"],
                "range": {"start": 0, "end": 3},
            },
        }
        try:
            result = PolytopeMars(self.cf).extract(request)
        except Exception as e:
            if "GribJump" in str(type(e).__name__) or "fdb" in str(e).lower() or "gribjump" in str(e).lower():
                pytest.skip("GribJump/FDB not available for integration test")
            raise

        coverages = result["coverages"]

        # Should get 3 coverages even though only 2 unique grid points
        assert len(coverages) == 3

        # Collect labels from all coverages
        labels = [c["mars:metadata"]["label"] for c in coverages]
        assert "Lisbon_StationA" in labels
        assert "Lisbon_StationB" in labels
        assert "Dusseldorf" in labels

    @COVJSONKIT_LABELS_XFAIL
    def test_merged_points_same_data(self):
        """Coverages for merged points have identical data values."""
        request = {
            "class": "od",
            "stream": "enfo",
            "type": "pf",
            "date": self.date,
            "time": "0000",
            "levtype": "sfc",
            "expver": "0001",
            "domain": "g",
            "param": "167",
            "number": "1",
            "feature": {
                "type": "timeseries",
                # Two points that will snap to the same grid point
                "points": [[-9.10, 38.78], [-9.11, 38.79]],
                "labels": ["StationA", "StationB"],
                "time_axis": "step",
                "axes": ["latitude", "longitude"],
                "range": {"start": 0, "end": 3},
            },
        }
        try:
            result = PolytopeMars(self.cf).extract(request)
        except Exception as e:
            if "GribJump" in str(type(e).__name__) or "fdb" in str(e).lower() or "gribjump" in str(e).lower():
                pytest.skip("GribJump/FDB not available for integration test")
            raise

        coverages = result["coverages"]
        assert len(coverages) == 2

        # Both coverages should have the same coordinates (same grid point)
        lat_a = coverages[0]["domain"]["axes"]["latitude"]["values"]
        lat_b = coverages[1]["domain"]["axes"]["latitude"]["values"]
        lon_a = coverages[0]["domain"]["axes"]["longitude"]["values"]
        lon_b = coverages[1]["domain"]["axes"]["longitude"]["values"]
        assert lat_a == lat_b
        assert lon_a == lon_b

        # Both coverages should have identical data values
        param_key = list(coverages[0]["ranges"].keys())[0]
        values_a = coverages[0]["ranges"][param_key]["values"]
        values_b = coverages[1]["ranges"][param_key]["values"]
        assert values_a == values_b

        # But different labels
        id_a = coverages[0]["mars:metadata"]["label"]
        id_b = coverages[1]["mars:metadata"]["label"]
        assert id_a != id_b
        assert {id_a, id_b} == {"StationA", "StationB"}

    @COVJSONKIT_LABELS_XFAIL
    def test_merged_points_no_labels(self):
        """Without labels, merged points are still returned once per requested point."""
        request = {
            "class": "od",
            "stream": "enfo",
            "type": "pf",
            "date": self.date,
            "time": "0000",
            "levtype": "sfc",
            "expver": "0001",
            "domain": "g",
            "param": "167",
            "number": "1",
            "feature": {
                "type": "timeseries",
                # Two points that snap to same grid point, no labels
                "points": [[-9.10, 38.78], [-9.11, 38.79]],
                "time_axis": "step",
                "axes": ["latitude", "longitude"],
                "range": {"start": 0, "end": 3},
            },
        }
        try:
            result = PolytopeMars(self.cf).extract(request)
        except Exception as e:
            if "GribJump" in str(type(e).__name__) or "fdb" in str(e).lower() or "gribjump" in str(e).lower():
                pytest.skip("GribJump/FDB not available for integration test")
            raise

        coverages = result["coverages"]
        # The number of points returned always matches the number requested
        assert len(coverages) == 2
        for c in coverages:
            assert "label" not in c["mars:metadata"]


# -- Longitude compression guard --
#
# Polytope stamps a tag on a tree node, not on a value. A compressed longitude node holds several
# cells, so the cells of different requested points could end up sharing one combined tag set and
# labels could not be assigned per cell. Point features therefore drop "longitude" from the
# compressed axes (Feature.uncompressed_axes, applied in PolytopeMars.retrieve_data).

_COMMON_REQUEST = {
    "class": "od",
    "stream": "enfo",
    "type": "pf",
    "time": "0000",
    "expver": "0001",
    "domain": "g",
    "number": "1",
}


def _guard_request(feature_name, labelled=True):
    """A minimal valid request for ``feature_name`` (point features and, as controls, area features)."""
    date = (datetime.today() - timedelta(days=1)).strftime("%Y%m%d")
    points = [[-9.10, 38.78], [-9.11, 38.79]]
    labels = {"labels": ["A", "B"]} if labelled else {}
    if feature_name == "timeseries":
        extra = {
            "levtype": "sfc",
            "param": "167",
            "feature": {
                "type": "timeseries",
                "points": points,
                "time_axis": "step",
                "axes": ["latitude", "longitude"],
                "range": {"start": 0, "end": 3},
                **labels,
            },
        }
    elif feature_name == "position":
        extra = {
            "levtype": "sfc",
            "param": "167",
            "step": "0",
            "feature": {"type": "position", "points": points, **labels},
        }
    elif feature_name == "verticalprofile":
        extra = {
            "levtype": "pl",
            "param": "203/133",
            "step": "0",
            "levelist": "0/to/1000",
            "feature": {"type": "verticalprofile", "points": points, "axes": "levelist", **labels},
        }
    elif feature_name == "polygon":
        extra = {
            "levtype": "sfc",
            "param": "167",
            "step": "0",
            "feature": {
                "type": "polygon",
                "shape": [[40.0, -105.0], [40.0, -104.0], [41.0, -104.0], [41.0, -105.0], [40.0, -105.0]],
            },
        }
    elif feature_name == "boundingbox":
        extra = {
            "levtype": "sfc",
            "param": "167",
            "step": "0",
            "feature": {"type": "boundingbox", "points": [[0, 0], [1, 1]]},
        }
    else:
        raise ValueError(feature_name)
    return {**_COMMON_REQUEST, "date": date, **extra}


class _StopRetrieve(Exception):
    """Raised by the fake Polytope to end ``extract`` right after the Polytope options were built."""


def _options_given_to_polytope(monkeypatch, cf, request):
    """Run ``PolytopeMars.extract`` with Polytope/GribJump stubbed; return the options Polytope was built with."""
    captured = {}

    class FakePolytope:
        def __init__(self, datacube, options, context=None):
            captured["options"] = options

        def retrieve(self, preq):
            raise _StopRetrieve

    monkeypatch.setattr(pm_api, "Polytope", FakePolytope)
    monkeypatch.setattr(pm_api, "gj", SimpleNamespace(GribJump=lambda: object()))
    with pytest.raises(_StopRetrieve):
        PolytopeMars(cf).extract(request)
    return captured["options"]


class TestLongitudeCompressionGuard:
    """Point features must not compress longitude; no FDB needed (Polytope is stubbed)."""

    @pytest.fixture
    def cf(self):
        validation = TestLabelsValidation()
        validation.setup_method()
        return validation.cf

    @pytest.mark.parametrize("feature_name", ["timeseries", "position", "verticalprofile"])
    @pytest.mark.parametrize("labelled", [True, False])
    def test_point_features_drop_longitude_from_compressed_axes(self, monkeypatch, cf, feature_name, labelled):
        configured = list(cf["options"]["compressed_axes_config"])
        assert "longitude" in configured  # the shared config does compress longitude

        options = _options_given_to_polytope(monkeypatch, cf, _guard_request(feature_name, labelled))

        assert "longitude" not in options["compressed_axes_config"]
        # Only longitude is removed, every other compressed axis (incl. latitude) is kept
        assert options["compressed_axes_config"] == [a for a in configured if a != "longitude"]

    @pytest.mark.parametrize("feature_name", ["polygon", "boundingbox"])
    def test_area_features_keep_longitude_compressed(self, monkeypatch, cf, feature_name):
        configured = list(cf["options"]["compressed_axes_config"])
        options = _options_given_to_polytope(monkeypatch, cf, _guard_request(feature_name))
        assert options["compressed_axes_config"] == configured

    def test_shared_config_is_not_modified(self, monkeypatch, cf):
        """The per-request copy is changed, never the configuration shared between requests."""
        pm = PolytopeMars(cf)
        monkeypatch.setattr(pm_api, "Polytope", lambda **kw: SimpleNamespace(retrieve=_raise_stop))
        monkeypatch.setattr(pm_api, "gj", SimpleNamespace(GribJump=lambda: object()))
        for _ in range(2):  # a second request must see the same, unmodified config
            with pytest.raises(_StopRetrieve):
                pm.extract(_guard_request("timeseries"))
        assert "longitude" in pm.conf.options.compressed_axes_config

    @pytest.mark.parametrize("feature_name", ["timeseries", "position", "verticalprofile"])
    def test_feature_hook(self, cf, feature_name):
        pm = PolytopeMars(cf)
        feature_config = _guard_request(feature_name)["feature"]
        assert pm._feature_factory(feature_name, feature_config, pm.conf).uncompressed_axes() == ["longitude"]

    @pytest.mark.parametrize("feature_name", ["polygon", "boundingbox"])
    def test_feature_hook_default_is_empty(self, cf, feature_name):
        pm = PolytopeMars(cf)
        feature_config = _guard_request(feature_name)["feature"]
        assert pm._feature_factory(feature_name, feature_config, pm.conf).uncompressed_axes() == []


def _raise_stop(preq):
    raise _StopRetrieve


# -- In-memory polytope pipeline (no FDB) --
#
# Real Polytope slicing and tag stamping on a small in-memory octahedral grid (xarray backend), then the
# covjsonkit encoder. Two things differ from production and are emulated:
#   * the xarray backend has no nearest-neighbour search (it is implemented in the FDB backend only), so
#     nearest queries run the FDB backend's own ``nearest_lat_lon_search`` on the sliced tree;
#   * leaf values are synthetic (``lon + 1000 * step_index``) so each cell/step is recognisable.

OCTAHEDRAL_N = 80
# Grid cells of an O80 grid (latitude row 47.66 has two cells at lon 10.71 and 12.86, row 48.78 has lon 10.98)
CELL_1 = (47.663246264843, 10.714285714286)
CELL_2 = (47.663246264843, 12.857142857143)
CELL_3 = (48.784729330535, 10.975609756098)


def _in_memory_tree(feature, compressed_axes, nearest):
    """Slice the feature's shapes on an in-memory O80 grid; returns the polytope result tree."""
    xr = pytest.importorskip("xarray")
    from polytope_feature.datacube.backends.fdb import FDBDatacube

    n_cells = sum(4 * i + 16 for i in range(1, OCTAHEDRAL_N + 1)) * 2
    steps = [0, 6]
    data = xr.DataArray(
        np.zeros((len(steps), n_cells)),
        dims=("step", "values"),
        coords={
            "step": steps,
            "values": np.arange(n_cells),
            "latitude": ("values", np.zeros(n_cells)),
            "longitude": ("values", np.zeros(n_cells)),
        },
        name="2t",
    )
    options = {
        "axis_config": [
            {
                "axis_name": "values",
                "transformations": [
                    {
                        "name": "mapper",
                        "type": "octahedral",
                        "resolution": OCTAHEDRAL_N,
                        "axes": ["latitude", "longitude"],
                    }
                ],
            },
            {"axis_name": "latitude", "transformations": [{"name": "reverse", "is_reverse": True}]},
            {"axis_name": "longitude", "transformations": [{"name": "cyclic", "range": [0, 360]}]},
        ],
        "compressed_axes_config": compressed_axes,
    }
    api = Polytope(datacube=data, options=options)
    (union,) = feature.get_shapes()
    if not nearest:
        # Exact grid cells: no nearest-neighbour search needed
        for point in union._shapes:
            point.method = None
    tree = api.retrieve(Request(shapes.Select("step", [0, 6]), union))
    if nearest:
        stub = SimpleNamespace(
            nearest_search=api.datacube.nearest_search, grid_transformation=SimpleNamespace(is_irregular=False)
        )
        FDBDatacube.nearest_lat_lon_search(stub, tree.children[0])
    return tree


def _encode_in_memory_tree(tree):
    """Put the polytope tree under the MARS axes the encoder expects, fill synthetic values, encode."""
    from covjsonkit.api import Covjsonkit
    from polytope_feature.datacube.datacube_axis import IntDatacubeAxis
    from polytope_feature.datacube.tensor_index_tree import TensorIndexTree

    def node(name, values):
        axis = IntDatacubeAxis()
        axis.name = name
        return TensorIndexTree(axis=axis, values=tuple(values))

    top = node("class", ("od",))
    parent = top
    for name, values in [
        ("date", (np.datetime64("2025-01-01T00:00:00"),)),
        ("domain", ("g",)),
        ("expver", ("0001",)),
        ("levtype", ("sfc",)),
        ("param", ("167",)),
        ("stream", ("oper",)),
        ("type", ("fc",)),
    ]:
        child = node(name, values)
        parent.add_child(child)
        parent = child
    step_node = tree.children[0]
    parent.add_child(step_node)

    def fill(n):
        if not n.children and n.axis.name == "longitude":
            n.result = [float(lon) + 1000 * s for s in range(2) for lon in n.values]
        for child in n.children:
            fill(child)

    fill(step_node)
    root = TensorIndexTree()
    root.add_child(top)
    return Covjsonkit().encode("CoverageCollection", "timeseries").from_polytope(root)


def _coverage_summary(covjson):
    """(label, lat, lon, values) per coverage."""
    return [
        (
            c["mars:metadata"].get("label"),
            c["domain"]["axes"]["y"]["values"][0],
            c["domain"]["axes"]["x"]["values"][0],
            list(c["ranges"].values())[0]["values"],
        )
        for c in covjson["coverages"]
    ]


class TestInMemoryPipeline:
    """Slice -> tag -> encode on an in-memory grid, with the compressed axes the API would use."""

    @pytest.fixture
    def validation(self):
        validation = TestLabelsValidation()
        validation.setup_method()
        return validation

    def _feature(self, validation, points, labels):
        request = copy.deepcopy(validation.request)
        request["feature"]["points"] = [list(p) for p in points]
        if labels is None:
            del request["feature"]["labels"]
        else:
            request["feature"]["labels"] = labels
        return validation._build_request_shapes(request)[1]

    def _run(self, validation, points, labels, nearest):
        feature = self._feature(validation, points, labels)
        # Same rule as PolytopeMars.retrieve_data: the feature decides which axes stay uncompressed
        compressed = [a for a in ["step", "latitude", "longitude"] if a not in feature.uncompressed_axes()]
        tree = _in_memory_tree(feature, compressed, nearest)
        return tree, _encode_in_memory_tree(tree)

    @staticmethod
    def _leaf_tags(tree):
        found = {}

        def walk(n):
            if n.axis.name == "longitude":
                found[(n.parent.values[0], n.values)] = n.tags
            for child in n.children:
                walk(child)

        walk(tree)
        return found

    def test_exact_cells_each_label_gets_its_own_coverage(self, validation):
        """Two labels on one cell, one on its row neighbour, one on another row: 4 coverages in request order."""
        points = [CELL_1, CELL_2, CELL_1, CELL_3]
        tree, covjson = self._run(validation, points, ["A", "B", "C", "D"], nearest=False)

        leaf_tags = self._leaf_tags(tree)
        assert leaf_tags[(CELL_1[0], (CELL_1[1],))] == {(0, "A"), (2, "C")}
        assert leaf_tags[(CELL_2[0], (CELL_2[1],))] == {(1, "B")}
        assert leaf_tags[(CELL_3[0], (CELL_3[1],))] == {(3, "D")}

        summary = _coverage_summary(covjson)
        assert [s[0] for s in summary] == ["A", "B", "C", "D"]
        for (_, lat, lon, values), (want_lat, want_lon) in zip(summary, points):
            assert (lat, lon) == pytest.approx((want_lat, want_lon))
            assert values == pytest.approx([want_lon, want_lon + 1000])
        assert summary[0][1:] == summary[2][1:]  # same cell: same coordinates and data, own label

    def test_exact_cells_unlabelled_still_one_coverage_per_point(self, validation):
        _, covjson = self._run(validation, [CELL_1, CELL_1, CELL_2], None, nearest=False)
        summary = _coverage_summary(covjson)
        assert [s[0] for s in summary] == [None, None, None]
        assert [s[2] for s in summary] == pytest.approx([CELL_1[1], CELL_1[1], CELL_2[1]])
        assert all("label" not in c["mars:metadata"] for c in covjson["coverages"])

    def test_nearest_points_snapping_to_one_cell_keep_their_labels(self, validation):
        """Requested points that snap to the same cell (and a distant one) keep one coverage and label each."""
        points = [(48.0, 11.0), (48.0, 11.2), (50.0, 11.3)]
        _, covjson = self._run(validation, points, ["A", "B", "D"], nearest=True)
        summary = _coverage_summary(covjson)
        assert [s[0] for s in summary] == ["A", "B", "D"]
        assert summary[0][1:] == summary[1][1:]

    @pytest.mark.xfail(
        strict=True,
        reason="polytope's nearest-neighbour search leaves tags on cells it examined but did not choose; "
        "needs retagging in polytope's FDB backend (see TIMESERIES_LABELS.md, Problem 2)",
    )
    @pytest.mark.parametrize(
        "points, want",
        [
            ([(48.0, 11.0), (48.0, 12.5)], [CELL_1, CELL_2]),  # same row, different cells
            ([(48.0, 11.0), (48.5, 11.0)], [CELL_1, CELL_3]),  # neighbouring rows
        ],
        ids=["same-row", "adjacent-rows"],
    )
    def test_nearest_points_on_neighbouring_cells_get_one_cell_each(self, validation, points, want):
        _, covjson = self._run(validation, points, ["A", "B"], nearest=True)
        summary = _coverage_summary(covjson)
        assert len(summary) == 2
        assert [(lat, lon) for _, lat, lon, _ in summary] == pytest.approx(want)


# -- Polygon labels: nesting depth and rings --


def _square(a, b):
    return [[a, a], [a, b], [b, b], [b, a], [a, a]]


class TestPolygonLabels:
    """Each polygon (ring) is one labelled unit: depth 2 is one ring, depth 3 a list of rings."""

    @staticmethod
    def _polygon(shape, labels=None):
        from polytope_mars.features.polygon import Polygons

        config = SimpleNamespace(polygonrules=SimpleNamespace(max_area=10**12, max_points=100000))
        feature_config = {"type": "polygon", "shape": shape}
        if labels is not None:
            feature_config["labels"] = labels
        return Polygons(feature_config, config)

    @staticmethod
    def _tags(feature):
        (union,) = feature.get_shapes()
        return [s.tag for s in union._shapes]

    def test_single_ring_unlabelled(self):
        assert self._tags(self._polygon(_square(0, 10))) == [(0, None)]

    def test_single_ring_one_label(self):
        assert self._tags(self._polygon(_square(0, 10), ["P"])) == [(0, "P")]

    def test_single_ring_needs_exactly_one_label(self):
        with pytest.raises(ValueError, match="Number of labels"):
            self._polygon(_square(0, 10), ["P", "Q"])

    def test_list_of_rings_one_label_each(self):
        feature = self._polygon([_square(0, 4), _square(6, 10)], ["P", "Q"])
        assert self._tags(feature) == [(0, "P"), (1, "Q")]

    def test_list_of_rings_unlabelled_still_tagged_per_ring(self):
        assert self._tags(self._polygon([_square(0, 4), _square(6, 10)])) == [(0, None), (1, None)]

    def test_list_of_rings_label_count_must_match(self):
        with pytest.raises(ValueError, match="Number of labels"):
            self._polygon([_square(0, 4), _square(6, 10)], ["P"])

    def test_inner_ring_is_a_separate_labelled_polygon_not_a_hole(self):
        """Depth 3 has no hole semantics: an inner ring is just another polygon unit, filled and tagged."""
        feature = self._polygon([_square(0, 10), _square(4, 6)], ["Outer", "Inner"])
        assert self._tags(feature) == [(0, "Outer"), (1, "Inner")]

    @pytest.mark.parametrize(
        "shape",
        [
            [[_square(0, 4)], [_square(6, 10)]],  # depth 4
            [[_square(0, 10), _square(4, 6)]],  # depth 5: one MultiPolygon unit with a hole
        ],
        ids=["depth-4", "depth-5"],
    )
    def test_deeper_nesting_is_rejected(self, shape):
        """Not supported yet (separate PR). Rejected only by accident today (unpacking error in the area
        calculation), not by an explicit check; tighten the match when a clear error is added."""
        with pytest.raises(ValueError):
            self._polygon(shape)
