
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

from polytope.datacube.backends.fdb import FDBDatacube
from polytope.engine.hullslicer import HullSlicer
from polytope.polytope import Polytope, Request
from polytope.shapes import Box, Select, Disk, Span, All, Point

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

        options = {
            "values": {
                "transformation": {
                    "mapper": {"type": "octahedral", "resolution": 1280, "axes": ["latitude", "longitude"]}
                }
            },
            "date": {"transformation": {"merge": {"with": "time", "linkers": ["T", "00"]}}},
            "step": {"transformation": {"type_change": "int"}},
        }
        config = {"class": "od", "expver": "0001", "levtype": "sfc", "type": "pf"}
        fdbdatacube = FDBDatacube(config, axis_options=options)
        slicer = HullSlicer()
        self.API = Polytope(datacube=fdbdatacube, engine=slicer, axis_options=options)

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
        
        PolytopeMars(self.API).extract(self.request)

"""
request = Request(
            #Select("step", [0,1,2,3,4,5,6,7,8,9]),
            All("step"),
            Select("levtype", ["sfc"]),
            Select("date", [pd.Timestamp("20231205T000000")]),
            Select("domain", ["g"]),
            Select("expver", ["0001"]),
            Select("param", ["167"]),
            Select("class", ["od"]),
            Select("stream", ["enfo"]),
            Select("type", ["pf"]),
            Select("latitude", [0.035149384216]),
            Select("longitude", [0.0]),
            #Point(["latitude", "longitude"], [0.035149384216, 0.0], method="surronding"),
            #Box(["latitude", "longitude"], [0, 0], [0.2, 0.2]),
            Select("number", ["1","2","3","4","5"]),
            #All("number"),
        )
"""