from polytope_feature import shapes

from ..feature import Feature


class Path(Feature):
    def __init__(self, feature_config, client_config):
        assert feature_config.pop("type") == "trajectory"
        self.points = feature_config.pop("points", [])
        if "axes" in feature_config:
            self.axes = feature_config.pop("axes")
        else:
            self.axes = ["latitude", "longitude", "levelist", "step"]
        if "inflation" in feature_config:
            if isinstance(feature_config["inflation"], list):
                self.inflation = feature_config.pop("inflation")
                if len(self.inflation) != len(self.axes):
                    raise ValueError(
                        "Inflation must have the same number of values as axes or a single value"  # noqa: E501
                    )
            else:
                self.inflation = []
                infl = feature_config.pop("inflation")
                for ax in self.axes:
                    self.inflation.append(infl)
        if "inflate" in feature_config:
            self.inflate = feature_config.pop("inflate")
        else:
            self.inflate = "round"
        if "axis" in feature_config:
            raise ValueError("Trajectory does not have axis in feature, did you mean axes?")  # noqa: E501

        assert len(feature_config) == 0, f"Unexpected keys in config: {feature_config.keys()}"

    def get_shapes(self):
        if len(self.points[0]) == 2:
            if self.inflate == "round":
                shape = shapes.Disk
            elif self.inflate == "box":
                shape = shapes.Box
            else:
                raise ValueError("Inflate must be either 'round' or 'box' for 2D trajectory feature")  # noqa: E501
            return [
                shapes.Path(
                    [self.axes[0], self.axes[1]],
                    shape(
                        [self.axes[0], self.axes[1]],
                        [0, 0],
                        [self.inflation[0], self.inflation[1]],
                    ),
                    *self.points,
                )
            ]
        elif len(self.points[0]) == 3:
            if self.inflate == "round":
                shape = shapes.Ellipsoid
            elif self.inflate == "box":
                shape = shapes.Box
            else:
                raise ValueError("Inflate must be either 'round' or 'box' for 3D trajectory feature")  # noqa: E501
            return [
                shapes.Path(
                    [self.axes[0], self.axes[1], self.axes[2]],
                    shape(
                        [self.axes[0], self.axes[1], self.axes[2]],
                        [0, 0, 0],
                        [self.inflation[0], self.inflation[1], self.inflation[2]],  # noqa: E501
                    ),
                    *self.points,
                )
            ]
        elif len(self.points[0]) == 4:
            if self.inflate == "round":
                raise ValueError(
                    "Round inflation not yet implemented for 4D trajectory feature, use 'box' instead"  # noqa: E501
                )
            return [
                shapes.Path(
                    [self.axes[0], self.axes[1], self.axes[2], self.axes[3]],
                    shapes.Box(
                        [self.axes[0], self.axes[1], self.axes[2], self.axes[3]],
                        [0, 0, 0, 0],
                        [
                            self.inflation[0],
                            self.inflation[1],
                            self.inflation[2],
                            self.inflation[3],
                        ],  # noqa: E501
                    ),
                    *self.points,
                )
            ]

    def incompatible_keys(self):
        return []

    def valid_axes(self):
        return ["latitude", "longitude", "levelist", "step"]

    def coverage_type(self):
        return "Trajectory"

    def name(self):
        return "Path"

    def required_keys(self):
        return ["type", "points", "inflation"]

    def required_axes(self):
        return ["latitude", "longitude"]

    def parse(self, request, feature_config):
        if "step" in request and "number" in request:
            step = request["step"].split("/")
            number = request["number"].split("/")
            if len(step) > 1 and len(number) > 1:
                raise ValueError("Multiple steps and numbers not yet supported for trajectory feature")  # noqa: E501
        if "step" in request:
            step = request["step"].split("/")
            if len(step) > 1:
                raise ValueError("Multiple steps not yet supported for trajectory feature")
        if "axes" not in feature_config:
            for point in feature_config["points"]:
                if len(point) != 4:
                    raise ValueError(
                        "For Trajectory each point must have only two values unless axes is specified, point must have form ['latitude', 'longitude', 'levelist', 'step']"  # noqa: E501
                    )
        else:
            for point in feature_config["points"]:
                if len(point) != len(feature_config["axes"]):
                    raise ValueError("Trajectory points must have the same number of values as axes")  # noqa: E501
            if ("levelist" in feature_config["axes"]) and ("levelist" in request):  # noqa: E501
                raise ValueError("Trajectory level axes is overspecified in request")  # noqa: E501
        if len(feature_config["points"]) < 2:
            raise ValueError("Trajectory must have atleast two values in points")  # noqa: E501
        if "axes" in feature_config:
            if len(feature_config["axes"]) < 2 or len(feature_config["axes"]) > 4:
                raise ValueError("Trajectory axes must have 2, 3 or 4 values")
            for axis in feature_config["axes"]:
                if axis not in self.valid_axes():
                    raise ValueError(f"Invalid axis: {axis}, must be one of {self.valid_axes()}")  # noqa: E501

        return request
