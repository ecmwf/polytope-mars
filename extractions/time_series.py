import numpy as np
from earthkit import data

from polytope.datacube.backends.xarray import XArrayDatacube
from polytope.engine.hullslicer import HullSlicer
from polytope.polytope import Polytope, Request
from polytope.shapes import Box, Select, Span, Disk
import json

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
        "points" : [3, 7] # Select
    },
    "format": "GeoJSON" # JSON, FlatJSON
}



class Time_Series:
    def setup_method(self, request):
        #nexus_url = "https://get.ecmwf.int/test-data/polytope/test-data/era5-levels-members.grib"
        #download_test_data(nexus_url, "era5-levels-members.grib")

        ds = data.from_source("file", "./era5-test.grib")
        self.array = ds.to_xarray().isel(step=0).t
        self.xarraydatacube = XArrayDatacube(self.array)
        self.slicer = HullSlicer()
        options = {"latitude": {"transformation": {"reverse": {True}}},
           "isobaricInhPa": {"transformation": {"reverse": {True}}}}
        self.API = Polytope(datacube=self.array, engine=self.slicer, axis_options=options)

        self.num = request["expver"]
        self.min_height = request["levelist"].split('/')[0]
        self.max_height = request["levelist"].split('/')[-1]
        self.start_time = request["date"].split('/')[0] + "T" + request["time"]
        self.end_time = request["date"].split('/')[-1] + "T" + request["time"]
        self.lat = []
        self.long = []
        if list(request['extraction'].keys())[0] == 'points':
            it = iter(request["extraction"]["points"])
            for point1, point2 in zip(it, it):
                self.lat.append(point1)
                self.long.append(point2)
            self.shape = 'point'
        self.step = request["step"]


    def time_series(self):
        if self.shape == 'point':
            request = Request(
                Span("number", 0.0, self.num),
                Span("isobaricInhPa", self.min_height, self.max_height),
                Span("time", self.start_time, self.end_time),
                Select("latitude", self.lat),
                Select("longitude", self.long),
                Select("step", [np.timedelta64(self.step, "s")]),
            )

        result = self.API.retrieve(request)
        result.pprint()
        cj = self.convert_to_coverage(result)
        json.dump( cj, open( "vertical_profile.covjson", 'w' ) )
        return result
    
    def convert_to_coverage(self, result):
        values = [val.get_ancestors() for val in result.leaves]
        coords = []
        numbers = []
        times = []
        for ancestor in values:
            coord = [0] * 3
            for feature in ancestor:
                if str(feature).split("=")[0] == "latitude":
                    coord[0] = str(feature).split("=")[1]
                elif str(feature).split("=")[0] == "longitude":
                    coord[1] = str(feature).split("=")[1]
                elif str(feature).split("=")[0] == "isobaricInhPa":
                    coord[2] = str(feature).split("=")[1]
                elif str(feature).split("=")[0] == "number":
                    numbers.append(str(feature).split("=")[1])
                elif str(feature).split("=")[0] == "time":
                    times.append(str(feature).split("=")[1])
            coords.append(coord)

        for number in numbers:
            cj = {
                "type": "Coverage",
                "domain": {
                    "type": "Domain",
                    "domainType": "MultiPoint",
                    "axes": {
                        "t": {"values": times},
                        "composite": {"dataType": "tuple", "coordinates": ["x", "y", "z"], "values": []},
                    },
                    "referencing":[
                        {
                            "coordinates":[
                                "x",
                                "y",
                                "z"
                            ],
                            "system":{
                                "type":"GeographicCRS",
                                "id":"http://www.opengis.net/def/crs/OGC/1.3/CRS84"
                            }
                        }
                    ],
                    "number": number,
                    "valid time": str(times[0]),
                },
                "parameters": {},
                "ranges": {},
            }

            cj["domain"]["axes"]["composite"]["values"] = coords

            for variable in ['t']:

                parameter = {
                    "type": "Parameter",
                    "description": self.array.long_name,
                    "unit": {"symbol": self.array.GRIB_units},
                    "observedProperty": {
                        "id": self.array.GRIB_shortName,
                        "label": {"en": self.array.long_name},
                    },
                }

                cj["parameters"][self.array.GRIB_shortName] = parameter

            for key in cj["parameters"].keys():
                cj["ranges"][key] = {
                    "type": "NdArray",
                    "dataType": str("float"),
                    "axisNames": ["x", "y", "z"],
                    "shape": [len(result.leaves)],
                }
                cj["ranges"][key]["values"] = [val.result[1] for val in result.leaves]  # noqa

        return cj