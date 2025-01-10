import logging

from polytope_feature import shapes

from ..feature import Feature


class TimeSeries(Feature):
    def __init__(self, feature_config, client_config):
        assert feature_config.pop("type") == "timeseries"
        # self.start_step = config.pop("start", None)
        # self.end_step = config.pop("end", None)
        self.axes = feature_config.pop("axes", [])
        if not isinstance(self.axes, list):
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

    def parse(self, request, feature_config):
        logging.debug("Feature config: %s", feature_config)
        if feature_config["type"] != "timeseries":
            raise ValueError("Feature type must be timeseries")
        if isinstance(feature_config["axes"], list):
            if "step" not in feature_config["axes"] and "date" not in feature_config["axes"]:
                raise ValueError("Timeseries axes must be step or date")
        elif feature_config["axes"] != "step" and feature_config["axes"] != "date":  # noqa: E501
            raise ValueError("Timeseries axes must be step or date")

        if isinstance(feature_config["axes"], list):
            if "step" in feature_config["axes"]:
                time_axis = "step"
                feature_config["axes"].remove("step")
            if "date" in feature_config["axes"]:
                time_axis = "date"
                feature_config["axes"].remove("date")
        else:
            time_axis = feature_config["axes"]

        if len(feature_config["points"][0]) != 2:
            raise ValueError("Timeseries must have only two values in points")
        if time_axis in request and "range" in feature_config:
            raise ValueError("Timeseries axes is overspecified in request")
        if time_axis not in request and "range" not in feature_config:  # noqa: E501
            raise ValueError("Timeseries axes is underspecified in request")

        if "range" in feature_config:
            if isinstance(feature_config["range"], dict):
                request[time_axis] = (
                    f"{feature_config['range']['start']}/to/{feature_config['range']['end']}"  # noqa: E501
                )
                if "interval" in feature_config["range"]:
                    request[time_axis] += f"/by/{feature_config['range']['interval']}"
        logging.debug("After parse request: %s", request)

        return request
