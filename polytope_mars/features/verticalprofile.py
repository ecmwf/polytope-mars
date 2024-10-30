from polytope_feature import shapes

from ..feature import Feature


class VerticalProfile(Feature):
    def __init__(self, feature_config, client_config):
        assert feature_config.pop("type") == "verticalprofile"
        # self.start_step = config.pop("start", None)
        # self.end_step = config.pop("end", None)
        if "axis" in feature_config:
            self.axis = feature_config.pop("axis", [])

        self.points = feature_config.pop("points", [])

        if "range" in feature_config:
            feature_config.pop("range")

        assert (
            len(feature_config) == 0
        ), f"Unexpected keys in config: {feature_config.keys()}"

    def get_shapes(self):
        # Time-series is a squashed box from start_step to start_end for each point  # noqa: E501
        return [
            shapes.Union(
                ["latitude", "longitude"],
                *[
                    shapes.Point(
                        ["latitude", "longitude"],
                        [[p[0], p[1]]],
                        method="nearest",  # noqa: E501
                    )
                    for p in self.points
                ],
            ),
            # shapes.Span("step", self.start_step, self.end_step),
        ]

    def incompatible_keys(self):
        return []

    def coverage_type(self):
        return "VerticalProfile"

    def name(self):
        return "Vertical Profile"

    def parse(self, request, feature_config):
        if feature_config["type"] != "verticalprofile":
            raise ValueError("Feature type must be vertical proifle")
        if "axis" in feature_config and feature_config["axis"] != "levelist":
            raise ValueError("Vertical profile axis must be levelist")
        if len(feature_config["points"][0]) != 2:
            raise ValueError(
                "Vertical Profile must have only two values in points"
            )  # noqa: E501
        if "axis" in feature_config:
            if feature_config["axis"] in request and "range" in feature_config:
                raise ValueError(
                    "Vertical profile axis is overspecified in request"
                )  # noqa: E501
            if (
                feature_config["axis"] not in request
                and "range" not in feature_config  # noqa: E501
            ):  # noqa: E501
                raise ValueError(
                    "Vertical profile axis is underspecified in request"
                )  # noqa: E501
        if "range" in feature_config:
            if isinstance(feature_config["range"], dict):
                request[feature_config["axis"]] = (
                    f"{feature_config['range']['start']}/to/{feature_config['range']['end']}"  # noqa: E501
                )
                if "interval" in feature_config["range"]:
                    request[
                        feature_config["axis"]
                    ] += f"/by/{feature_config['range']['interval']}"

        return request
