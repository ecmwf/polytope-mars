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
            "param": "165/167",
            "step": "1",
            "feature" : {
                "type" : "boundingbox",
                "points" : [[53.55, 2.76], [50.66, 7.86]],
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
