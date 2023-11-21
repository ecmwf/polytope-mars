
import pytest
import json

from polytope_mars.api import PolytopeMars
from polytope_mars.api import features

class TestFeatureFactory:

    def setup_method(self, method):
        
        self.request = {
            "class": "od",
            "stream" : "oper",
            "type" : "fc",
            "date" : "20170101/to/20170102",
            "time" : "00:00:00",
            "levtype" : "pl",
            "expver" : "0001", 
            "levelist" : "1/2/7/100/150/700/800/850",
            "feature" : {
                "type" : "timeseries",
                "points": [[3, 7]]
            },
        }

    def test_timeseries_invalid(self):

        with pytest.raises(ValueError):
            PolytopeMars({}).extract("invalid")

        with pytest.raises(KeyError):
            PolytopeMars({}).extract({"hello": "world"})

        with pytest.raises(KeyError):
            PolytopeMars({}).extract(json.dumps({"hello": "world"}))

        # 'step' is invalid in the request
        self.request["step"] = "0"
        with pytest.raises(KeyError):
            PolytopeMars({}).extract(self.request)

    def test_timeseries_valid(self):
        
        PolytopeMars({}).extract(self.request)