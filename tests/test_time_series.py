
import pytest
import json
import os

from polytope_mars.api import PolytopeMars
from polytope_mars.api import features


from datetime import date, datetime, timedelta
import datetime
import random

os.environ['ECCODES_DEFINITION_PATH'] = '/Users/maaw/bundles/build/share/eccodes/definitions/'
os.environ['DYLD_LIBRARY_PATH'] = '/Users/maaw/bundles/build/lib/'
os.environ['FDB_HOME'] = '/Users/maaw/fdb_store'


class TestFeatureFactory:

    def setup_method(self, method):
        
        self.request = {
            "class": "od",
            "stream" : "enfo",
            "type" : "pf",
            "date" : "20231205T000000",
            #"time" : "00:00:00",
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
                "transformation": {
                    "mapper": {"type": "octahedral", "resolution": 1280, "axes": ["latitude", "longitude"]}
                }
            },
            "date": {"transformation": {"merge": {"with": "time", "linkers": ["T", "00"]}}},
            "step": {"transformation": {"type_change": "int"}},
        }
        self.config = {"class": "od", "expver": "0001", "levtype": "sfc", "type": "pf"}

    def test_timeseries_invalid(self):

        with pytest.raises(ValueError):
            PolytopeMars(self.options,self.config).extract("invalid")

        with pytest.raises(KeyError):
            PolytopeMars(self.options,self.config).extract({"hello": "world"})

        with pytest.raises(KeyError):
            PolytopeMars(self.options,self.config).extract(json.dumps({"hello": "world"}))

        # 'step' is invalid in the request
        self.request["step"] = "0"
        with pytest.raises(KeyError):
            PolytopeMars(self.options,self.config).extract(self.request)

    def test_timeseries_valid(self):
        
        PolytopeMars(self.config, self.options).extract(self.request)