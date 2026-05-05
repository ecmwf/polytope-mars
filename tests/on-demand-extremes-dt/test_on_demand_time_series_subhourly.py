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
                "range": {"start": "0h0m", "end": "1h0m"},
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
                    "transformations": [{"name": "type_change", "type": "subhourly_step"}],
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

    def test_timeseries_subhourly(self):
        result = PolytopeMars(self.cf).extract(self.request)
        decoder = Covjsonkit().decode(result)
        decoder.to_xarray()
        assert True

    def test_timeseries_subhourly_single_step(self):
        request_copy = copy.deepcopy(self.request)
        request_copy["feature"]["range"] = {"start": "0h30m", "end": "0h30m"}
        result = PolytopeMars(self.cf).extract(request_copy)
        decoder = Covjsonkit().decode(result)
        decoder.to_xarray()
        assert True

    def test_timeseries_subhourly_range_with_interval(self):
        # "0h10m/to/1h30m" at 10-minute intervals
        request_copy = copy.deepcopy(self.request)
        request_copy["feature"]["range"] = {"start": "0h10m", "end": "1h30m", "interval": "0h10m"}
        result = PolytopeMars(self.cf).extract(request_copy)
        decoder = Covjsonkit().decode(result)
        decoder.to_xarray()
        assert True

    def test_timeseries_subhourly_list_of_steps(self):
        # Explicit list: "2h10m/2h20m"
        request_copy = copy.deepcopy(self.request)
        del request_copy["feature"]["range"]
        request_copy["step"] = "2h10m/2h20m"
        request_copy["feature"].pop("axes", None)
        request_copy["feature"]["time_axis"] = "step"
        result = PolytopeMars(self.cf).extract(request_copy)
        decoder = Covjsonkit().decode(result)
        decoder.to_xarray()
        assert True

    def test_timeseries_subhourly_half_hour_steps(self):
        # "0h30m" to "2h0m" stepping every half hour
        request_copy = copy.deepcopy(self.request)
        request_copy["feature"]["range"] = {"start": "0h30m", "end": "2h0m", "interval": "0h30m"}
        result = PolytopeMars(self.cf).extract(request_copy)
        decoder = Covjsonkit().decode(result)
        decoder.to_xarray()
        assert True

    def test_timeseries_subhourly_step_in_both(self):
        # step should not be in both request and feature range
        request_copy = copy.deepcopy(self.request)
        request_copy["step"] = "0h30m/to/1h30m"
        with pytest.raises(ValueError):
            PolytopeMars(self.cf).extract(request_copy)

    def test_timeseries_subhourly_neg_step(self):
        request_copy = copy.deepcopy(self.request)
        request_copy["feature"]["range"] = {"start": "-0h10m", "end": "1h0m"}
        with pytest.raises(ValueError):
            PolytopeMars(self.cf).extract(request_copy)

    def test_timeseries_subhourly_axes(self):
        # step must not appear inside 'axes' list
        request_copy = copy.deepcopy(self.request)
        request_copy["feature"]["axes"] = ["latitude", "longitude", "step"]
        with pytest.raises(ValueError):
            PolytopeMars(self.cf).extract(request_copy)
