import os
import json

# If using a local FDB need to set FDB_HOME and ECCODES_DEFINITIO_PATH


import pytest
from conflator import Conflator

from covjsonkit.api import Covjsonkit
from polytope_mars.api import PolytopeMars
from polytope_mars.config import PolytopeMarsConfig 


class TestFeatureFactory:
    def setup_method(self):
        self.request = {
            "class": "od",
            "stream" : "enfo",
            "type" : "pf",
            "date" : "20250106",
            "time" : "0000",
            "levtype" : "pl",
            "expver" : "0001", 
            "domain" : "g",
            "param" : "203/133",
            "number" : "1",
            "step" : "0",
            "levelist" : "500",
            "feature" : {
                "type" : "trajectory",
                "points" : [[-1, -1], [0, 0], [1, 1]],
                "axes" : ["latitude", "longitude"],
                "inflate" : "round",
                "inflation" : 0.1,
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
            "pre_path": {"class": "od", "expver": "0001", "levtype": "pl", "stream": "enfo", "type": "pf", "domain": "g", "date" : "20250106", "time" : "0000"},
        }

        conf = Conflator(app_name="polytope_mars", model=PolytopeMarsConfig).load()
        self.cf = conf.model_dump()
        self.cf['options'] = self.options

    def test_trajectory(self):
        result = PolytopeMars(self.cf).extract(self.request)
        decoder = Covjsonkit().decode(result)
