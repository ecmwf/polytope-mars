import datetime
import json
import logging
import time
from typing import List
from copy import deepcopy

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
from .post_processing_functions import get_geopotential_height_request, geopotential_height_from_geopotential

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
            timeseries_type = None  # noqa: F841

        feature = self._feature_factory(feature_type, feature_config, self.conf)  # noqa: E501

        feature.validate(request, feature_config_copy)

        logging.debug("Unparsed request: %s", request)
        logging.debug("Feature dictionary: %s", feature_config_copy)

        request = feature.parse(request, feature_config_copy)

        logging.debug("Parsed request: %s", request)

        self.setup_polytope()

        if feature_type == "vertical_profile":

            # Find the interpolation options
            interpolation_options = request.get("interpolate", None)
            if interpolation_options:
                # Assert request is valid with interpolation
                assert request.get("levtype") == "hl"
                wanted_height = request.get("levelist")

                # Check we are operating on a single field
                assert self.check_single_field()
                points_of_interest = feature_config_copy["points"]
                points_geopotential_heights = []
                for point in points_of_interest:
                    # For each point in the vertical profile, extract the geopotential height

                    # Build request for geopotential height for single point for levtype=pl (only one where param=129 exists?)
                    geopotential_request, point_feature_config = get_geopotential_height_request(request, feature_config_copy, point)
                    point_feature = self._feature_factory(feature_type, point_feature_config, self.conf)
                    geopotential_coverage = self.extract_request(geopotential_request, point_feature, feature_type)
                    geopotential_xarray = geopotential_coverage.to_xarray()
                    geopotentials = geopotential_xarray.z.values
                    levelists = geopotential_xarray.levelist.values
                    geopotential_heights = [geopotential_height_from_geopotential(z) for z in geopotentials]
                    # Find which geopotential heights bound the height we are looking for

                    lower_height = None
                    lower_height_idx = None
                    upper_height = None
                    upper_height_idx = None

                    for i, v in enumerate(geopotential_heights):
                        if v <= wanted_height:
                            lower_height_idx = i
                            lower_height = v
                        if v >= wanted_height and upper_height_idx is None:
                            upper_height_idx = i
                            upper_height = v
                    # Find interpolation coefficient
                    interp_coeff = (wanted_height - lower_height) / (upper_height - lower_height)
                    # Find the corresponding levelists
                    lower_levelist = levelists[lower_height_idx]
                    upper_levelist = levelists[upper_height_idx]
                    # Extract the initial wanted param on these levelists
                    actual_request = deepcopy(geopotential_request)
                    actual_request["param"] = request["param"]
                    actual_request["levelist"] = str(lower_levelist) + "/" + str(upper_levelist)
                    point_coverage = self.extract_request(actual_request, point_feature, feature_type)
                    # Return coverage (ideally coverage with interpolated result to wanted height)

            # ONCE we have all of the heights for all points, with the interpolation method, determine which are within the height extents requested
            # FOR each point, create a new request with the right heights and finally extract...
            pass

        # # check if the request has an interpolation step
        # interpolation_options = request.get("interpolate", None)
        # if interpolation_options:
        #     # make sure it makes sense to interpolate, ie levtype is ml or pl in request
        #     # assert request.get("levtype") in ["pl", "ml"]
        #     assert request.get("levtype") == "hl"
        #     from_pl = interpolation_options.get("from_pl", False)
        #     if from_pl:
        #         levtype = "pl"
        #     else:
        #         levtype = "ml"
        #     request["levtype"] = levtype
        #     assert feature_type == "vertical_profile"
        #     geopotential_field_param = "129"

        #     # GEOPOTENTIAL REQUEST
        #     #     "class": "od",
        #     #    "date": -1,
        #     #    "expver": "0001",
        #     #    "levtype": "sfc",
        #     #    "param": "129",
        #     #    "step": "0",
        #     #    "time": "0000",
        #     #    "domain": "g",
        #     #    "stream": "oper",
        #     #    "type": "fc",

        #     geopotential_request = request.copy()
        #     geopotential_request["param"] = geopotential_field_param
        #     geopotential_request["levtype"] = "sfc"
        #     # then first extract geopotential height
        #     geopotential_coverage = self.extract_request(geopotential_request, feature, feature_type)
        #     # find the geopotential heights from the coverage
        #     # NOTE: assume we only do a single point vertical profile here
        #     geopotential_points = geopotential_coverage.to_xarray().z.values

        #     # mark interpolation options for later
        #     over_sea = interpolation_options.get("sea", False)
        #     interpolation_method = interpolation_options.get("interpolation_method", "linear")
        #     # TODO: then find out what model/pressure levels are needed from this and change request accordingly

        self.coverage = self.extract_request(request, feature, feature_type)

        return self.coverage

    def setup_polytope(self):
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

    def extract_request(self, request, feature, feature_type):
        shapes = self._create_base_shapes(request, feature_type)

        shapes.extend(feature.get_shapes())

        preq = Request(*shapes)

        start = time.time()
        logging.info(f"{self.id}: Gribjump/setup time start: {start}")  # noqa: E501

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

        # TODO: add interpolation option to decoding and change the model/pressure level if requested
        # if timeseries_type == "date":
        if "dataset" in request:
            if request["dataset"] == "climate-dt" and (feature_type == "timeseries" or feature_type == "polygon"):
                coverage = encoder.from_polytope_step(result)
            else:
                coverage = encoder.from_polytope(result)
        else:
            coverage = encoder.from_polytope(result)

        end = time.time()
        delta = end - start
        logging.debug(f"{self.id}: Covjsonkit time end: {end}")  # noqa: E501
        logging.info(f"{self.id}: Covjsonkit time taken: {delta}")  # noqa: E501
        return coverage

    def convert_timestamp(self, timestamp):
        # Ensure the input is a string
        timestamp = str(timestamp)

        # Pad the timestamp with leading zeros if necessary
        timestamp = timestamp.zfill(4)

        # Insert colons to format as HH:MM:SS
        formatted_timestamp = f"{timestamp[:2]}:{timestamp[2:]}:00"

        return formatted_timestamp

    def check_single_field(self, request: dict, feature_type) -> bool:
        single_field = True
        for k, v in request.items():
            split = str(v).split("/")
            if len(split) != 1:
                single_field = False
            elif len(split) == 1 and split[0] == "ALL":
                single_field = False
        return single_field

    def _create_base_shapes(self, request: dict, feature_type) -> List[shapes.Shape]:
        base_shapes = []

        if (
            "dataset" in request
            and request["dataset"] == "climate-dt"  # noqa: W503
            and (feature_type == "timeseries" or feature_type == "polygon")  # noqa: W503
        ):  # noqa: E501
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
