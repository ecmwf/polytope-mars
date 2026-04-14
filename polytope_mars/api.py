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
from covjsonkit.utils import merge_coverage_collections
from polytope_feature import shapes
from polytope_feature.polytope import Polytope, Request

from .config import PolytopeMarsConfig
from .features.boundingbox import BoundingBox
from .features.circle import Circle
from .features.frame import Frame
from .features.path import Path
from .features.polygon import Polygons
from .features.position import Position
from .features.shpfile import Shapefile
from .features.timeseries import TimeSeries
from .features.verticalprofile import VerticalProfile
from .utils.datetimes import (
    convert_timestamp,
    find_step_intervals,
    from_range_to_list_date,
    from_range_to_list_num,
)

features = {
    "timeseries": TimeSeries,
    "verticalprofile": VerticalProfile,
    "boundingbox": BoundingBox,
    "frame": Frame,
    "trajectory": Path,
    "shapefile": Shapefile,
    "polygon": Polygons,
    "circle": Circle,
    "position": Position,
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
        self.split_request = False

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

        self.format = request.pop("format", "covjson")
        if self.format not in ("covjson", "tensogram"):
            raise ValueError(f"Unsupported format '{self.format}'. Supported formats: covjson, tensogram")

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
                    elif "month" in feature_config["axes"]:
                        raise ValueError(
                            "Month axis not supported in 'axes' keyword, must be in 'time_axis'"
                        )  # noqa: E501

            except KeyError:
                raise KeyError("The timeseries feature requires a 'time_axis' keyword")  # noqa: E501
        else:
            timeseries_type = None  # noqa: F841

        feature = self._feature_factory(feature_type, feature_config, self.conf)  # noqa: E501

        feature.validate(request, feature_config_copy)

        logging.debug("Unparsed request: %s", request)
        logging.debug("Feature dictionary: %s", feature_config_copy)

        request = feature.parse(request, feature_config_copy)

        self.split_request = feature.split_request()

        logging.debug("Self split: %s", self.split_request)
        logging.debug("Parsed request: %s", request)

        # Initialise the result container based on format
        if self.format == "tensogram":
            from .encoders.tensogram_encoder import TensogramResult

            self.coverage = TensogramResult()
        else:
            self.coverage = {}

        if self.split_request:
            # If the request is split, we need to handle it differently
            dates = from_range_to_list_date(request["date"])
            for date in dates.split("/"):
                if "number" in request:
                    numbers = from_range_to_list_num(request["number"])
                    if len(numbers) > 10:
                        for number in from_range_to_list_num(request["number"]):
                            copied_request = request.copy()
                            copied_request["date"] = date
                            copied_request["number"] = number
                            coverage = self.retrieve_data(copied_request, feature_type, feature)  # noqa: E501
                            self._merge_coverage(coverage)
                    else:
                        copied_request = request.copy()
                        copied_request["date"] = date
                        coverage = self.retrieve_data(copied_request, feature_type, feature)
                        self._merge_coverage(coverage)
                else:
                    copied_request = request.copy()
                    copied_request["date"] = date
                    coverage = self.retrieve_data(copied_request, feature_type, feature)
                    self._merge_coverage(coverage)

        else:
            self.coverage = self.retrieve_data(request, feature_type, feature)  # noqa: E501

        return self.coverage

    def _create_base_shapes(self, request: dict, feature_type) -> List[shapes.Shape]:
        base_shapes = []

        if (
            "dataset" in request
            and request["dataset"] == "climate-dt"  # noqa: W503
            and (feature_type == "timeseries" or feature_type == "polygon")  # noqa: W503
        ) or (request["class"] == "ng" and (feature_type == "timeseries" or feature_type == "polygon")):
            for k, v in request.items():
                split = str(v).split("/")

                if k == "param":
                    try:
                        int(split[0])
                    except (ValueError, TypeError):
                        new_split = []
                        for s in split:
                            new_split.append(get_param_ids(self.conf.coverageconfig)[s])  # noqa: E501
                        split = new_split

                # ALL -> All
                if len(split) == 1 and split[0] == "ALL":
                    base_shapes.append(shapes.All(k))

                # month / year axes: values are always passed as integers
                elif k in ("month", "year"):
                    # Single integer value -> Select
                    if len(split) == 1:
                        base_shapes.append(shapes.Select(k, [int(split[0])]))

                    # Range a/to/b -> Span with integer bounds
                    elif len(split) == 3 and split[1] == "to":
                        base_shapes.append(shapes.Span(k, lower=int(split[0]), upper=int(split[2])))

                    # Range a/to/b/by/step -> Select of integers
                    elif "by" in split:
                        step = int(split[-1])
                        expansion = list(range(int(split[0]), int(split[2]) + 1, step))
                        base_shapes.append(shapes.Select(k, expansion))

                    # List of individual integer values -> Select
                    else:
                        base_shapes.append(shapes.Select(k, [int(s) for s in split]))

                # Single value -> Select
                elif len(split) == 1:
                    if k == "date":
                        split[0] = pd.Timestamp(split[0])
                    if k == "time":
                        split[0] = convert_timestamp(split[0])
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
                        start = convert_timestamp(split[0])
                        end = convert_timestamp(split[2])
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
                            start = convert_timestamp(split[0])
                            end = convert_timestamp(split[2])
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
                            start = convert_timestamp(split[0])
                            end = convert_timestamp(split[2])
                            times = pd.date_range(start=start, end=end, freq=f"{split[-1]}H")
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
                            times.append(convert_timestamp(s))
                        split = times
                    base_shapes.append(shapes.Select(k, split))
        else:
            # When the time axis is month or year, there is no "date" key in
            # the request – "time" may also be absent.  Only pop "time" when it
            # is actually present so we don't break month/year requests.
            time = []
            if "time" in request:
                time = request.pop("time").replace(":", "")
                time = time.split("/")
                if "to" in time:
                    start = convert_timestamp(time[0])
                    end = convert_timestamp(time[2])
                    if "by" in time:
                        times = pd.date_range(start=start, end=end, freq=f"{time[-1]}H")
                    else:
                        times = pd.date_range(start=start, end=end, freq="1H")
                    time = times.strftime("%H:%M:%S").tolist()

            for k, v in request.items():
                split = str(v).split("/")

                if k == "param":
                    try:
                        int(split[0])
                    except (ValueError, TypeError):
                        new_split = []
                        for s in split:
                            new_split.append(get_param_ids(self.conf.coverageconfig)[s])  # noqa: E501
                        split = new_split

                # ALL -> All
                if len(split) == 1 and split[0] == "ALL":
                    base_shapes.append(shapes.All(k))

                # month / year axes: values are always passed as integers
                elif k in ("month", "year"):
                    # Single integer value -> Select
                    if len(split) == 1:
                        base_shapes.append(shapes.Select(k, [int(split[0])]))

                    # Range a/to/b -> Span with integer bounds
                    elif len(split) == 3 and split[1] == "to":
                        base_shapes.append(shapes.Span(k, lower=int(split[0]), upper=int(split[2])))

                    # Range a/to/b/by/step -> Select of integers
                    elif "by" in split:
                        step = int(split[-1])
                        expansion = list(range(int(split[0]), int(split[2]) + 1, step))
                        base_shapes.append(shapes.Select(k, expansion))

                    # List of individual integer values -> Select
                    else:
                        base_shapes.append(shapes.Select(k, [int(s) for s in split]))

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
                            base_shapes.append(shapes.Select(k, dates))
                        elif k == "step":
                            steps = find_step_intervals(split[0], split[2], split[-1])
                            base_shapes.append(shapes.Select(k, steps))
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

    def _merge_coverage(self, coverage):
        """Merge a sub-request coverage into self.coverage."""
        if self.format == "tensogram":
            self.coverage.merge(coverage)
        else:
            self.coverage = merge_coverage_collections(self.coverage, coverage)

    def _feature_factory(self, feature_name, feature_config, config=None):
        feature_class = features.get(feature_name)
        if feature_class:
            return feature_class(feature_config, config)
        else:
            raise NotImplementedError(f"Feature '{feature_name}' not found")

    def retrieve_data(self, request, feature_type, feature):
        """
        Retrieves data from the Polytope engine based on the request and feature type.
        This method sets up the Polytope engine, prepares the request, and encodes the
        result into the requested output format (covjson or tensogram).

        :param request: The request dictionary containing parameters for data retrieval.
        :param feature_type: The type of feature being requested (e.g., 'timeseries', 'polygon').
        :param feature: The feature object that contains the logic for data retrieval.
        :return: The coverage data in the requested format.
        """
        shapes = self._create_base_shapes(request, feature_type)

        shapes.extend(feature.get_shapes())

        preq = Request(*shapes)

        start = time.time()
        logging.info(f"{self.id}: Gribjump/setup time start: {start}")  # noqa: E501

        if self.conf.datacube.type == "gribjump":
            fdbdatacube = gj.GribJump()
        else:
            raise NotImplementedError(f"Datacube type '{self.conf.datacube.type}' not found")  # noqa: E501

        logging.debug(f"Send log_context to polytope: {self.log_context}")
        self.api = Polytope(
            datacube=fdbdatacube,
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
        logging.debug(result.pprint())

        end = time.time()
        delta = end - start
        logging.debug(f"{self.id}: Polytope time end: {end}")  # noqa: E501
        logging.info(f"{self.id}: Polytope time taken: {delta}")  # noqa: E501
        start = time.time()

        # ---- Encode the result into the requested format ----
        if self.format == "tensogram":
            logging.info(f"{self.id}: Tensogram encoding time start: {start}")  # noqa: E501
            from .encoders.tensogram_encoder import TensogramEncoder

            encoder = TensogramEncoder(self.conf.coverageconfig, feature_type)
            coverage = self._encode_with_walker(encoder, request, feature_type, result)

            end = time.time()
            delta = end - start
            logging.info(f"{self.id}: Tensogram encoding time taken: {delta}")  # noqa: E501
        else:
            logging.info(f"{self.id}: Covjson time start: {start}")  # noqa: E501
            encoder = Covjsonkit(self.conf.coverageconfig.model_dump()).encode(
                "CoverageCollection", feature_type
            )  # noqa: E501
            coverage = self._encode_with_walker(encoder, request, feature_type, result)

            end = time.time()
            delta = end - start
            logging.debug(f"{self.id}: Covjsonkit time end: {end}")  # noqa: E501
            logging.info(f"{self.id}: Covjsonkit time taken: {delta}")  # noqa: E501

        return coverage

    def _encode_with_walker(self, encoder, request, feature_type, result):
        """Select the correct tree-walk variant and encode the result.

        Both covjsonkit encoders and TensogramEncoder implement the same
        ``from_polytope`` / ``from_polytope_step`` / ``from_polytope_month``
        interface, so the routing logic is shared.
        """
        if "dataset" in request:
            if request["dataset"] == "climate-dt":
                if request.get("stream") == "clmn":
                    return encoder.from_polytope_month(result)
                elif feature_type in ("timeseries", "polygon"):
                    return encoder.from_polytope_step(result)
                else:
                    return encoder.from_polytope(result)
            else:
                return encoder.from_polytope(result)
        elif request.get("class") == "ng":
            if feature_type in ("timeseries", "polygon"):
                return encoder.from_polytope_step(result)
            else:
                return encoder.from_polytope(result)
        else:
            return encoder.from_polytope(result)
