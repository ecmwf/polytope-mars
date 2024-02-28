from typing import List
from ..feature import Feature
from polytope import shapes
import geopandas as gpd

# Function to convert POLYGON and MULTIPOLYGON to points 
def get_coords(geom):
    if geom.geom_type == 'Polygon':
        coords = list(geom.exterior.coords)
    else:
        coords = []
        for geom in geom.geoms:
            coords = list(geom.exterior.coords)
    return (coords)

class Shapefile(Feature):

    def __init__(self, config):
        
        assert config.pop('type') == "shapefile"
        self.file = config.pop('file')
        self.df = gpd.read_file(self.file)

        assert len(config) == 0, f"Unexpected keys in config: {config.keys()}"

    def get_shapes(self):

        coordinates = self.df.geometry.apply(get_coords)
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
        return "shapefile"
    
    def name(self):
        return "Shapefile"
    

