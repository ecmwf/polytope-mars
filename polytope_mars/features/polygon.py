from functools import partial

import pyproj
import shapely.ops as ops
from polytope_feature import shapes
from shapely.geometry import Polygon

from ..feature import Feature


def get_area(points):
    x = []
    y = []
    for point in points:
        x.append(point[0])
        y.append(point[1])
    pgon = Polygon(zip(x, y))
    geom_area = ops.transform(
        partial(
            pyproj.transform,
            pyproj.Proj(init="EPSG:4326"),
            pyproj.Proj(
                proj="aea", lat_1=pgon.bounds[1], lat_2=pgon.bounds[3]
            ),  # noqa: E501
        ),
        pgon,
    )
    return geom_area.area / 1_000_000


class Polygons(Feature):
    def __init__(self, feature_config, client_config):
        assert feature_config.pop("type") == "polygon"
        self.shape = feature_config.pop("shape")
        self.max_area = client_config.polygonrules.max_area
        if type(self.shape[0][0]) is not list:
            if len(self.shape) > client_config.polygonrules.max_points:
                raise ValueError(
                    f"Number of points {len(self.shape)} exceeds the maximum of {client_config.polygonrules.max_points}"  # noqa: E501
                )
            if get_area(self.shape) > client_config.polygonrules.max_area:
                raise ValueError(
                    f"Area of polygon {get_area(self.shape)} km\u00b2 exceeds the maximum of size of {client_config.polygonrules.max_area} km\u00b2"  # noqa: E501
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
                    f"Area of polygon {area_polygons} exceeds the maximum of size of {client_config.polygonrules.max_area} degrees\u00b2"  # noqa: E501
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

    def parse(self, request, feature_config):
        if feature_config["type"] != "polygon":
            raise ValueError("Feature type must be polygon")
        if "step" in request and "number" in request:
            step = request["step"].split("/")
            number = request["number"].split("/")
            if len(step) > 1 and len(number) > 1:
                if "to" in step:
                    step_len = int(step[2]) - int(step[0])
                else:
                    step_len = len(step)
                if "to" in number:
                    number_len = int(number[2]) - int(number[0])
                else:
                    number_len = len(number)
                shape_area = get_area(self.shape[0])
                if step_len * number_len * shape_area > self.max_area:
                    raise ValueError(
                        "The request size is too large, lower number of fields requested or size of shape requested"  # noqa: E501
                    )
        return request
