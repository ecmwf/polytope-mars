import pytest
from conflator import Conflator
from covjsonkit.api import Covjsonkit

from polytope_mars.api import PolytopeMars
from polytope_mars.config import PolytopeMarsConfig

# If using a local FDB need to set GRIBJUMP_CONFIG_FILE and DYLD_LIBRARY_PATH

# Train route points (latitude, longitude in 0-360) matching the on-demand-extremes-dt example
TRAIN_ROUTE = [
    [57.479, 355.777],  # Inverness
    [56.395, 356.565],  # Perth
    [55.952, 356.811],  # Edinburgh Waverley
    [54.892, 357.067],  # Carlisle
    [54.047, 357.192],  # Lancaster
    [53.757, 357.297],  # Preston
    [53.089, 357.565],  # Crewe
    [52.478, 358.101],  # Birmingham New Street
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
            "georef": "gcgkrb",
            "step": "1",
            "feature": {
                "type": "trajectory",
                "points": TRAIN_ROUTE,
                "inflation": 0.01,
                "inflate": "round",
                "axes": ["latitude", "longitude"],
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

    def test_trajectory(self):
        result = PolytopeMars(self.cf).extract(self.request)
        decoder = Covjsonkit().decode(result)
        decoder.to_xarray()
        assert True

    def test_trajectory_latlon_correct_inflation(self):
        self.request["feature"]["inflation"] = [0.01, 0.02]
        result = PolytopeMars(self.cf).extract(self.request)
        decoder = Covjsonkit().decode(result)
        decoder.to_xarray()
        assert True

    def test_trajectory_latlon_incorrect_inflates(self):
        with pytest.raises(ValueError):
            self.request["feature"]["inflation"] = [0.01, 0.02, 0.03]
            result = PolytopeMars(self.cf).extract(self.request)
            decoder = Covjsonkit().decode(result)
            decoder.to_xarray()

    def test_trajectory_lonlat(self):
        self.request["feature"]["axes"] = ["longitude", "latitude"]
        self.request["feature"]["points"] = [[p[1], p[0]] for p in TRAIN_ROUTE]
        result = PolytopeMars(self.cf).extract(self.request)
        decoder = Covjsonkit().decode(result)
        decoder.to_xarray()
        assert True

    def test_trajectory_3d_step(self):
        self.request["feature"]["axes"] = ["latitude", "longitude", "step"]
        self.request["feature"]["points"] = [
            [57.479, 355.777, 1],
            [56.395, 356.565, 2],
            [55.952, 356.811, 3],
        ]
        self.request["feature"]["inflate"] = "round"
        del self.request["step"]
        result = PolytopeMars(self.cf).extract(self.request)
        decoder = Covjsonkit().decode(result)
        decoder.to_xarray()
        assert True

    def test_trajectory_1_axes(self):
        self.request["feature"]["axes"] = ["latitude"]
        self.request["feature"]["points"] = [[52.0], [53.0], [54.0]]
        with pytest.raises(KeyError):
            PolytopeMars(self.cf).extract(self.request)

    def test_trajectory_no_inflation(self):
        del self.request["feature"]["inflation"]
        with pytest.raises(KeyError):
            PolytopeMars(self.cf).extract(self.request)
