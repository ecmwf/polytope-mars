import copy

import pytest
from conflator import Conflator
from covjsonkit.api import Covjsonkit

from polytope_mars.api import PolytopeMars
from polytope_mars.config import PolytopeMarsConfig

# If using a local FDB need to set GRIBJUMP_CONFIG_FILE and DYLD_LIBRARY_PATH


class TestFeatureFactory:
    def setup_method(self):

        self.request = {
            "class": "d1",
            "dataset": "on-demand-extremes-dt",
            "stream": "oper",
            "type": "fc",
            "date": "20250926",
            "time": "0000",
            "levtype": "sfc",
            "expver": "0099",
            "param": "167",
            "georef": "gcgkrb",
            "feature": {
                "type": "timeseries",
                "points": [[-9.11, 38.79]],
                "axes": "step",
                "range": {"start": 0, "end": 10},
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
                            "type": "lambert_conformal",
                            "resolution": 0,
                            "axes": ["latitude", "longitude"],
                        }
                    ],
                },
                {
                    "axis_name": "step",
                    "transformations": [{"name": "type_change", "type": "int"}],
                },
            ],
            "pre_path": {
                "class": "d1",
                "expver": "0099",
                "dataset": "on-demand-extremes-dt",
                "levtype": "sfc",
                "stream": "oper",
                "type": "fc",
                "georef": "gcgkrb",
            },
            "compressed_axes_config": [
                "date",
                "time",
                "longitude",
                "latitude",
                "param",
                "step",
            ],
            "dynamic_grid": True,
        }

        conf = Conflator(app_name="polytope_mars", model=PolytopeMarsConfig).load()
        self.cf = conf.model_dump()
        self.cf["options"] = self.options

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
        request_copy["feature"]["axes"] = "step"
        request_copy["feature"]["points"] = [[38.79, -9.11]]
        result1 = PolytopeMars(self.cf).extract(request_copy)
        assert result == result1

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

    def test_timeseries_no_axes(self):
        del self.request["feature"]["axes"]
        # Without axes, time_axis must be set; expect KeyError
        with pytest.raises(KeyError):
            PolytopeMars(self.cf).extract(self.request)

    def test_timeseries_neg_step(self):
        self.request["feature"]["range"] = {"start": -1, "end": 10}
        with pytest.raises(ValueError):
            PolytopeMars(self.cf).extract(self.request)

    def test_timeseries_by_2(self):
        self.request["feature"]["range"] = {"start": 0, "end": 10, "interval": 2}
        result = PolytopeMars(self.cf).extract(self.request)
        decoder = Covjsonkit().decode(result)
        decoder.to_xarray()
        assert True

    def test_timeseries_no_range(self):
        del self.request["feature"]["range"]
        with pytest.raises(KeyError):
            PolytopeMars(self.cf).extract(self.request)
