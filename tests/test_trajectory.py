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
        self.date = yesterday.strftime("%Y%m%d")

        self.request = {
            "class": "od",
            "stream": "enfo",
            "type": "pf",
            "date": self.date,
            "time": "0000",
            "levtype": "pl",
            "expver": "0001",
            "domain": "g",
            "param": "203/133",
            "number": "1",
            "step": "0",
            "levelist": "500",
            "feature": {
                "type": "trajectory",
                "points": [[-1, -1], [0, 0], [1, 1]],
                "axes": ["latitude", "longitude"],
                "inflate": "round",
                "inflation": 0.1,
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
                {"axis_name": "latitude", "transformations": [{"name": "reverse", "is_reverse": True}]},
                {"axis_name": "longitude", "transformations": [{"name": "cyclic", "range": [0, 360]}]},
                {"axis_name": "step", "transformations": [{"name": "type_change", "type": "int"}]},
                {"axis_name": "number", "transformations": [{"name": "type_change", "type": "int"}]},
                {"axis_name": "levelist", "transformations": [{"name": "type_change", "type": "int"}]},
            ],
            "compressed_axes_config": [
                "longitude",
                "latitude",
                "levtype",
                "levelist",
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
                "levtype": "pl",
                "stream": "enfo",
                "type": "pf",
                "domain": "g",
                "date": self.date,
                "time": "0000",
            },
        }

        conf = Conflator(app_name="polytope_mars", model=PolytopeMarsConfig).load()
        self.cf = conf.model_dump()
        self.cf["options"] = self.options

    # @pytest.mark.skip(reason="Gribjump not set up for ci actions yet")
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
    def test_trajectory_3d_levelist(self):
        self.request["feature"]["axes"] = ["latitude", "longitude", "levelist"]
        self.request["feature"]["points"] = [[-1, -1, 1], [0, 0, 2], [1, 1, 10]]
        self.request["feature"]["inflate"] = "round"
        del self.request["levelist"]
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
    def test_trajectory_4d(self):
        request_copy = copy.deepcopy(self.request)
        self.request["feature"]["axes"] = ["latitude", "longitude", "levelist", "step"]
        self.request["feature"]["points"] = [[-1, -1, 1, 1], [0, 0, 2, 2], [1, 1, 10, 3]]
        self.request["feature"]["inflate"] = "box"
        del self.request["levelist"]
        del self.request["step"]
        result1 = PolytopeMars(self.cf).extract(self.request)

        request_copy["feature"]["axes"] = ["latitude", "longitude", "step", "levelist"]
        request_copy["feature"]["points"] = [[-1, -1, 1, 1], [0, 0, 2, 2], [1, 1, 3, 10]]
        request_copy["feature"]["inflate"] = "box"
        del request_copy["levelist"]
        del request_copy["step"]
        result2 = PolytopeMars(self.cf).extract(request_copy)

        assert result1 == result2

    # @pytest.mark.skip(reason="Gribjump not set up for ci actions yet")
    def test_trajectory_4d_mix_axes(self):
        request_copy = copy.deepcopy(self.request)
        self.request["feature"]["axes"] = ["latitude", "longitude", "levelist", "step"]
        self.request["feature"]["points"] = [[-1, -1, 1, 1], [0, 0, 2, 2], [1, 1, 10, 3]]
        self.request["feature"]["inflate"] = "box"
        del self.request["levelist"]
        del self.request["step"]
        result1 = PolytopeMars(self.cf).extract(self.request)

        request_copy["feature"]["axes"] = ["longitude", "step", "latitude", "levelist"]
        request_copy["feature"]["points"] = [[-1, 1, -1, 1], [0, 2, 0, 2], [1, 3, 1, 10]]
        request_copy["feature"]["inflate"] = "box"
        del request_copy["levelist"]
        del request_copy["step"]
        result2 = PolytopeMars(self.cf).extract(request_copy)
        assert result1 == result2

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

    def test_trajectory_levelist_multiple(self):
        self.request["levelist"] = "500/700"
        result = PolytopeMars(self.cf).extract(self.request)
        decoder = Covjsonkit().decode(result)
        decoder.to_xarray()
        assert True
