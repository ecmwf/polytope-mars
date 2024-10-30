from polytope_feature import shapes

from ..feature import Feature


class Path(Feature):
    def __init__(self, feature_config, client_config):
        assert feature_config.pop("type") == "trajectory"
        self.points = feature_config.pop("points", [])
        if "padding" in feature_config:
            self.padding = feature_config.pop("padding")
        if "axis" in feature_config:
            self.axis = feature_config.pop("axis")

        assert (
            len(feature_config) == 0
        ), f"Unexpected keys in config: {feature_config.keys()}"

    def get_shapes(self):
        # Time-series is a squashed box from start_step to start_end for each point  # noqa: E501
        if len(self.points[0]) == 2:
            return [
                shapes.Path(
                    ["latitude", "longitude"],
                    shapes.Box(
                        ["latitude", "longitude"],
                        [0, 0],
                        [self.padding, self.padding],
                    ),
                    *self.points,
                )
            ]
        elif len(self.points[0]) == 3:
            if self.axis[2] == "step":
                return [
                    shapes.Path(
                        ["latitude", "longitude", "step"],
                        shapes.Box(
                            ["latitude", "longitude", "step"],
                            [0, 0, 0],
                            [self.padding, self.padding, 0],
                        ),
                        *self.points,
                    )
                ]
            else:
                return [
                    shapes.Path(
                        ["latitude", "longitude", "levelist"],
                        shapes.Box(
                            ["latitude", "longitude", "levelist"],
                            [0, 0, 0],
                            [self.padding, self.padding, 0],
                        ),
                        *self.points,
                    )
                ]
        elif len(self.points[0]) == 4:
            return [
                shapes.Path(
                    ["latitude", "longitude", "levelist", "step"],
                    shapes.Box(
                        ["latitude", "longitude", "levelist", "step"],
                        [0, 0, 0, 0],
                        [self.padding, self.padding, 0, 0],
                    ),
                    *self.points,
                )
            ]

    def incompatible_keys(self):
        return []

    def coverage_type(self):
        return "Trajectory"

    def name(self):
        return "Path"

    def parse(self, request, feature_config):
        if feature_config["type"] != "trajectory":
            raise ValueError("Feature type must be trajectory")
        if "padding" not in feature_config:
            raise ValueError("Padding must be specified in request")
        if "axis" not in feature_config:
            for point in feature_config["points"]:
                if len(point) != 4:
                    raise ValueError(
                        "For Trajectory each point must have only two values unless axis is specified, point must have form ['latitude', 'longitude', 'levelist', 'step']"  # noqa: E501
                    )
        else:
            for point in feature_config["points"]:
                if len(point) != len(feature_config["axis"]):
                    raise ValueError(
                        "Trajectory points must have the same number of values as axis"  # noqa: E501
                    )
            if ("levelist" in feature_config["axis"]) and (
                "levelist" in request
            ):  # noqa: E501
                raise ValueError(
                    "Trajectory level axis is overspecified in request"
                )  # noqa: E501
            if feature_config["axis"] == [
                "latitude",
                "longitude",
                "levelist",
            ]:  # noqa: E501
                raise ValueError(
                    "['latitude', 'longitude', 'levelist'] not yet implemented"
                )
        if len(feature_config["points"]) < 2:
            raise ValueError(
                "Trajectory must have atleast two values in points"
            )  # noqa: E501

        return request
