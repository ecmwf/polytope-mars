import copy
from datetime import datetime, timedelta

import pytest
from conflator import Conflator
from covjsonkit.api import Covjsonkit

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
