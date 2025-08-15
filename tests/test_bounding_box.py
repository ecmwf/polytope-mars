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
            "levtype": "sfc",
            "expver": "0001",
            "domain": "g",
            "param": "164/166/167",
            "number": "1",
            "step": "0/1",
            "feature": {
                "type": "boundingbox",
                "points": [[0, 0], [1, 1]],
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
                "levtype": "sfc",
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
    def test_boundingbox(self):
        result = PolytopeMars(self.cf).extract(self.request)
        decoder = Covjsonkit().decode(result)
        decoder.to_xarray()
        assert True

    def test_boundingbox_three_points(self):
        with pytest.raises(ValueError):
            self.request["feature"]["points"] = [[0, 0], [1, 1], [2, 2]]
            PolytopeMars(self.cf).extract(self.request)

    def test_boundingbox_three_values_per_point(self):
        with pytest.raises(ValueError):
            self.request["feature"]["points"] = [[0, 0, 0], [1, 1, 1]]
            PolytopeMars(self.cf).extract(self.request)

    # @pytest.mark.skip(reason="Gribjump not set up for ci actions yet")
    def test_boundingbox_lonlat(self):
        request_copy = copy.deepcopy(self.request)
        self.request["feature"]["points"] = [[0.1, 0.2], [0.2, 0.3]]
        result = PolytopeMars(self.cf).extract(self.request)
        request_copy["feature"]["axes"] = ["longitude", "latitude"]
        request_copy["feature"]["points"] = [[0.2, 0.1], [0.3, 0.2]]
        result2 = PolytopeMars(self.cf).extract(request_copy)

        assert result == result2

    # @pytest.mark.skip(reason="Gribjump not set up for ci actions yet")
    def test_boundingbox_1_axes(self):
        self.request["feature"]["axes"] = ["latitude"]
        self.request["feature"]["points"] = [[-1], [0], [1]]
        with pytest.raises(ValueError):
            PolytopeMars(self.cf).extract(self.request)

    def test_boundingbox_no_points(self):
        with pytest.raises(KeyError):
            del self.request["feature"]["points"]
            PolytopeMars(self.cf).extract(self.request)
