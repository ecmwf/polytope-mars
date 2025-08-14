from copy import deepcopy

cEarthRadiusInKm = 6378.388
cEarthRadiusInM = cEarthRadiusInKm * 1000
cEarthG = 9.80665


def height_from_geopotential(z):
    z = z / cEarthG
    return cEarthRadiusInM * z / (cEarthRadiusInM - z)


def geopotential_height_from_geopotential(z):
    return z / cEarthG


def get_geopotential_height_request(request, feature_config, point):
    feature_config_copy = deepcopy(feature_config)
    geopotential_request = deepcopy(request)
    feature_config_copy["points"] = [point]
    geopotential_request["param"] = "129"
    geopotential_request["levtype"] = "pl"
    geopotential_request["levelist"] = "all"
    return geopotential_request, feature_config_copy
