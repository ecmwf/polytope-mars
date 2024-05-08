from polytope import shapes

from ..feature import Feature


class BoundingBox(Feature):
    def __init__(self, config):
        assert config.pop("type") == "boundingbox"
        self.points = config.pop("points", [])

        assert len(config) == 0, f"Unexpected keys in config: {config.keys()}"

    def get_shapes(self):
        # Time-series is a squashed box from start_step to start_end for each point  # noqa: E501
        return [
            shapes.Union(
                ["latitude", "longitude"],
                *[
                    shapes.Box(
                        ["latitude", "longitude"],
                        lower_corner=[self.points[0][0], self.points[0][1]],
                        upper_corner=[self.points[1][0], self.points[1][1]],
                    )
                ],
            )
        ]

    def incompatible_keys(self):
        return ["levellist"]

    def coverage_type(self):
        return "MultiPoint"

    def name(self):
        return "Bounding Box"
