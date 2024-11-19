from polytope_feature import shapes

from ..feature import Feature


class Frame(Feature):
    def __init__(self, feature_config, client_config):
        assert feature_config.pop("type") == "frame"
        self.points = feature_config.pop("points", [])
        self.outer_box = feature_config.pop("outer_box", [])
        self.inner_box = feature_config.pop("inner_box", [])

        assert len(feature_config) == 0, f"Unexpected keys in config: {feature_config.keys()}"

    def get_shapes(self):
        # frame is a four seperate boxes requested based on the inner and outer boxes  # noqa: E501
        return [
            shapes.Union(
                ["latitude", "longitude"],
                shapes.Box(
                    ["latitude", "longitude"],
                    [self.outer_box[0][0], self.outer_box[0][1]],
                    [self.inner_box[0][0], self.outer_box[1][1]],
                ),
                shapes.Box(
                    ["latitude", "longitude"],
                    [self.inner_box[0][0], self.outer_box[0][1]],
                    [self.inner_box[1][0], self.inner_box[0][1]],
                ),
                shapes.Box(
                    ["latitude", "longitude"],
                    [self.inner_box[0][0], self.inner_box[1][1]],
                    [self.inner_box[1][0], self.outer_box[1][1]],
                ),
                shapes.Box(
                    ["latitude", "longitude"],
                    [self.inner_box[1][0], self.outer_box[0][1]],
                    [self.outer_box[1][0], self.outer_box[1][1]],
                ),
            )
        ]

    def incompatible_keys(self):
        return ["levellist"]

    def coverage_type(self):
        return "MultiPoint"

    def name(self):
        return "Frame"

    def parse(self, request, feature_config):
        return request
