from polytope import shapes
from shapely.geometry import Polygon

from ..feature import Feature


def get_area(points):
    x = []
    y = []
    for point in points:
        x.append(point[0])
        y.append(point[1])
    pgon = Polygon(zip(x, y))
    return pgon.area


class Polygons(Feature):
    def __init__(self, feature_config, client_config):
        assert feature_config.pop("type") == "polygon"
        self.shape = feature_config.pop("shape")
        if type(self.shape[0][0]) is not list:
            if len(self.shape) > client_config.polygonrules.max_points:
                raise ValueError(
                    f"Number of points {len(self.shape)} exceeds the maximum of {client_config.polygonrules.max_points}"  # noqa: E501
                )
            if get_area(self.shape) > client_config.polygonrules.max_area:
                raise ValueError(
                    f"Area of polygon {get_area(self.shape)} exceeds the maximum of {client_config.polygonrules.max_area}"  # noqa: E501
                )
            self.shape = [self.shape]
        else:
            len_polygons = 0
            area_polygons = 0
            for polygon in self.shape:
                len_polygons += len(polygon)
                area_polygons += get_area(polygon)
            if len_polygons > client_config.polygonrules.max_points:
                raise ValueError(
                    f"Number of points {len_polygons} exceeds the maximum of {client_config.polygonrules.max_points}"  # noqa: E501
                )
            if area_polygons > client_config.polygonrules.max_area:
                raise ValueError(
                    f"Area of polygon {area_polygons} exceeds the maximum of {client_config.polygonrules.max_area}"  # noqa: E501
                )

        assert (
            len(feature_config) == 0
        ), f"Unexpected keys in config: {feature_config.keys()}"

    def get_shapes(self):
        # coordinates = get_coords(self.df)
        polygons = []
        for polygon in self.shape:
            points = []
            for point in polygon:
                points.append([point[0], point[1]])
            polygons.append(shapes.Polygon(["latitude", "longitude"], points))
        return [shapes.Union(["latitude", "longitude"], *polygons)]

    def incompatible_keys(self):
        return []

    def coverage_type(self):
        return "MultiPoint"

    def name(self):
        return "Polygon"
