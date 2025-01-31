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
            "step": "1/2",
            "feature": {
                "type": "polygon",
                "shape": [
                    [40.0, -105.0],
                    [ 40.0, -104.0],
                    [41.0, -104.0],
                    [ 41.0, -105.0],
                    [40.0, -105.0],
                ]
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
    def test_polygon(self):
        result = PolytopeMars(self.cf).extract(self.request)
        decoder = Covjsonkit().decode(result)
        decoder.to_xarray()
        assert True

    # @pytest.mark.skip(reason="Gribjump not set up for ci actions yet")
    def test_polygon_lonlat(self):
        request_copy = copy.deepcopy(self.request)
        result = PolytopeMars(self.cf).extract(self.request)
        request_copy["feature"]["axes"] = ["longitude", "latitude"]
        request_copy["feature"]["shape"] = [
            [-105.0, 40.0],
            [-104.0, 40.0],
            [-104.0, 41.0],
            [-105.0, 41.0],
            [-105.0, 40.0],
        ]
        result1 = PolytopeMars(self.cf).extract(request_copy)
        assert result == result1

    # @pytest.mark.skip(reason="Gribjump not set up for ci actions yet")
    def test_polygon_1_axes(self):
        self.request["feature"]["axes"] = ["latitude"]
        self.request["feature"]["shape"] = [[-1], [0], [-1]]
        with pytest.raises(ValueError):
            PolytopeMars(self.cf).extract(self.request)

    def test_polygon_multiple_steps(self):
        self.request["step"] = "0/1"
        result = PolytopeMars(self.cf).extract(self.request)
        decoder = Covjsonkit().decode(result)
        decoder.to_xarray()
        assert True

    def test_polygon_no_shape(self):
        with pytest.raises(KeyError):
            del self.request["feature"]["shape"]
            PolytopeMars(self.cf).extract(self.request)
