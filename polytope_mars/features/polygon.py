from polytope_feature import shapes

from ..feature import Feature
from ..utils.areas import field_area, get_polygon_area


class Polygons(Feature):
    def __init__(self, feature_config, client_config):
        assert feature_config.pop("type") == "polygon"
        self.shape = feature_config.pop("shape")
        self.max_area = client_config.polygonrules.max_area
        self.area = 0
        if type(self.shape[0][0]) is not list:
            self.area = get_polygon_area(self.shape)
            if len(self.shape) > client_config.polygonrules.max_points:
                raise ValueError(
                    f"Number of points {len(self.shape)} exceeds the maximum of {client_config.polygonrules.max_points}"  # noqa: E501
                )
            if self.area > client_config.polygonrules.max_area:
                raise ValueError(
                    f"Area of polygon {self.area} km\u00b2 exceeds the maximum of size of {client_config.polygonrules.max_area} km\u00b2"  # noqa: E501
                )
            self.shape = [self.shape]
        else:
            len_polygons = 0
            area_polygons = 0
            for polygon in self.shape:
                len_polygons += len(polygon)
                area_polygons += get_polygon_area(polygon)
            self.area = area_polygons
            if len_polygons > client_config.polygonrules.max_points:
                raise ValueError(
                    f"Number of points {len_polygons} exceeds the maximum of {client_config.polygonrules.max_points}"  # noqa: E501
                )
            if area_polygons > client_config.polygonrules.max_area:
                raise ValueError(
                    f"Area of polygon {area_polygons} exceeds the maximum of size of {client_config.polygonrules.max_area} degrees\u00b2"  # noqa: E501
                )

        if "axes" not in feature_config:
            self.axes = ["latitude", "longitude"]
        else:
            self.axes = feature_config.pop("axes")

        assert len(feature_config) == 0, f"Unexpected keys in config: {feature_config.keys()}"

    def get_shapes(self):
        # coordinates = get_coords(self.df)
        polygons = []
        for polygon in self.shape:
            points = []
            for point in polygon:
                points.append([point[0], point[1]])
            polygons.append(shapes.Polygon([self.axes[0], self.axes[1]], points))
        return [shapes.Union([self.axes[0], self.axes[1]], *polygons)]

    def incompatible_keys(self):
        return []

    def coverage_type(self):
        return "MultiPoint"

    def name(self):
        return "Polygon"

    def required_keys(self):
        return ["type", "shape"]

    def required_axes(self):
        return ["latitude", "longitude"]

    def parse(self, request, feature_config):
        if "axes" in request:
            if len(request["axes"]) != 2:
                raise ValueError("Polygon feature must have two axes, latitude and longitude")
        if field_area(request, self.area) > self.max_area:
            raise ValueError(
                "The request size is too large, lower number of fields requested or size of shape requested"  # noqa: E501
            )
        return request
