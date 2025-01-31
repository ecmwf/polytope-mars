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
        yesterday = today - timedelta(days=5)
        self.today = today.strftime("%Y%m%d")
        self.date = yesterday.strftime("%Y%m%d")
        self.date2 = (today - timedelta(days=6)).strftime("%Y%m%d")

        self.request = {
            "dataset": "extremes-dt",
            "class": "d1",
            "stream": "oper",
            "type": "fc",
            "date": self.date,
            "time": "0000",
            "levtype": "sfc",
            "expver": "0001",
            "param": "167",
            "step": "0",
            "feature": {
                "type": "trajectory",
                "points": [[0, 0], [1, 1], [2, 2]],
                "inflation": 0.1,
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
                            "type": "octahedral",
                            "resolution": 2560,
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
                {
                    "axis_name": "levelist",
                    "transformations": [{"name": "type_change", "type": "int"}],
                },
                {
                    "axis_name": "step",
                    "transformations": [{"name": "type_change", "type": "int"}],
                },
            ],
            "pre_path": {
                "class": "d1",
                "expver": "0001",
                "dataset": "extremes-dt",
                "levtype": "sfc",
                "stream": "oper",
                "type": "fc",
                "param": "165",
            },
            "compressed_axes_config": [
                "date",
                "time",
                "longitude",
                "latitude",
                "param",
                "levelist",
                "step",
            ],
        }

        conf = Conflator(app_name="polytope_mars", model=PolytopeMarsConfig).load()
        self.cf = conf.model_dump()
        self.cf["options"] = self.options

    def test_trajectory(self):
        result = PolytopeMars(self.cf).extract(self.request)
        decoder = Covjsonkit().decode(result)
        decoder.to_xarray()
        assert True

    # @pytest.mark.skip(reason="Gribjump not set up for ci actions yet")
    def test_trajectory_latlon_correct_inflation(self):
        self.request["feature"]["inflation"] = [0.1, 0.2]
        result = PolytopeMars(self.cf).extract(self.request)
        decoder = Covjsonkit().decode(result)
        decoder.to_xarray()
        assert True

    # @pytest.mark.skip(reason="Gribjump not set up for ci actions yet")
    def test_trajectory_latlon_incorrect_inflates(self):
        with pytest.raises(ValueError):
            self.request["feature"]["inflation"] = [0.1, 0.2, 0.3]
            result = PolytopeMars(self.cf).extract(self.request)
            decoder = Covjsonkit().decode(result)
            decoder.to_xarray()

    # @pytest.mark.skip(reason="Gribjump not set up for ci actions yet")
    def test_trajectory_lonlat(self):
        self.request["feature"]["axes"] = ["longitude", "latitude"]
        result = PolytopeMars(self.cf).extract(self.request)
        decoder = Covjsonkit().decode(result)
        decoder.to_xarray()
        assert True

    # @pytest.mark.skip(reason="Gribjump not set up for ci actions yet")
    def test_trajectory_3d_step(self):
        self.request["feature"]["axes"] = ["latitude", "longitude", "step"]
        self.request["feature"]["points"] = [[-1, -1, 1], [0, 0, 2], [1, 1, 10]]
        self.request["feature"]["inflate"] = "round"
        del self.request["step"]
        result = PolytopeMars(self.cf).extract(self.request)
        decoder = Covjsonkit().decode(result)
        decoder.to_xarray()
        assert True

    # @pytest.mark.skip(reason="Gribjump not set up for ci actions yet")
    def test_trajectory_1_axes(self):
        self.request["feature"]["axes"] = ["latitude"]
        self.request["feature"]["points"] = [[-1], [0], [1]]
        with pytest.raises(KeyError):
            PolytopeMars(self.cf).extract(self.request)

    def test_trajectory_no_inflation(self):
        del self.request["feature"]["inflation"]
        with pytest.raises(KeyError):
            PolytopeMars(self.cf).extract(self.request)
