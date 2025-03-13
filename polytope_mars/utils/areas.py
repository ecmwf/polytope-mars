import math

import numpy as np
from geographiclib.geodesic import Geodesic
from geographiclib.polygonarea import PolygonArea
from shapely.geometry import LineString, Polygon
from shapely.ops import split

from .datetimes import days_between_dates, hours_between_times


def haversine_distance(lat1, lon1, lat2, lon2):
    """
    Calculate the great-circle distance between two points on the Earth's surface.

    :param lat1: Latitude of the first point in degrees
    :param lon1: Longitude of the first point in degrees
    :param lat2: Latitude of the second point in degrees
    :param lon2: Longitude of the second point in degrees
    :return: Distance between the two points in kilometers
    """
    R = 6371  # Radius of the Earth in kilometers
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


def get_circle_area(radius_km):
    """
    Calculate the area of a circle on the surface of the Earth in square kilometers.

    :param radius_km: Radius of the circle in kilometers
    :return: Area of the circle in square kilometers
    """
    return math.pi * (radius_km**2)


def get_circle_area_from_coords(lat_center, lon_center, lat_point, lon_point):
    """
    Calculate the area of a circle on the surface of the Earth in square kilometers
    given the coordinates of the center and a point on the circumference.

    :param lat_center: Latitude of the circle's center in degrees
    :param lon_center: Longitude of the circle's center in degrees
    :param lat_point: Latitude of a point on the circumference in degrees
    :param lon_point: Longitude of a point on the circumference in degrees
    :return: Area of the circle in square kilometers
    """
    radius_km = haversine_distance(lat_center, lon_center, lat_point, lon_point)
    return get_circle_area(radius_km)


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


def get_polygon_area(points):
    polygon = Polygon([(lon, lat) for lat, lon in points])
    pieces = split_polygon(polygon)
    total_area = 0.0
    for piece in pieces:
        area = get_area_piece(piece)
        total_area += area
    return total_area / 1e6  # Convert area from square meters to square kilometers  # noqa: E501


def get_boundingbox_area(points):
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


def field_area(request, area):
    step_len = 1
    number_len = 1
    levelist_len = 1

    if "step" in request:
        step = request["step"].split("/")
        if "to" in step:
            step_len = int(step[2]) - int(step[0])
        else:
            step_len = len(step)

    if "number" in request:
        number = request["number"].split("/")
        if "to" in number:
            number_len = int(number[2]) - int(number[0])
        else:
            number_len = len(number)

    if "levelist" in request:
        levelist = request["levelist"].split("/")
        if "to" in levelist:
            levelist_len = int(levelist[2]) - int(levelist[0])
        else:
            levelist_len = len(levelist)

    date = request["date"].split("/")
    time = request["time"].split("/")

    if "to" in date:
        date_len = days_between_dates(date[0], date[2])
    else:
        date_len = len(date)

    if "to" in time:
        time_len = hours_between_times(time[0], time[2])
    else:
        time_len = len(time)

    shape_area = area

    return step_len * number_len * time_len * date_len * levelist_len * shape_area
