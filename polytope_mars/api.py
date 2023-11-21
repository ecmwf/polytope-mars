import json
import logging

from typing import List

from .features.timeseries import TimeSeries
from .features.verticalprofile import VerticalProfile
from polytope import polytope, shapes

features = {
    "timeseries" : TimeSeries,
    "verticalprofile" : VerticalProfile
}


class PolytopeMars():

    def __init__(self, datacube_config):
        # Initialise polytope
        pass

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
            raise KeyError("Request does not contain a 'feature' keyword")

        feature = self._feature_factory(feature_type, feature_config)

        feature.validate(request)

        shapes = self._create_base_shapes(request)

        shapes.extend(feature.get_shapes())

        preq = polytope.Request(*shapes)

        # TODO: make polytope request to get data
        # TODO: convert output to coveragejson (defer to feature specialisation to handle particular outputs?)



    def _create_base_shapes(self, request: dict) -> List[shapes.Shape]:

        base_shapes = []

        # TODO: not handling type conversion
        #   * strings to integers for step, number, etc.
        #   * date/times to datetime (and merging of date + time)
        #   * enforcing strings are actually strings (e.g. type=fc)

        # TODO: not restricting certain keywords:
        #   * AREA, GRID
        # do we need to filter this... it will fail later anyway

        for k,v in request.items():
            split = str(v).split("/")

            # ALL -> All
            if len(split) == 1 and split[0] == "ALL":
                base_shapes.append(shapes.All(k))

            # Single value -> Select
            elif len(split) == 1:
                base_shapes.append(shapes.Select(k, split[0]))

            # Range a/to/b, "by" not supported -> Span
            elif len(split) == 3 and split[1] == "to":
                base_shapes.append(shapes.Span(k, lower=split[0], upper=split[2]))
            
            elif "by" in split:
                raise ValueError(f"Ranges with step-size specified with 'by' keyword is not supported")
            
            # List of individual values -> Union of Selects
            else:
                base_shapes.append(shapes.Union([k], *[shapes.Select(k, val) for val in split]))

        return base_shapes

    def _feature_factory(self, feature_name, feature_config):

        feature_class = features.get(feature_name)
        if feature_class:
            return feature_class(feature_config)
        else:
            raise NotImplementedError(f"Feature '{feature_name}' not found")

        

