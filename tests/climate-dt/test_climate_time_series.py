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
            "activity": "scenariomip",
            "class": "d1",
            "dataset": "climate-dt",
            "experiment": "ssp3-7.0",
            "generation": "1",
            "levtype": "sfc",
            "date": "20210101/to/20210110",
            "model": "ifs-nemo",
            "expver": "0001",
            "param": "167/165",
            "realization": "1",
            "resolution": "high",
            "stream": "clte",
            "type": "fc",
            "time": "0000/to/2300",
            "feature": {
                "type": "timeseries",
                "points": [[38, -9.5]],
                "time_axis": "date",
                "axes": ["latitude", "longitude"],
            },
        }

        self.options = {
            "axis_config": [
                {"axis_name": "date", "transformations": [{"name": "type_change", "type": "date"}]},
                {"axis_name": "time", "transformations": [{"name": "type_change", "type": "time"}]},
                {
                    "axis_name": "values",
                    "transformations": [
                        {
                            "name": "mapper",
                            "type": "healpix_nested",
                            "resolution": 1024,
                            "axes": ["latitude", "longitude"],
                        }
                    ],
                },
                {
                    "axis_name": "latitude",
                    "transformations": [{"name": "reverse", "is_reverse": True}],
                },
                {
                    "axis_name": "longitude",
                    "transformations": [{"name": "cyclic", "range": [0, 360]}],
                },
            ],
            "pre_path": {"class": "d1", "expver": "0001", "levtype": "sfc", "stream": "clte"},
            "compressed_axes_config": [
                "longitude",
                "latitude",
                "date",
                "time",
                "param",
            ],
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
        request_copy["feature"]["points"] = [[-9.5, 38]]
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
        with pytest.raises(KeyError):
            result = PolytopeMars(self.cf).extract(self.request)
            decoder = Covjsonkit().decode(result)
            decoder.to_xarray()

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
        assert da.t.size == 20

    def test_timeseries_multiple_dates_select(self):
        self.request["date"] = "20210101/20210110"
        result = PolytopeMars(self.cf).extract(self.request)
        decoder = Covjsonkit().decode(result)
        da = decoder.to_xarray()
        assert da.t.size == 48

    def test_timeseries_no_lon(self):
        self.request["feature"]["axes"] = ["levelist", "latitude"]
        with pytest.raises(KeyError):
            PolytopeMars(self.cf).extract(self.request)

    def test_timeseries_neg_step(self):
        # self.request["feature"]["axes"] = ["levelist", "latitude"]
        self.request["feature"]["range"] = {"start": -1, "end": 3}
        with pytest.raises(ValueError):
            PolytopeMars(self.cf).extract(self.request)

    def test_timeseries_by_one(self):
        self.request["date"] = ("20210101/to/20210110/by/1",)
        with pytest.raises(ValueError):
            PolytopeMars(self.cf).extract(self.request)

    def test_timeseries_by_week(self):
        self.request["date"] = ("20210101/to/20210110/by/7",)
        with pytest.raises(ValueError):
            PolytopeMars(self.cf).extract(self.request)
