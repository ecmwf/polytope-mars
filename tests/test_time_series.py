
import pytest
import json
import os

from polytope_mars.api import PolytopeMars
from polytope_mars.api import features


from datetime import date, datetime, timedelta
import datetime
import random

# If using a local FDB need to set FDB_HOME and ECCODES_DEFINITIO_PATH


class TestFeatureFactory:

    def setup_method(self):
        
        self.request = {
            "class": "od",
            "stream" : "enfo",
            "type" : "pf",
            "date" : "20231205",
            "time" : "00:00:00",
            "levtype" : "sfc",
            "expver" : "0001", 
            "domain" : "g",
            "param" : "167",
            "number" : "1/2/3/4/5",
            "feature" : {
                "type" : "timeseries",
                "points": [[0.035149384216, 0.0]],
                "start": 0,
                "end" : 9
            },
        }

        self.options = {
            "values": {
                    "mapper": {"type": "octahedral", "resolution": 1280, "axes": ["latitude", "longitude"]}
            },
            "date": {"merge": {"with": "time", "linkers": ["T", "00"]}},
            "step": {"type_change": "int"},
        }

        self.config = {"class": "od", "expver": "0001", "levtype": "sfc", "type": "pf"}

    def test_timeseries_invalid(self):

        with pytest.raises(TypeError):
            PolytopeMars(self.options,self.config).extract("invalid")

        with pytest.raises(TypeError):
            PolytopeMars(self.options,self.config).extract({"hello": "world"})

        with pytest.raises(TypeError):
            PolytopeMars(self.options,self.config).extract(json.dumps({"hello": "world"}))

        # 'step' is invalid in the request
        self.request["step"] = "0"
        with pytest.raises(TypeError):
            PolytopeMars(self.options,self.config).extract(self.request)

        self.request["levellist"] = "0"
        with pytest.raises(TypeError):
            PolytopeMars(self.options,self.config).extract(self.request)

    def test_timeseries_valid(self):
        
        coverage = PolytopeMars(self.config, self.options).extract(self.request)
        print(coverage)