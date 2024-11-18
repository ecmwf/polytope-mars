from polytope_feature import shapes

from ..feature import Feature


class Path(Feature):
    def __init__(self, feature_config, client_config):
        assert feature_config.pop("type") == "trajectory"
        self.points = feature_config.pop("points", [])
        if "inflation" in feature_config:
            self.inflation = feature_config.pop("inflation")
        if "axes" in feature_config:
            self.axes = feature_config.pop("axes")
        if "axis" in feature_config:
            raise ValueError(
                "Trajectory does not have axis in feature, did you mean axes?"  # noqa: E501
            )

        assert (
            len(feature_config) == 0
        ), f"Unexpected keys in config: {feature_config.keys()}"

    def get_shapes(self):
        # Time-series is a squashed box from start_step to start_end for each point  # noqa: E501
        if len(self.points[0]) == 2:
            return [
                shapes.Path(
                    ["latitude", "longitude"],
                    shapes.Disk(
                        ["latitude", "longitude"],
                        [0, 0],
                        [self.inflation, self.inflation],
                    ),
                    *self.points,
                )
            ]
        elif len(self.points[0]) == 3:
            if self.axes[2] == "step":
                return [
                    shapes.Path(
                        ["latitude", "longitude", "step"],
                        shapes.Ellipsoid(
                            ["latitude", "longitude", "step"],
                            [0, 0, 0],
                            [self.inflation, self.inflation, 0],
                        ),
                        *self.points,
                    )
                ]
            else:
                return [
                    shapes.Path(
                        ["latitude", "longitude", "levelist"],
                        shapes.Ellipsoid(
                            ["latitude", "longitude", "levelist"],
                            [0, 0, 0],
                            [self.inflation, self.inflation, self.inflation],
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
                        [self.inflation, self.inflation, self.inflation, 0],
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
        if "inflation" not in feature_config:
            raise ValueError("Inflation must be specified in request")
        if "step" in request and "number" in request:
            step = request["step"].split("/")
            number = request["number"].split("/")
            if len(step) > 1 and len(number) > 1:
                raise ValueError(
                    "Multiple steps and numbers not yet supported for trajectory feature"  # noqa: E501
                )
        if "step" in request:
            step = request["step"].split("/")
            if len(step) > 1:
                raise ValueError(
                    "Multiple steps not yet supported for trajectory feature"
                )
        if "axes" not in feature_config:
            for point in feature_config["points"]:
                if len(point) != 4:
                    raise ValueError(
                        "For Trajectory each point must have only two values unless axes is specified, point must have form ['latitude', 'longitude', 'levelist', 'step']"  # noqa: E501
                    )
        else:
            for point in feature_config["points"]:
                if len(point) != len(feature_config["axes"]):
                    raise ValueError(
                        "Trajectory points must have the same number of values as axes"  # noqa: E501
                    )
            if ("levelist" in feature_config["axes"]) and (
                "levelist" in request
            ):  # noqa: E501
                raise ValueError(
                    "Trajectory level axes is overspecified in request"
                )  # noqa: E501
            if feature_config["axes"] == [
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
        if "axes" in feature_config:
            if len(feature_config["axes"]) == 2:
                try:
                    assert feature_config["axes"] == ["latitude", "longitude"]
                except AssertionError:
                    raise AssertionError(
                        "Axes must be ['latitude', 'longitude'], the axes will become more dynamic in the future"  # noqa: E501
                    )
            if len(feature_config["axes"]) == 3:
                if "levelist" in feature_config["axes"]:
                    try:
                        assert feature_config["axes"] == [
                            "latitude",
                            "longitude",
                            "levelist",
                        ]
                    except AssertionError:
                        raise AssertionError(
                            "Axes must be ['latitude', 'longitude', 'levelist'] or ['latitude', 'longitude', 'step'], the axes will become more dynamic in the future"  # noqa: E501
                        )
                else:
                    try:
                        assert feature_config["axes"] == [
                            "latitude",
                            "longitude",
                            "step",
                        ]
                    except AssertionError:
                        raise AssertionError(
                            "Axes must be ['latitude', 'longitude', 'levelist'] or ['latitude', 'longitude', 'step'], the axes will become more dynamic in the future"  # noqa: E501
                        )
            if len(feature_config["axes"]) == 4:
                try:
                    assert feature_config["axes"] == [
                        "latitude",
                        "longitude",
                        "levelist",
                        "step",
                    ]
                except AssertionError:
                    raise AssertionError(
                        "Axes must be ['latitude', 'longitude', 'levelist', 'step'], the axes will become more dynamic in the future"  # noqa: E501
                    )

        return request
