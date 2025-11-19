import logging

from polytope_feature import shapes

from ..feature import Feature
from ..utils.areas import field_area


class Position(Feature):
    def __init__(self, feature_config, client_config):
        assert feature_config.pop("type") == "position"
        self.axes = feature_config.pop("axes", [])

        self.max_size = client_config.polygonrules.max_area

        if self.axes != []:
            if not isinstance(self.axes, list):
                self.axes = ["latitude", "longitude"]
            if self.axes == ["step"] or self.axes == ["date"]:
                raise ValueError(
                    "Position feature cannot have time axis, axes must be latitude and longitude"
                )  # noqa: E501
            for value in self.axes:
                if value not in {"latitude", "longitude"}:
                    raise ValueError("Position feature must have only latitude and longitude axes")  # noqa: E501
        else:
            self.axes = ["latitude", "longitude"]

        self.points = feature_config.pop("points", [])

        assert len(feature_config) == 0, f"Unexpected keys in config: {feature_config.keys()}"

    def get_shapes(self):
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
        ]

    def incompatible_keys(self):
        return []

    def coverage_type(self):
        return "PointSeries"

    def name(self):
        return "Position"

    def required_keys(self):
        return ["type", "points"]

    def required_axes(self):
        return ["latitude", "longitude"]

    def parse(self, request, feature_config):
        logging.debug("Feature config: %s", feature_config)

        area = field_area(request, len(feature_config["points"]))

        if area > self.max_size:
            raise ValueError(
                f"Number of coordinates*fields for timeseries {area} exceeds total number allowed, please reduce the number of coordinates or fields requested"  # noqa: E501
            )

        if len(feature_config["points"][0]) != 2:
            raise ValueError("Position must have only two values in points")

        logging.debug("After parse request: %s", request)

        return request
