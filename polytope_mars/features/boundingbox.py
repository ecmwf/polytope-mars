from polytope_feature import shapes

from ..feature import Feature


class BoundingBox(Feature):
    def __init__(self, feature_config, client_config):
        assert feature_config.pop("type") == "boundingbox"
        self.points = feature_config.pop("points", [])
        self.axis = feature_config.pop("axis", [])

        assert (
            len(feature_config) == 0
        ), f"Unexpected keys in config: {feature_config.keys()}"

    def get_shapes(self):
        # Time-series is a squashed box from start_step to start_end for each point  # noqa: E501
        if len(self.points[0]) == 2:
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
        else:
            return [
                shapes.Union(
                    ["latitude", "longitude", "levelist"],
                    *[
                        shapes.Box(
                            ["latitude", "longitude", "levelist"],
                            lower_corner=[self.points[0][0], self.points[0][1], self.points[0][2]],
                            upper_corner=[self.points[1][0], self.points[1][1], self.points[1][2]],
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
    
    def parse(self, request, feature_config):
        print("feature_config: ", feature_config)
        print("request: ", request)
        if feature_config['type'] != 'boundingbox':
            raise ValueError("Feature type must be boudningbox")
        if len(feature_config['points']) != 2:
            raise ValueError("Boudning must have only two points in points")
        if "axis" not in feature_config:
            for point in feature_config['points']:
                if len(point) != 2:
                    raise ValueError("For Bounding Box each point must have only two values unless axis is specified")
        else:
            for point in feature_config['points']:
                if len(point) != len(feature_config['axis']):
                    raise ValueError("Bounding Box points must have the same number of values as axis")
            if "axis" in feature_config:
                if ("levelist" in feature_config['axis']) and ("levelist" in request):
                    raise ValueError("Bounding Box axis is overspecified in request")
  
        
        return request
