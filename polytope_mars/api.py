import json
import logging
from eccovjson.api import Eccovjson

from typing import List

from .features.timeseries import TimeSeries
from .features.verticalprofile import VerticalProfile
from .features.boundingbox import BoundingBox
from polytope import polytope, shapes
from polytope.polytope import Polytope, Request
from polytope.datacube.backends.fdb import FDBDatacube
from polytope.engine.hullslicer import HullSlicer

features = {
    "timeseries": TimeSeries,
    "verticalprofile": VerticalProfile,
    "boundingbox": BoundingBox
}


class PolytopeMars():

    def __init__(self, datacube_config, datacube_options):
        # Initialise polytope
        fdbdatacube = FDBDatacube(datacube_config, axis_options=datacube_options)
        slicer = HullSlicer()
        self.api = Polytope(datacube=fdbdatacube, engine=slicer)

        self.coverage = {}

    def extract(self, request):

        # request expected in JSON or dict
        if not isinstance(request, dict):
            try:
                request = json.loads(request)
            except ValueError:
                raise ValueError("Request not in JSON format or python dictionary")

        # expect a "feature" key in the request
        try:
            feature_config = request.pop("feature")
        except KeyError:
            raise KeyError("Request does not contain a 'feature' keyword")

        # get feature type
        try:
            feature_type = feature_config["type"]
        except KeyError:
            raise KeyError("The 'feature' does not contain a 'type' keyword")

        feature = self._feature_factory(feature_type, feature_config)

        feature.validate(request)

        shapes = self._create_base_shapes(request)

        shapes.extend(feature.get_shapes())

        preq = Request(*shapes)

        # TODO: make polytope request to get data

        result = self.api.retrieve(preq)
        #result.pprint()

        # TODO: convert output to coveragejson (defer to feature specialisation to handle particular outputs?)
        print(feature_type)
        encoder = Eccovjson().encode(
            "CoverageCollection", feature_type
        )
        if feature_type == "timeseries":
            request = self._parse_request(feature, request)

        self.coverage = encoder.from_polytope(result, request)
        #with open('result.covjson', 'w') as fp:
        #    json.dump(self.coverage, fp)

        return self.coverage

    def _create_base_shapes(self, request: dict) -> List[shapes.Shape]:

        base_shapes = []

        # TODO: not handling type conversion
        #   * strings to integers for step, number, etc.
        #   * date/times to datetime (and merging of date + time)
        #   * enforcing strings are actually strings (e.g. type=fc)

        time = request.pop("time").replace(":", "")
        request["date"] = request["date"] + "T" + time

        # TODO: not restricting certain keywords:
        #   * AREA, GRID
        # do we need to filter this... it will fail later anyway

        for k, v in request.items():
            split = str(v).split("/")

            # ALL -> All
            if len(split) == 1 and split[0] == "ALL":
                base_shapes.append(shapes.All(k))

            # Single value -> Select
            elif len(split) == 1:
                base_shapes.append(shapes.Select(k, [split[0]]))

            # Range a/to/b, "by" not supported -> Span
            elif len(split) == 3 and split[1] == "to":
                base_shapes.append(shapes.Span(k, lower=split[0], upper=split[2]))

            elif "by" in split:
                raise ValueError(f"Ranges with step-size specified with 'by' keyword is not supported")

            # List of individual values -> Union of Selects
            else:
                base_shapes.append(shapes.Select(k, split))

        return base_shapes

    def _feature_factory(self, feature_name, feature_config):

        feature_class = features.get(feature_name)
        if feature_class:
            return feature_class(feature_config)
        else:
            raise NotImplementedError(f"Feature '{feature_name}' not found")

    def _parse_request(self, feature, request):
        feature_start = feature.start_step
        feature_end = feature.end_step
        feature_lat = feature.points[0][0]
        feature_long = feature.points[0][1]

        request["step"] = list(range(feature_start, feature_end))
        request["latitude"] = feature_lat
        request["longitude"] = feature_long
        return request