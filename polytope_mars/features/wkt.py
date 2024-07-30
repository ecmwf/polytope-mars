from polytope import shapes
from shapely import wkt

from ..feature import Feature


# Function to convert POLYGON and MULTIPOLYGON to points
def get_coords(geom):
    if geom.geom_type == "Polygon":
        coords = [list(geom.exterior.coords)]
    else:
        coords = []
        for geom in geom.geoms:
            coords.append(list(geom.exterior.coords))
    return coords


class Wkt(Feature):
    def __init__(self, config):
        assert config.pop("type") == "wkt"
        self.shape = config.pop("shape")
        self.df = wkt.loads(self.shape)

        assert len(config) == 0, f"Unexpected keys in config: {config.keys()}"

    def get_shapes(self):
        coordinates = get_coords(self.df)
        polygons = []
        for coord in coordinates:
            points = []
            for point in coord:
                points.append([point[0], point[1]])
            polygons.append(shapes.Polygon(["latitude", "longitude"], points))
        return [shapes.Union(["latitude", "longitude"], *polygons)]

    def incompatible_keys(self):
        return ["levellist"]

    def coverage_type(self):
        return "wkt"

    def name(self):
        return "Wkt"
