import logging

from polytope_feature import shapes

from ..feature import Feature
from ..utils.areas import field_area, get_boundingbox_area


class BoundingBox(Feature):
    def __init__(self, feature_config, client_config):
        assert feature_config.pop("type") == "boundingbox"
        if "points" not in feature_config:
            raise KeyError("Bounding box must have points in feature")
        self.points = feature_config.pop("points", [])
        if "axes" not in feature_config:
            feature_config["axes"] = ["latitude", "longitude"]
        self.axes = feature_config.pop("axes", [])
        self.max_area = client_config.polygonrules.max_area

        if "axes" in feature_config:
            raise ValueError("Bounding box does not have axes in feature, did you mean axes?")  # noqa: E501

        assert len(feature_config) == 0, f"Unexpected keys in config: {feature_config.keys()}"

        self.area_bb = get_boundingbox_area(self.points)
        logging.info(f"Area of bounding box: {self.area_bb} km\u00b2")
        if self.area_bb > client_config.polygonrules.max_area:
            raise ValueError(
                f"Area of Bounding Box {self.area_bb} km\u00b2 exceeds the maximum size of {client_config.polygonrules.max_area} km\u00b2"  # noqa: E501
            )

    def get_shapes(self):
        # Time-series is a squashed box from start_step to start_end for each point  # noqa: E501
        if len(self.points[0]) == 2:
            return [
                shapes.Union(
                    ["latitude", "longitude"],
                    *[
                        shapes.Box(
                            ["latitude", "longitude"],
                            lower_corner=[
                                self.points[0][self.axes.index("latitude")],
                                self.points[0][self.axes.index("longitude")],
                            ],  # noqa: E501
                            upper_corner=[
                                self.points[1][self.axes.index("latitude")],
                                self.points[1][self.axes.index("longitude")],
                            ],  # noqa: E501
                        )
                    ],
                )
            ]
        else:
            return [
                shapes.Union(
                    [self.axes[0], self.axes[1], self.axes[2]],
                    *[
                        shapes.Box(
                            [self.axes[0], self.axes[1], self.axes[2]],
                            lower_corner=[
                                self.points[0][0],
                                self.points[0][1],
                                self.points[0][2],
                            ],
                            upper_corner=[
                                self.points[1][0],
                                self.points[1][1],
                                self.points[1][2],
                            ],
                        )
                    ],
                )
            ]

    def incompatible_keys(self):
        return []

    def coverage_type(self):
        return "MultiPoint"

    def name(self):
        return "Bounding Box"

    def required_keys(self):
        return ["type", "points"]

    def required_axes(self):
        return ["latitude", "longitude"]

    def parse(self, request, feature_config):
        if feature_config["type"] != "boundingbox":
            raise ValueError("Feature type must be boundingbox")
        if "axes" in feature_config:
            if len(feature_config["axes"]) < 2 or len(feature_config["axes"]) > 3:
                raise ValueError(
                    "Bounding Box axes must contain 2 or 3 values, latitude, longitude, and optionally levelist"
                )
            if "step" in feature_config["axes"]:
                raise ValueError(
                    "Bounding box axes must be latitude and longitude, step can be requested in main body of request"
                )
            if "latitude" not in feature_config["axes"] or "longitude" not in feature_config["axes"]:
                raise ValueError("Bounding Box axes must contain both latitude and longitude")
            if len(feature_config["axes"]) > 3:
                raise ValueError(
                    "Bounding Box axes must contain at most 3 values, latitude, longitude, and levelist"
                )  # noqa: E501

        if field_area(request, self.area_bb) > self.max_area:
            raise ValueError(
                "The request size is too large, lower number of fields requested or size of shape requested"  # noqa: E501
            )

        if len(feature_config["points"]) != 2:
            raise ValueError("Bounding box must have only two points in points")  # noqa: E501
        if "axis" in feature_config:
            raise ValueError("Bounding box does not have axis in feature, did you mean axes?")  # noqa: E501
        if "axes" not in feature_config:
            for point in feature_config["points"]:
                if len(point) != 2:
                    raise ValueError(
                        "For Bounding Box each point must have only two values unless axes is specified"  # noqa: E501
                    )
        else:
            for point in feature_config["points"]:
                if len(point) != len(feature_config["axes"]):
                    raise ValueError("Bounding Box points must have the same number of values as axes")  # noqa: E501
            if "axes" in feature_config:
                if ("levelist" in feature_config["axes"]) and ("levelist" in request):  # noqa: E501
                    raise ValueError("Bounding Box axes is overspecified in request")  # noqa: E501

        return request
