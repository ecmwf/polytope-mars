import logging

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
    # We extend the range slightly to include exact multiples if they
    # coincide with minx or maxx
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
    # Convert points to a Shapely Polygon
    min_lon, min_lat = points[0][:2]
    max_lon, max_lat = points[1][:2]
    if min_lon + max_lon == 0:
        min_lon += 0.1

    # Define the polygon coordinates
    polygon_coords = [
        (min_lat, min_lon),  # Bottom-left corner
        (min_lat, max_lon),  # Bottom-right corner
        (max_lat, max_lon),  # Top-right corner
        (max_lat, min_lon),  # Top-left corner
        (
            min_lat,
            min_lon,
        ),  # Closing the polygon by returning to the bottom-left corner
    ]
    polygon = Polygon(polygon_coords)
    pieces = split_polygon(polygon)
    total_area = 0.0
    for piece in pieces:
        area = get_area_piece(piece)
        total_area += area
    return total_area / 1e6  # Convert area from square meters to square kilometers  # noqa: E501


class BoundingBox(Feature):
    def __init__(self, feature_config, client_config):
        assert feature_config.pop("type") == "boundingbox"
        if "points" not in feature_config:
            raise KeyError("Bounding box must have points in feature")
        self.points = feature_config.pop("points", [])
        if "axes" not in feature_config:
            feature_config["axes"] = ["latitude", "longitude"]
        self.axes = feature_config.pop("axes", [])
        self.max_area = client_config.polygonrules.max_area

        if "axes" in feature_config:
            raise ValueError("Bounding box does not have axes in feature, did you mean axes?")  # noqa: E501

        assert len(feature_config) == 0, f"Unexpected keys in config: {feature_config.keys()}"

        area_bb = get_area(self.points)
        logging.info(f"Area of bounding box: {area_bb} km\u00b2")
        if area_bb > client_config.polygonrules.max_area:
            raise ValueError(
                f"Area of Bounding Box {area_bb} km\u00b2 exceeds the maximum size of {client_config.polygonrules.max_area} km\u00b2"  # noqa: E501
            )

    def get_shapes(self):
        # Time-series is a squashed box from start_step to start_end for each point  # noqa: E501
        if len(self.points[0]) == 2:
            return [
                shapes.Union(
                    ["latitude", "longitude"],
                    *[
                        shapes.Box(
                            ["latitude", "longitude"],
                            lower_corner=[
                                self.points[0][self.axes.index("latitude")],
                                self.points[0][self.axes.index("longitude")],
                            ],  # noqa: E501
                            upper_corner=[
                                self.points[1][self.axes.index("latitude")],
                                self.points[1][self.axes.index("longitude")],
                            ],  # noqa: E501
                        )
                    ],
                )
            ]
        else:
            return [
                shapes.Union(
                    [self.axes[0], self.axes[1], self.axes[2]],
                    *[
                        shapes.Box(
                            [self.axes[0], self.axes[1], self.axes[2]],
                            lower_corner=[
                                self.points[0][0],
                                self.points[0][1],
                                self.points[0][2],
                            ],
                            upper_corner=[
                                self.points[1][0],
                                self.points[1][1],
                                self.points[1][2],
                            ],
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

    def required_keys(self):
        return ["type", "points"]

    def required_axes(self):
        return ["latitude", "longitude"]

    def parse(self, request, feature_config):
        if feature_config["type"] != "boundingbox":
            raise ValueError("Feature type must be boundingbox")
        if "axes" in feature_config:
            if len(feature_config["axes"]) < 2 or len(feature_config["axes"]) > 3:
                raise ValueError(
                    "Bounding Box axes must contain 2 or 3 values, latitude, longitude, and optionally levelist"
                )
            if "step" in feature_config["axes"]:
                raise ValueError(
                    "Bounding box axes must be latitude and longitude, step can be requested in main body of request"
                )
            if "latitude" not in feature_config["axes"] or "longitude" not in feature_config["axes"]:
                raise ValueError("Bounding Box axes must contain both latitude and longitude")
            if len(feature_config["axes"]) > 3:
                raise ValueError(
                    "Bounding Box axes must contain at most 3 values, latitude, longitude, and levelist"
                )  # noqa: E501
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

            shape_area = get_area(self.points)
            if step_len * number_len * shape_area > self.max_area:
                raise ValueError(
                    "The request size is too large, lower number of fields requested or size of shape requested"  # noqa: E501
                )

        if len(feature_config["points"]) != 2:
            raise ValueError("Bounding box must have only two points in points")  # noqa: E501
        if "axis" in feature_config:
            raise ValueError("Bounding box does not have axis in feature, did you mean axes?")  # noqa: E501
        if "axes" not in feature_config:
            for point in feature_config["points"]:
                if len(point) != 2:
                    raise ValueError(
                        "For Bounding Box each point must have only two values unless axes is specified"  # noqa: E501
                    )
        else:
            for point in feature_config["points"]:
                if len(point) != len(feature_config["axes"]):
                    raise ValueError("Bounding Box points must have the same number of values as axes")  # noqa: E501
            if "axes" in feature_config:
                if ("levelist" in feature_config["axes"]) and ("levelist" in request):  # noqa: E501
                    raise ValueError("Bounding Box axes is overspecified in request")  # noqa: E501

        return request
