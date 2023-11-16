
def convert_to_vertical_profile_coverage(array, result):
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
        zs = [coord[2] for coord in coords]


        cj = {
        "type" : "Coverage",
        "domain" : {
            "type" : "Domain",
            "domainType" : "VerticalProfile",
            "axes": {
            "x" : { "values": [coord[0]] },
            "y" : { "values": [coord[1]] },
            "z" : { "values": zs },
            "t" : { "values": [times] }
            },
            "referencing": [{
            "coordinates": ["x","y"],
            "system": {
                "type": "GeographicCRS",
                "id": "http://www.opengis.net/def/crs/OGC/1.3/CRS84"
            }
            }, {
            "coordinates": ["z"],
            "system": {
                "type": "VerticalCRS",
                "cs": {
                "csAxes": [{
                    "name": {
                    "en": "Pressure"
                    },
                    "direction": "down",
                    "unit": {
                    "symbol": "Pa"
                    }
                }]
                }
            }
            }, {
            "coordinates": ["t"],
            "system": {
                "type": "TemporalRS",
                "calendar": "Gregorian"
            }
            }]
        },
        "parameters" : {},
        "ranges" : {}
        }

        parameter = {
            "type": "Parameter",
            "description": array.long_name,
            "unit": {"symbol": array.GRIB_units},
            "observedProperty": {
                "id": array.GRIB_shortName,
                "label": {"en": array.long_name},
            },
        }

        cj["parameters"][array.GRIB_shortName] = parameter

        for key in cj["parameters"].keys():
            cj["ranges"][key] = {
                "type": "NdArray",
                "dataType": str("float"),
                "axisNames": ["z"],
                "shape": [len(result.leaves)],
            }
            cj["ranges"][key]["values"] = [val.result[1] for val in result.leaves]  # noqa

        return cj


def convert_to_coverage(array, result):
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
                    "domainType": "MultiPointSeries",
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
                    "description": array.long_name,
                    "unit": {"symbol": array.GRIB_units},
                    "observedProperty": {
                        "id": array.GRIB_shortName,
                        "label": {"en": array.long_name},
                    },
                }

                cj["parameters"][array.GRIB_shortName] = parameter

            for key in cj["parameters"].keys():
                cj["ranges"][key] = {
                    "type": "NdArray",
                    "dataType": str("float"),
                    "axisNames": ["x", "y", "z"],
                    "shape": [len(result.leaves)],
                }
                cj["ranges"][key]["values"] = [val.result[1] for val in result.leaves]  # noqa

        return cj

def convert_to_pointseries_coverage(array, result, request):

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

    cj = {
                "type": "CoverageCollection",
                "domainType" : "PointSeries",
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
                "parameters": {},
                "coverages": [{
                    "mars:metadata" : {
                        "class": request["class"],
                        "stream": request["stream"],
                        "levtype": request["levtype"],
                        "date": request["date"],
                        "step": request["step"]
                    },
                    "type" : "Coverage",
                        "domain" : {
                            "type": "Domain",
                            "axes": {
                            "x": { "values": [request['extraction']['point'][0]] },
                            "y": { "values": [request['extraction']['point'][1]] },
                            "z": { "values": [request['levelist']] },
                            "t": { "values": [times] }
                            }
                        },
                        "ranges" : {
                            array.long_name : {
                            "type" : "NdArray",
                            "dataType": "float",
                            "shape": [len(result.leaves)],
                            "axisNames": ["z"],
                            "values" : [val.result[1] for val in result.leaves]
                            }
                        }
                }
                ]
            }
    for variable in ['t']:

        parameter = {
            "type": "Parameter",
            "description": array.long_name,
            "unit": {"symbol": array.GRIB_units},
            "observedProperty": {
                "id": array.GRIB_shortName,
                "label": {"en": array.long_name},
            },
        }

        cj["parameters"][array.GRIB_shortName] = parameter

    return cj
