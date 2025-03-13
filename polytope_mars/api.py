import datetime
import json
import logging
import time
from typing import List

import pandas as pd
import pygribjump as gj
from conflator import Conflator
from covjsonkit.api import Covjsonkit
from covjsonkit.param_db import get_param_ids
from polytope_feature import shapes
from polytope_feature.engine.hullslicer import HullSlicer
from polytope_feature.polytope import Polytope, Request

from .config import PolytopeMarsConfig
from .features.boundingbox import BoundingBox
from .features.circle import Circle
from .features.frame import Frame
from .features.path import Path
from .features.polygon import Polygons
from .features.shpfile import Shapefile
from .features.timeseries import TimeSeries
from .features.verticalprofile import VerticalProfile

features = {
    "timeseries": TimeSeries,
    "verticalprofile": VerticalProfile,
    "boundingbox": BoundingBox,
    "frame": Frame,
    "trajectory": Path,
    "shapefile": Shapefile,
    "polygon": Polygons,
    "circle": Circle,
}


class PolytopeMars:
    def __init__(self, config=None, log_context=None):
        # Initialise polytope-mars configuration
        self.log_context = log_context
        self.id = log_context["id"] if log_context else "-1"

        # If no config check default locations
        if config is None:
            self.conf = Conflator(app_name="polytope_mars", model=PolytopeMarsConfig).load()  # noqa: E501
            logging.debug(f"{self.id}: Config loaded from file: {self.conf}")  # noqa: E501
        # else initialise with provided config
        else:
            self.conf = PolytopeMarsConfig.model_validate(config)
            logging.debug(f"{self.id}: Config loaded from dictionary: {self.conf}")  # noqa: E501

        self.coverage = {}

    def extract(self, request):
        # request expected in JSON or dict
        if not isinstance(request, dict):
            try:
                request = json.loads(request)
            except ValueError:
                raise ValueError("Request not in JSON format or python dictionary")  # noqa: E501

        # expect a "feature" key in the request
        try:
            feature_config = request.pop("feature")
            feature_config_copy = feature_config.copy()
        except KeyError:
            raise KeyError("Request does not contain a 'feature' keyword")

        try:
            format = request.pop("format")
            if format != "covjson":
                raise ValueError("Only covjson format is currently supported")
        except KeyError:
            pass

        # get feature type
        try:
            feature_type = feature_config["type"]
        except KeyError:
            raise KeyError("The 'feature' does not contain a 'type' keyword")

        if feature_type == "timeseries":
            try:
                if "time_axis" in feature_config:
                    timeseries_type = feature_config["time_axis"]
                if "axes" in feature_config:
                    if feature_config["axes"] == "step":
                        timeseries_type = "step"
                        del feature_config["axes"]
                        del feature_config_copy["axes"]
                        feature_config["time_axis"] = "step"
                        feature_config_copy["time_axis"] = "step"
                    elif "step" in feature_config["axes"]:
                        raise ValueError(
                            "Step axis not supported in 'axes' keyword, must be in 'time_axis'"
                        )  # noqa: E501
                    elif "date" in feature_config["axes"]:
                        raise ValueError(
                            "Date axis not supported in 'axes' keyword, must be in 'time_axis'"
                        )  # noqa: E501

            except KeyError:
                raise KeyError("The timeseries feature requires a 'time_axis' keyword")  # noqa: E501
        else:
            timeseries_type = None

        feature = self._feature_factory(feature_type, feature_config, self.conf)  # noqa: E501

        feature.validate(request, feature_config_copy)

        logging.debug("Unparsed request: %s", request)
        logging.debug("Feature dictionary: %s", feature_config_copy)

        request = feature.parse(request, feature_config_copy)

        logging.debug("Parsed request: %s", request)

        shapes = self._create_base_shapes(request, feature_type)

        shapes.extend(feature.get_shapes())

        preq = Request(*shapes)

        start = time.time()
        logging.info(f"{self.id}: Gribjump/setup time start: {start}")  # noqa: E501

        if self.conf.datacube.type == "gribjump":
            fdbdatacube = gj.GribJump()
        else:
            raise NotImplementedError(f"Datacube type '{self.conf.datacube.type}' not found")  # noqa: E501
        slicer = HullSlicer()

        logging.debug(f"Send log_context to polytope: {self.log_context}")
        self.api = Polytope(
            datacube=fdbdatacube,
            engine=slicer,
            options=self.conf.options.model_dump(),
            context=self.log_context,
        )

        end = time.time()
        delta = end - start
        logging.debug(f"{self.id}: Gribjump/setup time end: {end}")  # noqa: E501
        logging.info(f"{self.id}: Gribjump/setup time taken: {delta}")  # noqa: E501

        logging.debug(f"{self.id}: The request we give polytope from polytope-mars is: {preq}")  # noqa: E501
        start = time.time()
        logging.info(f"{self.id}: Polytope time start: {start}")  # noqa: E501

        result = self.api.retrieve(preq)

        end = time.time()
        delta = end - start
        logging.debug(f"{self.id}: Polytope time end: {end}")  # noqa: E501
        logging.info(f"{self.id}: Polytope time taken: {delta}")  # noqa: E501
        start = time.time()
        logging.info(f"{self.id}: Covjson time start: {start}")  # noqa: E501
        encoder = Covjsonkit(self.conf.coverageconfig.model_dump()).encode(
            "CoverageCollection", feature_type
        )  # noqa: E501

        if timeseries_type == "date":
            self.coverage = encoder.from_polytope_step(result)
        else:
            self.coverage = encoder.from_polytope(result)

        end = time.time()
        delta = end - start
        logging.debug(f"{self.id}: Covjsonkit time end: {end}")  # noqa: E501
        logging.info(f"{self.id}: Covjsonkit time taken: {delta}")  # noqa: E501

        return self.coverage

    def convert_timestamp(self, timestamp):
        # Ensure the input is a string
        timestamp = str(timestamp)

        # Pad the timestamp with leading zeros if necessary
        timestamp = timestamp.zfill(4)

        # Insert colons to format as HH:MM:SS
        formatted_timestamp = f"{timestamp[:2]}:{timestamp[2:]}:00"

        return formatted_timestamp

    def _create_base_shapes(self, request: dict, feature_type) -> List[shapes.Shape]:
        base_shapes = []

        if "dataset" in request and request["dataset"] == "climate-dt" and feature_type == "timeseries":  # noqa: E501
            for k, v in request.items():
                split = str(v).split("/")

                if k == "param":
                    try:
                        int(split[0])
                    except:  # noqa: E722
                        new_split = []
                        for s in split:
                            new_split.append(get_param_ids(self.conf.coverageconfig)[s])  # noqa: E501
                        split = new_split

                # ALL -> All
                if len(split) == 1 and split[0] == "ALL":
                    base_shapes.append(shapes.All(k))

                # Single value -> Select
                elif len(split) == 1:
                    if k == "date":
                        split[0] = pd.Timestamp(split[0])
                    if k == "time":
                        split[0] = self.convert_timestamp(split[0])
                    base_shapes.append(shapes.Select(k, split))

                # Range a/to/b, "by" not supported -> Span
                elif len(split) == 3 and split[1] == "to":
                    # if date then only get time of dates in span not
                    # all in times within date
                    if k == "date":
                        start = pd.Timestamp(split[0])
                        end = pd.Timestamp(split[2])
                        base_shapes.append(shapes.Span(k, lower=start, upper=end))
                    elif k == "time":
                        start = self.convert_timestamp(split[0])
                        end = self.convert_timestamp(split[2])
                        base_shapes.append(shapes.Span(k, lower=start, upper=end))
                    else:
                        base_shapes.append(shapes.Span(k, lower=split[0], upper=split[2]))  # noqa: E501

                elif "by" in split:

                    if split[-1] == "1":
                        if k == "date":
                            start = pd.Timestamp(split[0])
                            end = pd.Timestamp(split[2])
                            base_shapes.append(shapes.Span(k, lower=start, upper=end))
                        elif k == "time":
                            start = self.convert_timestamp(split[0])
                            end = self.convert_timestamp(split[2])
                            base_shapes.append(shapes.Span(k, lower=start, upper=end))
                        else:
                            base_shapes.append(shapes.Span(k, lower=split[0], upper=split[2]))  # noqa: E501
                    else:
                        if k == "date":
                            start = pd.Timestamp(split[0])
                            end = pd.Timestamp(split[2])
                            timestamps = pd.date_range(start=start, end=end, freq=f"{split[-1]}D")
                            base_shapes.append(shapes.Select(k, timestamps.tolist()))
                        elif k == "time":
                            start = self.convert_timestamp(split[0])
                            end = self.convert_timestamp(split[2])
                            times = pd.date_range(start=start, end=end, freq=f"{split[-1]}H")
                            # print(times.strftime("%H%M").tolist())
                            base_shapes.append(shapes.Select(k, times.strftime("%H:%M:%S").tolist()))
                            # base_shapes.append(shapes.Span(k, lower=start, upper=end))
                            # base_shapes.append(shapes.Span(k, lower=start, upper=end))
                        # raise ValueError("Ranges with step-size specified with 'by' keyword is not supported")  # noqa: E501

                # List of individual values -> Union of Selects
                else:
                    if k == "date":
                        dates = []
                        for s in split:
                            dates.append(pd.Timestamp(s))
                        split = dates
                    if k == "time":
                        times = []
                        for s in split:
                            times.append(self.convert_timestamp(s))
                        split = times
                    base_shapes.append(shapes.Select(k, split))
        else:
            time = request.pop("time").replace(":", "")
            time = time.split("/")
            if "to" in time:
                start = self.convert_timestamp(time[0])
                end = self.convert_timestamp(time[2])
                if "by" in time:
                    times = pd.date_range(start=start, end=end, freq=f"{time[-1]}H")
                else:
                    times = pd.date_range(start=start, end=end, freq="1H")
                time = times.strftime("%H:%M:%S").tolist()
                # raise NotImplementedError("Time ranges with 'to' keyword not supported yet")  # noqa: E501

            for k, v in request.items():
                split = str(v).split("/")

                if k == "param":
                    try:
                        int(split[0])
                    except:  # noqa: E722
                        new_split = []
                        for s in split:
                            new_split.append(get_param_ids(self.conf.coverageconfig)[s])  # noqa: E501
                        split = new_split

                # ALL -> All
                if len(split) == 1 and split[0] == "ALL":
                    base_shapes.append(shapes.All(k))

                # Single value -> Select
                elif len(split) == 1:
                    if k == "date":
                        if int(split[0]) < 0:
                            split[0] = str(
                                (
                                    datetime.datetime.now() + datetime.timedelta(days=int(split[0]))
                                ).strftime(  # noqa: E501
                                    "%Y%m%d"
                                )  # noqa: E501
                            )
                        new_split = []
                        for t in time:
                            new_split.append(pd.Timestamp(split[0] + "T" + t))
                        split = new_split
                    base_shapes.append(shapes.Select(k, split))

                # Range a/to/b, "by" not supported -> Span
                elif len(split) == 3 and split[1] == "to":
                    # if date then only get time of dates in span not
                    # all in times within date
                    if k == "date":
                        start = pd.Timestamp(split[0] + "T" + time[0])
                        end = pd.Timestamp(split[2] + "T" + time[-1])
                        dates = []
                        for s in pd.date_range(start, end):
                            for t in time:
                                dates.append(pd.Timestamp(s.strftime("%Y%m%d") + "T" + t))
                            # dates.append(s)
                        base_shapes.append(shapes.Select(k, dates))
                    else:
                        base_shapes.append(shapes.Span(k, lower=split[0], upper=split[2]))  # noqa: E501

                elif "by" in split:
                    if split[-1] == "1":
                        if k == "date":
                            start = pd.Timestamp(split[0] + "T" + time[0])
                            end = pd.Timestamp(split[2] + "T" + time[-1])
                            dates = []
                            for s in pd.date_range(start, end):
                                for t in time:
                                    dates.append(pd.Timestamp(s.strftime("%Y%m%d") + "T" + t))
                                # dates.append(s)
                            base_shapes.append(shapes.Select(k, dates))
                        else:
                            base_shapes.append(shapes.Span(k, lower=split[0], upper=split[2]))
                    else:
                        if k == "date":
                            start = pd.Timestamp(split[0] + "T" + time[0])
                            end = pd.Timestamp(split[2] + "T" + time[-1])
                            dates = []
                            for s in pd.date_range(start, end, freq=f"{split[-1]}D"):
                                for t in time:
                                    dates.append(pd.Timestamp(s.strftime("%Y%m%d") + "T" + t))
                                # dates.append(s)
                            base_shapes.append(shapes.Select(k, dates))
                        else:
                            expansion = list(range(int(split[0]), int(split[2]), int(split[-1])))
                            base_shapes.append(shapes.Select(k, expansion))

                # List of individual values -> Union of Selects
                else:
                    if k == "date":
                        dates = []
                        for s in split:
                            for t in time:
                                dates.append(pd.Timestamp(s + "T" + t))
                        split = dates
                    base_shapes.append(shapes.Select(k, split))

        return base_shapes

    def _feature_factory(self, feature_name, feature_config, config=None):
        feature_class = features.get(feature_name)
        if feature_class:
            return feature_class(feature_config, config)
        else:
            raise NotImplementedError(f"Feature '{feature_name}' not found")
