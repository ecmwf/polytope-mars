import math

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
    return math.pi * (radius_km ** 2)

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

def field_area(request, area):

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
    else:
        step_len = 1
        number_len = 1

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

    return step_len * number_len * time_len * date_len * shape_area