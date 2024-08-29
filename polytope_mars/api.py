import json
import logging
from typing import List

import pandas as pd
import pygribjump as gj
from conflator import Conflator
from covjsonkit.api import Covjsonkit
from polytope import shapes
from polytope.engine.hullslicer import HullSlicer
from polytope.polytope import Polytope, Request

from .config import PolytopeMarsConfig
from .features.boundingbox import BoundingBox
from .features.frame import Frame
from .features.path import Path
from .features.shpfile import Shapefile
from .features.timeseries import TimeSeries
from .features.verticalprofile import VerticalProfile
from .features.wkt import Wkt

features = {
    "timeseries": TimeSeries,
    "verticalprofile": VerticalProfile,
    "boundingbox": BoundingBox,
    "frame": Frame,
    "path": Path,
    "shapefile": Shapefile,
    "wkt": Wkt,
}


class PolytopeMars:
    def __init__(self, config=None):
        # Initialise polytope-mars configuration

        # If no config check default locations
        if config is None:
            self.conf = Conflator(
                app_name="polytope_mars", model=PolytopeMarsConfig
            ).load()
        # else initialise with provided config
        else:
            self.conf = PolytopeMarsConfig.model_validate(config)

        self.coverage = {}

    def extract(self, request):
        # request expected in JSON or dict
        if not isinstance(request, dict):
            try:
                request = json.loads(request)
            except ValueError:
                raise ValueError(
                    "Request not in JSON format or python dictionary"
                )  # noqa: E501

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

        if feature_type == "timeseries":
            timeseries_type = feature_config["axis"]
        else:
            timeseries_type = None

        feature = self._feature_factory(feature_type, feature_config)

        feature.validate(request)

        shapes = self._create_base_shapes(request)

        shapes.extend(feature.get_shapes())

        preq = Request(*shapes)

        if self.conf.datacube.type == "gribjump":
            fdbdatacube = gj.GribJump()
        else:
            raise NotImplementedError(
                f"Datacube type '{self.conf.datacube.type}' not found"
            )  # noqa: E501
        slicer = HullSlicer()
        self.api = Polytope(
            datacube=fdbdatacube,
            engine=slicer,
            options=self.conf.options.model_dump(),
        )
        logging.debug(
            "The request we give polytope from polytope-mars are: %s", preq
        )  # noqa: E501
        result = self.api.retrieve(preq)
        encoder = Covjsonkit(self.conf.coverageconfig.model_dump()).encode(
            "CoverageCollection", feature_type
        )  # noqa: E501

        if timeseries_type == "datetime":
            self.coverage = encoder.from_polytope_step(result)
        else:
            self.coverage = encoder.from_polytope(result)

        return self.coverage

    def _create_base_shapes(self, request: dict) -> List[shapes.Shape]:
        base_shapes = []

        # TODO: not handling type conversion
        #   * strings to integers for step, number, etc.
        #   * date/times to datetime (and merging of date + time)
        #   * enforcing strings are actually strings (e.g. type=fc)

        time = request.pop("time").replace(":", "")
        # if str(time).split("/") != 1:
        #   time = str(time).split("/")
        # else:
        #   time = [time]

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
                if k == "date":
                    split[0] = pd.Timestamp(split[0] + "T" + time)
                base_shapes.append(shapes.Select(k, [split[0]]))

            # Range a/to/b, "by" not supported -> Span
            elif len(split) == 3 and split[1] == "to":
                if k == "date":
                    split[0] = pd.Timestamp(split[0] + "T" + time)
                    split[2] = pd.Timestamp(split[2] + "T" + time)
                base_shapes.append(
                    shapes.Span(k, lower=split[0], upper=split[2])
                )  # noqa: E501

            elif "by" in split:
                raise ValueError(
                    "Ranges with step-size specified with 'by' keyword is not supported"  # noqa: E501
                )

            # List of individual values -> Union of Selects
            else:
                if k == "date":
                    dates = []
                    for s in split:
                        dates.append(pd.Timestamp(s + "T" + time))
                    split = dates
                base_shapes.append(shapes.Select(k, split))

        return base_shapes

    def _feature_factory(self, feature_name, feature_config):
        feature_class = features.get(feature_name)
        if feature_class:
            return feature_class(feature_config)
        else:
            raise NotImplementedError(f"Feature '{feature_name}' not found")
