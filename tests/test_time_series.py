import copy
from datetime import datetime, timedelta

import pandas as pd
import pytest
from conflator import Conflator
from covjsonkit.api import Covjsonkit
from polytope_feature import shapes
from polytope_feature.polytope import Request

from polytope_mars.api import PolytopeMars
from polytope_mars.config import PolytopeMarsConfig

# If using a local FDB need to set GRIBJUMP_CONFIG_FILE and DYLD_LIBRARY_PATH


class TestFeatureFactory:
    def setup_method(self):

        today = datetime.today()
        yesterday = today - timedelta(days=1)
        self.today = today.strftime("%Y%m%d")
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
            "param": "164/166/167/169",
            "number": "1/to/2",
            "feature": {
                "type": "timeseries",
                "points": [[-9.10, 38.78]],
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

    # @pytest.mark.skip(reason="Gribjump not set up for ci actions yet")
    def test_timeseries(self):
        result = PolytopeMars(self.cf).extract(self.request)
        decoder = Covjsonkit().decode(result)
        decoder.to_xarray()
        assert True

    def test_timeseries_axes(self):
        self.request["feature"]["axes"] = ["latitude", "longitude", "step"]
        with pytest.raises(ValueError):
            PolytopeMars(self.cf).extract(self.request)

    def test_timeseries_mix_axes(self):
        request_copy = copy.deepcopy(self.request)
        result = PolytopeMars(self.cf).extract(self.request)
        request_copy["feature"]["axes"] = ["longitude", "latitude"]
        request_copy["feature"]["points"] = [[38.78, -9.10]]
        result1 = PolytopeMars(self.cf).extract(request_copy)
        assert result == result1

    def test_timeseries_mix_axes_step(self):
        self.request["feature"]["axes"] = ["longitude", "latitude"]
        result = PolytopeMars(self.cf).extract(self.request)
        decoder = Covjsonkit().decode(result)
        decoder.to_xarray()
        assert True

    def test_timeseries_only_step_axes(self):
        self.request["feature"]["axes"] = ["step"]
        with pytest.raises(ValueError):
            PolytopeMars(self.cf).extract(self.request)

    def test_timeseries_step_in_both(self):
        self.request["step"] = "0/to/3"
        with pytest.raises(ValueError):
            result = PolytopeMars(self.cf).extract(self.request)
            decoder = Covjsonkit().decode(result)
            decoder.to_xarray()

    def test_timeseries_step_in_request(self):
        self.request["step"] = "0/to/3"
        del self.request["feature"]["range"]
        result = PolytopeMars(self.cf).extract(self.request)
        decoder = Covjsonkit().decode(result)
        decoder.to_xarray()
        assert True

    def test_timeseries_no_time_axis(self):
        with pytest.raises(KeyError):
            del self.request["feature"]["time_axis"]
            PolytopeMars(self.cf).extract(self.request)

    def test_timeseries_no_axes(self):
        del self.request["feature"]["axes"]
        PolytopeMars(self.cf).extract(self.request)
        assert True

    def test_timeseries_multiple_times(self):
        self.request["time"] = "0000/1200"
        result = PolytopeMars(self.cf).extract(self.request)
        decoder = Covjsonkit().decode(result)
        da = decoder.to_xarray()
        assert da[0].datetime.size == 2

    def test_timeseries_multiple_dates(self):
        self.request["date"] = f"{self.date}/{self.today}"
        result = PolytopeMars(self.cf).extract(self.request)
        decoder = Covjsonkit().decode(result)
        da = decoder.to_xarray()
        assert da[0].datetime.size == 2

    def test_timeseries_no_lon(self):
        self.request["feature"]["axes"] = ["levelist", "latitude"]
        with pytest.raises(KeyError):
            PolytopeMars(self.cf).extract(self.request)

    def test_timeseries_neg_step(self):
        self.request["feature"]["range"] = {"start": -1, "end": 3}
        with pytest.raises(ValueError):
            PolytopeMars(self.cf).extract(self.request)

    def test_timeseries_interval(self):
        self.request["feature"]["range"] = {"start": 1, "end": 10, "interval": 2}
        PolytopeMars(self.cf).extract(self.request)

    def test_timeseries_number_interval(self):
        self.request["number"] = "1/to/10/by/2"
        PolytopeMars(self.cf).extract(self.request)


class TestHdateRequestConstruction:
    def setup_method(self):
        self.request = {
            "class": "ce",
            "stream": "efcl",
            "type": "sfo",
            "date": "20240301",
            "time": "0600",
            "hdate": "20250714",
            "levtype": "sfc",
            "expver": "4321",
            "domain": "g",
            "model": "lisflood",
            "origin": "ecmf",
            "param": "240023",
            "step": "6",
            "feature": {
                "type": "timeseries",
                "points": [[51.5, 6.5]],
                "time_axis": "hdate",
            },
        }

        self.options = {
            "axis_config": [
                {
                    "axis_name": "hdate",
                    "transformations": [{"name": "merge", "other_axis": "time", "linkers": ["T", "00"]}],
                },
                {"axis_name": "step", "transformations": [{"name": "type_change", "type": "int"}]},
                {"axis_name": "number", "transformations": [{"name": "type_change", "type": "int"}]},
                {"axis_name": "levelist", "transformations": [{"name": "type_change", "type": "int"}]},
            ],
            "compressed_axes_config": [
                "longitude",
                "latitude",
                "levtype",
                "step",
                "date",
                "hdate",
                "domain",
                "expver",
                "param",
                "class",
                "stream",
                "type",
            ],
        }

        conf = Conflator(app_name="polytope_mars", model=PolytopeMarsConfig).load()
        self.cf = conf.model_dump()
        self.cf["options"] = self.options

    def _build_request(self, request):
        pm = PolytopeMars(self.cf)
        request = copy.deepcopy(request)
        feature_config = request.pop("feature")
        feature_config_copy = feature_config.copy()
        feature_type = feature_config["type"]
        feature = pm._feature_factory(feature_type, feature_config, pm.conf)
        feature.validate(request, feature_config_copy)
        request = feature.parse(request, feature_config_copy)
        s = pm._create_base_shapes(request, feature_type)
        s.extend(feature.get_shapes())
        return Request(*s)

    def _shapes_to_dict(self, preq):
        result = {}
        for s in preq.shapes:
            if isinstance(s, shapes.Select):
                result[s.axis] = s.values
            elif isinstance(s, shapes.Span):
                result[s.axis] = (s.lower, s.upper)
        return result

    def test_hdate_single_time_request(self):
        preq = self._build_request(self.request)
        d = self._shapes_to_dict(preq)

        assert d["hdate"] == [pd.Timestamp("20250714T0600")]
        assert d["date"] == ["20240301"]
        assert "time" not in d

    def test_hdate_multiple_times_request(self):
        request = copy.deepcopy(self.request)
        request["time"] = "0600/1200"
        preq = self._build_request(request)
        d = self._shapes_to_dict(preq)

        assert d["hdate"] == [pd.Timestamp("20250714T0600"), pd.Timestamp("20250714T1200")]
        assert d["date"] == ["20240301"]
        assert "time" not in d

    def test_hdate_multiple_hdates_request(self):
        request = copy.deepcopy(self.request)
        request["hdate"] = "20250714/20250715"
        preq = self._build_request(request)
        d = self._shapes_to_dict(preq)

        assert d["hdate"] == [pd.Timestamp("20250714T0600"), pd.Timestamp("20250715T0600")]
        assert d["date"] == ["20240301"]
        assert "time" not in d

    def test_hdate_multiple_hdates_multiple_times_request(self):
        request = copy.deepcopy(self.request)
        request["hdate"] = "20250714/20250715"
        request["time"] = "0600/1200"
        preq = self._build_request(request)
        d = self._shapes_to_dict(preq)

        assert len(d["hdate"]) == 4
        assert d["hdate"] == [
            pd.Timestamp("20250714T0600"),
            pd.Timestamp("20250714T1200"),
            pd.Timestamp("20250715T0600"),
            pd.Timestamp("20250715T1200"),
        ]
        assert d["date"] == ["20240301"]
        assert "time" not in d
