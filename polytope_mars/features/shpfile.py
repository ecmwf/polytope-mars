import geopandas as gpd
from polytope_feature import shapes

from ..feature import Feature


# Function to convert POLYGON and MULTIPOLYGON to points
def get_coords(geom):
    if geom.geom_type == "Polygon":
        coords = []
        for point in geom.exterior.coords:
            coords.append([point[0], point[1]])
        return [coords]
    elif geom.geom_type == "MultiPolygon":
        coords = []
        for sub_geom in geom.geoms:
            coord = []
            for point in sub_geom.exterior.coords:
                coord.append([point[0], point[1]])
            coords.append(coord)
        return coords
    else:
        raise ValueError(f"Unsupported geometry type '{geom.geom_type}', expected Polygon or MultiPolygon")


class Shapefile(Feature):
    def __init__(self, feature_config, client_config):
        if feature_config.pop("type") != "shapefile":
            raise ValueError("Feature type must be 'shapefile'")
        self.file = feature_config.pop("file")
        self.df = gpd.read_file(self.file)

        if len(feature_config) != 0:
            raise ValueError(f"Unexpected keys in feature config: {list(feature_config.keys())}")

    def get_shapes(self):
        self.df = self.df.head(1)

        coordinates = self.df.geometry.apply(get_coords)
        polygons = []
        for coords in coordinates:
            for coord in coords:
                polygons.append(shapes.Polygon(["latitude", "longitude"], coord))  # noqa: E501
        return [shapes.Union(["latitude", "longitude"], *polygons)]

    def incompatible_keys(self):
        return ["levellist"]

    def coverage_type(self):
        return "shapefile"

    def name(self):
        return "Shapefile"

    def required_keys(self):
        return ["type", "file"]

    def required_axes(self):
        return ["latitude", "longitude"]

    def parse(self, request, feature_config):
        return request
