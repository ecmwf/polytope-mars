import numpy as np
from earthkit import data

from polytope.datacube.backends.xarray import XArrayDatacube
from polytope.engine.hullslicer import HullSlicer
from polytope.polytope import Polytope, Request
from polytope.shapes import Box, Select, Span, Disk
import json
from output_to_coverage import convert_to_coverage, convert_to_pointseries_coverage

request = {
    "class": "od",
    "stream" : "oper",
    "type" : "fc",
    "date" : "20170101/to/20170102",
    "time" : "00:00:00",
    "step" : "0",  # Span
    "levtype" : "pl",
    "expver" : 1, 
    "levelist" : "1/2/7/100/150/700/800/850", # Span
    "extraction" : {
        "point" : [3, 7] # Select
    },
    "format": "coverageJSON" # JSON, FlatJSON
}



class Time_Series:
    def setup_method(self, request):

        ds = data.from_source("file", "./era5-test.grib")
        self.array = ds.to_xarray().isel(step=0).t
        self.xarraydatacube = XArrayDatacube(self.array)
        self.slicer = HullSlicer()
        options = {"latitude": {"transformation": {"reverse": {True}}},
           "isobaricInhPa": {"transformation": {"reverse": {True}}}}
        self.API = Polytope(datacube=self.array, engine=self.slicer, axis_options=options)
        self.request = request
        self.parse_request(request)


    def time_series(self):
        if self.shape == 'point':
            request = Request(
                Span("number", 0.0, self.num),
                Span("isobaricInhPa", self.min_height, self.max_height),
                Span("time", self.start_time, self.end_time),
                Select("latitude", self.lat),
                Select("longitude", self.long),
                Span("step", np.timedelta64(self.min_step, "s"), np.timedelta64(self.max_step, "s") ),
            )
        elif self.shape == 'disk':
            request = Request(
                Span("number", 0.0, self.num),
                Span("isobaricInhPa", self.min_height, self.max_height),
                Span("time", self.start_time, self.end_time),
                Disk(["latitude", "longitude"], [self.lat, self.long], [1, 1]),
                Select("step", [np.timedelta64(self.step, "s")]),
            )
        elif self.shape == 'box':
            request = Request(
                Span("number", 0.0, self.num),
                Span("isobaricInhPa", self.min_height, self.max_height),
                Span("time", self.start_time, self.end_time),
                Box(["latitude", "longitude"], lower_corner=[self.lat[0], self.long[0]], upper_corner=[self.lat[1], self.long[1]]),
                Select("step", [np.timedelta64(self.step, "s")]),
            )

        result = self.API.retrieve(request)
        result.pprint()
        cj = convert_to_pointseries_coverage(self.array, result, self.request)
        json.dump( cj, open( "time_series.covjson", 'w' ) )
        return result
    

    def parse_request(self, request):
        self.num = request["expver"]
        self.min_height = request["levelist"].split('/')[0]
        self.max_height = request["levelist"].split('/')[-1]
        self.start_time = request["date"].split('/')[0] + "T" + request["time"]
        self.end_time = request["date"].split('/')[-1] + "T" + request["time"]
        self.lat = []
        self.long = []
        self.shape = 'point'
        if list(request['extraction'].keys())[0] == 'point':
            it = iter(request["extraction"]["point"])
            for point1, point2 in zip(it, it):
                self.lat.append(point1)
                self.long.append(point2)
            self.shape = 'point'
        elif list(request['extraction'].keys())[0] == 'disk':
            it = iter(request["extraction"]["points"])
            for point1, point2 in zip(it, it):
                self.lat.append(point1)
                self.long.append(point2)
            self.shape = 'disk'
        elif list(request['extraction'].keys())[0] == 'box':
            it = iter(request["extraction"]["points"])
            for point1, point2 in zip(it, it):
                self.lat.append(point1)
                self.long.append(point2)
            self.shape = 'box'
        self.min_step = request["step"]
        self.max_step = request["step"]
    