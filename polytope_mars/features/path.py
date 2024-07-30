from polytope import shapes

from ..feature import Feature


class Path(Feature):
    def __init__(self, config):
        assert config.pop("type") == "path"
        self.points = config.pop("points", [])
        self.padding = config.pop("padding")

        assert len(config) == 0, f"Unexpected keys in config: {config.keys()}"

    def get_shapes(self):
        # Time-series is a squashed box from start_step to start_end for each point  # noqa: E501
        return [
            shapes.Union(
                ["latitude", "longitude"],
                *[
                    shapes.Path(
                        ["latitude", "longitude"],
                        shapes.Box(
                            ["latitude", "longitude"],
                            [0, 0],
                            [self.padding, self.padding],
                        ),
                        *self.points,
                    )
                ],
            )
        ]

    def incompatible_keys(self):
        return ["levellist"]

    def coverage_type(self):
        return "Trajectory"

    def name(self):
        return "Path"
