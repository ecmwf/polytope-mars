cEarthRadiusInKm = 6378.388
cEarthRadiusInM = cEarthRadiusInKm * 1000
cEarthG = 9.80665


def height_from_geopotential(z):
    z = z / cEarthG
    return cEarthRadiusInM * z / (cEarthRadiusInM - z)


def geopotential_height_from_geopotential(z):
    return z / cEarthG
