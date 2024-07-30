import geopandas as gpd
from polytope import shapes

from ..feature import Feature


# Function to convert POLYGON and MULTIPOLYGON to points
def get_coords(geom):
    if geom.geom_type == "Polygon":
        coords = []
        for point in geom.exterior.coords:
            coords.append([point[0], point[1]])
        return [coords]
    else:
        coords = []
        for geom in geom.geoms:
            coord = []
            for point in geom.exterior.coords:
                coord.append([point[0], point[1]])
            coords.append(coord)
    return coords


class Shapefile(Feature):
    def __init__(self, config):
        assert config.pop("type") == "shapefile"
        self.file = config.pop("file")
        self.df = gpd.read_file(self.file)

        assert len(config) == 0, f"Unexpected keys in config: {config.keys()}"

    def get_shapes(self):
        self.df = self.df.head(1)

        coordinates = self.df.geometry.apply(get_coords)
        polygons = []
        for coords in coordinates:
            for coord in coords:
                polygons.append(
                    shapes.Polygon(["latitude", "longitude"], coord)
                )  # noqa: E501
        return [shapes.Union(["latitude", "longitude"], *polygons)]

    def incompatible_keys(self):
        return ["levellist"]

    def coverage_type(self):
        return "shapefile"

    def name(self):
        return "Shapefile"
