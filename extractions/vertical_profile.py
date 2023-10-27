import numpy as np
from earthkit import data

from polytope.datacube.backends.xarray import XArrayDatacube
from polytope.engine.hullslicer import HullSlicer
from polytope.polytope import Polytope, Request
from polytope.shapes import Box, Select, Span, Disk

request = {
    "class": "od",
    "stream" : "oper",
    "type" : "fc",
    "date" : 20170101,
    "time" : 0000,
    "step" : "0",  # Span
    "levtype" : "pl",
    "levelist" : "1/2/7/100/150/700/800/850", # Span
    "extraction" : {
        "points" : [3.65, 7.86, 3.65, 7.86, 5.32, 8.89, 5.32, 8.89, 3.65, 7.86] # Select
    },
    "format": "GeoJSON" # JSON, FlatJSON
}



class VerticalProfile:
    def setup_method(self):
        #nexus_url = "https://get.ecmwf.int/test-data/polytope/test-data/era5-levels-members.grib"
        #download_test_data(nexus_url, "era5-levels-members.grib")

        ds = data.from_source("file", "./era5-test.grib")
        array = ds.to_xarray().isel(step=0).t
        self.xarraydatacube = XArrayDatacube(array)
        self.slicer = HullSlicer()
        options = {"lat": {"transformation": {"reverse": {True}}}}
        self.API = Polytope(datacube=array, engine=self.slicer, axis_options=options)

    def vertical_profile(self):
        request = Request(
            Span("number", 0.0, 6.0),
            Span("isobaricInhPa", 0.0, 850.0),
            Select("time", ["2017-01-01T00:00:00.000000000"]),
            Disk(["latitude", "longitude"], [3, 7], [3, 3]),
            Select("step", [np.timedelta64(0, "s")]),
        )

        result = self.API.retrieve(request)
        result.pprint()
        return result