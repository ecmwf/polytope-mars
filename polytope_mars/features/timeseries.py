import logging

from ..feature import Feature
from ..utils.areas import field_area
from ..utils.labels import tagged_point_union, validate_labels


class TimeSeries(Feature):
    def __init__(self, feature_config, client_config):
        assert feature_config.pop("type") == "timeseries"
        # self.start_step = config.pop("start", None)
        # self.end_step = config.pop("end", None)
        self.axes = feature_config.pop("axes", [])
        self.time_axis = feature_config.pop("time_axis", [])

        self.max_size = client_config.polygonrules.max_area

        if self.axes != []:
            if not isinstance(self.axes, list):
                self.axes = ["latitude", "longitude"]
            if self.axes == ["step"] or self.axes == ["date"]:
                self.axes = ["latitude", "longitude"]
        else:
            self.axes = ["latitude", "longitude"]

        self.points = feature_config.pop("points", [])
        self.labels = feature_config.pop("labels", None)

        if "range" in feature_config:
            feature_config.pop("range")

        assert len(feature_config) == 0, f"Unexpected keys in config: {feature_config.keys()}"

    def get_shapes(self):
        # Union of tagged single Points until polytope keeps per-point tags on a multi-point Point
        # (see TIMESERIES_LABELS.md); then tagged_multi_point can be used instead.
        return [tagged_point_union([self.axes[0], self.axes[1]], self.points, self.labels)]

    def incompatible_keys(self):
        return ["levellist"]

    def coverage_type(self):
        return "PointSeries"

    def name(self):
        return "Time Series"

    def uncompressed_axes(self):
        # Workaround until polytope keeps tags per value: a compressed longitude node can hold the
        # cells of several requested points with one combined tag set, so labels can't be assigned
        # per cell. With longitude uncompressed each cell has its own node and tags.
        return ["longitude"]

    def required_keys(self):
        return ["type", "points", "time_axis"]

    def required_axes(self):
        return ["latitude", "longitude"]

    def allowed_time_axis(self):
        return ["step", "date", "month", "year", "hdate"]

    def parse(self, request, feature_config):
        logging.debug("Feature config: %s", feature_config)
        # if isinstance(feature_config["time_axis"], list):
        #    if "step" not in feature_config["time_axis"] and "date" not in feature_config["time_axis"]:
        #        raise ValueError("Timeseries axes must be step or date")
        if feature_config["time_axis"] not in self.allowed_time_axis():  # noqa: E501
            raise ValueError(f"Timeseries axes must be in {self.allowed_time_axis()}")

        area = field_area(request, len(feature_config["points"]))

        if area > self.max_size:
            raise ValueError(
                f"Number of coordinates*fields for timeseries {area} exceeds total number allowed, please reduce the number of coordinates or fields requested"  # noqa: E501
            )

        if isinstance(feature_config["time_axis"], list):
            if "step" in feature_config["time_axis"]:
                time_axis = "step"
                feature_config["time_axis"].remove("step")
            if "date" in feature_config["time_axis"]:
                time_axis = "date"
                feature_config["time_axis"].remove("date")
        else:
            time_axis = feature_config["time_axis"]

        if len(feature_config["points"][0]) != 2:
            raise ValueError("Timeseries must have only two values in points")
        validate_labels(self.labels, len(feature_config["points"]), "Timeseries", "points")
        if time_axis in request and "range" in feature_config:
            raise ValueError("Timeseries time_axis is overspecified in request")
        if time_axis not in request and "range" not in feature_config:  # noqa: E501
            raise ValueError("Timeseries time_axis is underspecified in request")

        if "range" in feature_config:
            if feature_config["range"]["start"] < 0:
                raise ValueError("Timeseries range start must be greater than 0")
            if isinstance(feature_config["range"], dict):
                time_range = f"{feature_config['range']['start']}/to/{feature_config['range']['end']}"
                request[time_axis] = time_range  # noqa: E501
                if "interval" in feature_config["range"]:
                    request[time_axis] += f"/by/{feature_config['range']['interval']}"
        logging.debug("After parse request: %s", request)

        return request
