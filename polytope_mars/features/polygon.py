import numpy as np
from geographiclib.geodesic import Geodesic
from geographiclib.polygonarea import PolygonArea
from polytope_feature import shapes
from shapely.geometry import LineString, Polygon
from shapely.ops import split

from ..feature import Feature


def split_polygon(polygon):
    minx, miny, maxx, maxy = polygon.bounds

    # Determine all multiples of 90 degrees within the longitude range
    # We extend the range slightly to include exact multiples if
    # they coincide with minx or maxx
    start_lon = int(np.floor(minx / 90.0)) * 90
    end_lon = int(np.ceil(maxx / 90.0)) * 90
    split_longitudes = list(range(start_lon, end_lon + 1, 90))

    pieces = [polygon]

    # Split the polygon using the specified meridians
    for lon in split_longitudes:
        new_pieces = []
        splitter = LineString([(lon, -90), (lon, 90)])
        for poly in pieces:
            if not poly.is_empty:
                result = split(poly, splitter)
                for geom in result.geoms:
                    if geom.geom_type in ["Polygon", "MultiPolygon"]:
                        new_pieces.append(geom)
            else:
                continue
        pieces = new_pieces

    return pieces


def get_area_piece(piece):
    geod = Geodesic.WGS84
    polygon = PolygonArea(geod, False)

    if piece.geom_type == "Polygon":
        coords = list(piece.exterior.coords)
    elif piece.geom_type == "MultiPolygon":
        area = 0.0
        for poly in piece:
            area += get_area_piece(poly)
        return area
    else:
        return 0.0

    for lon, lat in coords:
        polygon.AddPoint(lat, lon)

    num, perimeter, area = polygon.Compute(False, True)

    area = abs(area)

    return area  # area in square meters


def get_area(points):
    polygon = Polygon([(lon, lat) for lat, lon in points])
    pieces = split_polygon(polygon)
    total_area = 0.0
    for piece in pieces:
        area = get_area_piece(piece)
        total_area += area
    return total_area / 1e6  # Convert area from square meters to square kilometers  # noqa: E501


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
        if "step" in request and "number" in request:
            step = request["step"].split("/")
            number = request["number"].split("/")

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
