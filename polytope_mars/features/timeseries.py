import logging

from polytope_feature import shapes

from ..feature import Feature
from ..utils.areas import field_area


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

        if "range" in feature_config:
            feature_config.pop("range")

        assert len(feature_config) == 0, f"Unexpected keys in config: {feature_config.keys()}"

    def get_shapes(self):
        # Time-series is a squashed box from start_step to start_end for each point  # noqa: E501
        return [
            shapes.Union(
                [self.axes[0], self.axes[1]],
                *[
                    shapes.Point(
                        [self.axes[0], self.axes[1]],
                        [[p[0], p[1]]],
                        method="nearest",  # noqa: E501
                    )
                    for p in self.points
                ],
            ),
            # shapes.Span("step", self.start_step, self.end_step),
        ]

    def incompatible_keys(self):
        return ["levellist"]

    def coverage_type(self):
        return "PointSeries"

    def name(self):
        return "Time Series"

    def required_keys(self):
        return ["type", "points", "time_axis"]

    def required_axes(self):
        return ["latitude", "longitude"]

    def parse(self, request, feature_config):
        logging.debug("Feature config: %s", feature_config)
        # if isinstance(feature_config["time_axis"], list):
        #    if "step" not in feature_config["time_axis"] and "date" not in feature_config["time_axis"]:
        #        raise ValueError("Timeseries axes must be step or date")
        if feature_config["time_axis"] != "step" and feature_config["time_axis"] != "date":  # noqa: E501
            raise ValueError("Timeseries axes must be step or date")

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
        if time_axis in request and "range" in feature_config:
            raise ValueError("Timeseries time_axis is overspecified in request")
        if time_axis not in request and "range" not in feature_config:  # noqa: E501
            raise ValueError("Timeseries time_axis is underspecified in request")

        if "range" in feature_config:
            if feature_config["range"]["start"] < 0:
                raise ValueError("Timeseries range start must be greater than 0")
            if isinstance(feature_config["range"], dict):
                request[time_axis] = (
                    f"{feature_config['range']['start']}/to/{feature_config['range']['end']}"  # noqa: E501
                )
                if "interval" in feature_config["range"]:
                    request[time_axis] += f"/by/{feature_config['range']['interval']}"
        logging.debug("After parse request: %s", request)

        return request
