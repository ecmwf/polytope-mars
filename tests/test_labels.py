"""Tests for the optional 'labels' field in the timeseries feature dictionary."""

import copy
from datetime import datetime, timedelta

import pytest
from conflator import Conflator
from polytope_feature import shapes
from polytope_feature.polytope import Request

from polytope_mars.api import PolytopeMars
from polytope_mars.config import PolytopeMarsConfig


class TestIdentifiersValidation:
    """Unit tests for identifiers parsing and validation (no data retrieval)."""

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

    def test_identifiers_accepted_in_feature_config(self):
        """Labels field is accepted without error when count matches points."""
        preq, feature = self._build_request_shapes(self.request)
        assert feature.identifiers == ["Lisbon", "Dusseldorf"]

    def test_identifiers_none_when_not_provided(self):
        """When labels is omitted, feature.identifiers is None."""
        request = copy.deepcopy(self.request)
        del request["feature"]["labels"]
        preq, feature = self._build_request_shapes(request)
        assert feature.identifiers is None

    def test_identifiers_single_point(self):
        """Labels works with a single point."""
        request = copy.deepcopy(self.request)
        request["feature"]["points"] = [[48.0, 11.0]]
        request["feature"]["labels"] = ["Munich"]
        preq, feature = self._build_request_shapes(request)
        assert feature.identifiers == ["Munich"]

    def test_identifiers_many_points(self):
        """Labels works with many points."""
        request = copy.deepcopy(self.request)
        points = [[-9.10, 38.78], [51.5, 6.5], [48.0, 11.0], [40.4, -3.7]]
        identifiers = ["Lisbon", "Dusseldorf", "Munich", "Madrid"]
        request["feature"]["points"] = points
        request["feature"]["labels"] = identifiers
        preq, feature = self._build_request_shapes(request)
        assert feature.identifiers == identifiers

    # -- Validation error tests --

    def test_identifiers_mismatch_too_few(self):
        """Raises ValueError when fewer labels than points."""
        request = copy.deepcopy(self.request)
        request["feature"]["labels"] = ["Lisbon"]  # only 1, but 2 points
        with pytest.raises(ValueError, match="Number of labels"):
            self._build_request_shapes(request)

    def test_identifiers_mismatch_too_many(self):
        """Raises ValueError when more labels than points."""
        request = copy.deepcopy(self.request)
        request["feature"]["labels"] = ["Lisbon", "Dusseldorf", "Munich"]  # 3, but 2 points
        with pytest.raises(ValueError, match="Number of labels"):
            self._build_request_shapes(request)

    def test_identifiers_empty_list_with_points(self):
        """Raises ValueError when labels is empty but points exist."""
        request = copy.deepcopy(self.request)
        request["feature"]["labels"] = []
        with pytest.raises(ValueError, match="Number of labels"):
            self._build_request_shapes(request)

    # -- Shape construction tests --

    def test_identifiers_passed_as_tag_to_point_shapes(self):
        """Each identifier is passed as the tag kwarg to the corresponding shapes.Point."""
        request = copy.deepcopy(self.request)
        preq, feature = self._build_request_shapes(request)

        # Find the Union shape (it covers latitude/longitude)
        union_shape = None
        for shape in preq.shapes:
            if isinstance(shape, shapes.Union):
                union_shape = shape
                break

        assert union_shape is not None, "Expected a Union shape for lat/lon points"

        # The Union's internal shapes should be Points with tags
        point_shapes = union_shape._shapes
        assert len(point_shapes) == 2

        # Check tags match identifiers
        tags = [p.tag for p in point_shapes]
        assert tags == ["Lisbon", "Dusseldorf"]

    def test_no_identifiers_means_no_tags(self):
        """When labels is not provided, Point shapes have tag=None."""
        request = copy.deepcopy(self.request)
        del request["feature"]["labels"]
        preq, feature = self._build_request_shapes(request)

        union_shape = None
        for shape in preq.shapes:
            if isinstance(shape, shapes.Union):
                union_shape = shape
                break

        assert union_shape is not None
        point_shapes = union_shape._shapes
        for p in point_shapes:
            assert p.tag is None

    def test_identifiers_with_swapped_axes(self):
        """Labels work correctly when axes are [longitude, latitude]."""
        request = copy.deepcopy(self.request)
        request["feature"]["axes"] = ["longitude", "latitude"]
        request["feature"]["points"] = [[38.78, -9.10], [6.5, 51.5]]
        request["feature"]["labels"] = ["Lisbon", "Dusseldorf"]
        preq, feature = self._build_request_shapes(request)

        union_shape = None
        for shape in preq.shapes:
            if isinstance(shape, shapes.Union):
                union_shape = shape
                break

        assert union_shape is not None
        point_shapes = union_shape._shapes
        tags = [p.tag for p in point_shapes]
        assert tags == ["Lisbon", "Dusseldorf"]

    def test_identifiers_numeric_values(self):
        """Labels can be numeric (e.g. station IDs)."""
        request = copy.deepcopy(self.request)
        request["feature"]["labels"] = [12345, 67890]
        preq, feature = self._build_request_shapes(request)

        union_shape = None
        for shape in preq.shapes:
            if isinstance(shape, shapes.Union):
                union_shape = shape
                break

        point_shapes = union_shape._shapes
        tags = [p.tag for p in point_shapes]
        assert tags == [12345, 67890]

    def test_identifiers_not_allowed_without_points(self):
        """If points is empty but labels is provided, validation fails."""
        request = copy.deepcopy(self.request)
        request["feature"]["points"] = []
        request["feature"]["labels"] = ["Lisbon"]
        # This should fail because points is empty but identifiers has values
        # The parse step will fail because points[0] doesn't exist
        with pytest.raises((ValueError, IndexError)):
            self._build_request_shapes(request)


class TestIdentifiersIntegration:
    """Integration tests that verify the full extract pipeline accepts identifiers.

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

    def test_extract_with_identifiers(self):
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

    def test_extract_without_identifiers_still_works(self):
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

    def test_merged_points_no_identifiers(self):
        """Without labels, merged points still produce only one coverage (no duplication)."""
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
                # Two points that snap to same grid point, no identifiers
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
        # Without labels, merged points produce a single coverage (polytope deduplication)
        assert len(coverages) == 1
        assert "label" not in coverages[0]["mars:metadata"]
