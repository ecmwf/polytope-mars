from polytope import shapes

from ..feature import Feature


class VerticalProfile(Feature):
    def __init__(self, feature_config, client_config):
        assert feature_config.pop("type") == "verticalprofile"
        # self.start_step = config.pop("start", None)
        # self.end_step = config.pop("end", None)
        # self.axis = config.pop("axis", [])

        self.points = feature_config.pop("points", [])

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
