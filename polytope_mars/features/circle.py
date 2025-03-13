from polytope_feature import shapes

from ..feature import Feature
from ..utils.areas import field_area, get_circle_area_from_coords


class Circle(Feature):
    def __init__(self, feature_config, client_config):
        assert feature_config.pop("type") == "circle"
        if len(feature_config["center"][0]) < 2 or len(feature_config["center"][0]) > 3:
            raise ValueError("Circle center must have two values, latitude and longitude")
        self.center = feature_config.pop("center")
        self.max_area = client_config.polygonrules.max_area
        self.radius = feature_config.pop("radius")
        self.area = get_circle_area_from_coords(
            self.center[0][0], self.center[0][1], self.center[0][0] + self.radius, self.center[0][1] + self.radius
        )
        if self.area > client_config.polygonrules.max_area:
            raise ValueError(
                f"Area of circle {self.area} km\u00b2 exceeds the maximum of size of {client_config.polygonrules.max_area} km\u00b2"  # noqa: E501
            )

        if "axes" not in feature_config:
            self.axes = ["latitude", "longitude"]
        else:
            self.axes = feature_config.pop("axes")

        assert len(feature_config) == 0, f"Unexpected keys in config: {feature_config.keys()}"

    def get_shapes(self):
        if len(self.center[0]) == 2:
            return [
                shapes.Disk(
                    [self.axes[0], self.axes[1]],
                    centre=self.center[0],
                    radius=[self.radius, self.radius],
                )
            ]
        else:
            return [
                shapes.Disk(
                    [self.axes[0], self.axes[1], self.axes[2]],
                    centre=self.center[0],
                    radius=[self.radius, self.radius, self.radius],
                )
            ]

    def incompatible_keys(self):
        return []

    def coverage_type(self):
        return "MultiPoint"

    def name(self):
        return "Circle"

    def required_keys(self):
        return ["type", "center", "radius"]

    def required_axes(self):
        return ["latitude", "longitude"]

    def parse(self, request, feature_config):
        if "axes" in feature_config:
            if len(feature_config["center"][0]) != len(feature_config["axes"]):
                raise ValueError("Number of axes must match number of values in center")

        if field_area(request, self.area) > self.max_area:
            raise ValueError(
                "The request size is too large, lower number of fields requested or size of shape requested"  # noqa: E501
            )
        if len(feature_config["center"]) != 1:
            raise ValueError("Circle feature must have one center point")

        return request
