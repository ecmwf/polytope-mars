import copy

import pytest
from conflator import Conflator
from covjsonkit.api import Covjsonkit

from polytope_mars.api import PolytopeMars
from polytope_mars.config import PolytopeMarsConfig

# If using a local FDB need to set GRIBJUMP_CONFIG_FILE and DYLD_LIBRARY_PATH

# Simple polygon over Ireland (lat/lon, longitudes in 0-360 range)
IRELAND_POLYGON = [
    [51.5, 350.0],
    [51.5, 354.0],
    [55.5, 354.0],
    [55.5, 350.0],
    [51.5, 350.0],
]


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
            "step": "0h30m",
            "georef": "gcgkrb",
            "feature": {
                "type": "polygon",
                "shape": IRELAND_POLYGON,
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

    def test_polygon_subhourly(self):
        result = PolytopeMars(self.cf).extract(self.request)
        decoder = Covjsonkit().decode(result)
        decoder.to_xarray()
        assert True

    def test_polygon_subhourly_45min(self):
        request_copy = copy.deepcopy(self.request)
        request_copy["step"] = "1h45m"
        result = PolytopeMars(self.cf).extract(request_copy)
        decoder = Covjsonkit().decode(result)
        decoder.to_xarray()
        assert True

    def test_polygon_subhourly_list_of_steps(self):
        # "2h10m/2h20m"
        request_copy = copy.deepcopy(self.request)
        request_copy["step"] = "2h10m/2h20m"
        result = PolytopeMars(self.cf).extract(request_copy)
        decoder = Covjsonkit().decode(result)
        decoder.to_xarray()
        assert True

    def test_polygon_subhourly_range(self):
        # "0h10m/to/1h30m" at 10-minute intervals
        request_copy = copy.deepcopy(self.request)
        request_copy["step"] = "0h10m/to/1h30m/by/0h10m"
        result = PolytopeMars(self.cf).extract(request_copy)
        decoder = Covjsonkit().decode(result)
        decoder.to_xarray()
        assert True

    def test_polygon_subhourly_lonlat(self):
        request_copy = copy.deepcopy(self.request)
        result = PolytopeMars(self.cf).extract(self.request)
        request_copy["feature"]["axes"] = ["longitude", "latitude"]
        request_copy["feature"]["shape"] = [[p[1], p[0]] for p in IRELAND_POLYGON]
        result1 = PolytopeMars(self.cf).extract(request_copy)
        assert result == result1

    def test_polygon_subhourly_no_shape(self):
        with pytest.raises(KeyError):
            del self.request["feature"]["shape"]
            PolytopeMars(self.cf).extract(self.request)

    def test_polygon_subhourly_1_axes(self):
        self.request["feature"]["axes"] = ["latitude"]
        self.request["feature"]["shape"] = [[-1], [0], [-1]]
        with pytest.raises(ValueError):
            PolytopeMars(self.cf).extract(self.request)
