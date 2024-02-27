from typing import List
from ..feature import Feature
from polytope import shapes
import geopandas as gpd

class Shapefile(Feature):

    def __init__(self, config):
        
        assert config.pop('type') == "shapefile"
        self.file = config.pop('file')
        self.df = gpd.read_file(self.file)

        assert len(config) == 0, f"Unexpected keys in config: {config.keys()}"

    def get_shapes(self):

        self.df = self.df.head(2)
        polygons = []
        for row in self.df.iterrows():
            if row[1]['geometry'].geom_type == 'Polygon':
                points = []
                for point in row[1]['geometry'].exterior.coords:
                    points.append([point[0], point[1]])
                polygons.append(shapes.Polygon(["latitude", "longitude"], points))
            else:
                for geom in row[1]["geometry"].geoms:
                    points = []
                    for point in geom.exterior.coords:
                        points.append([point[0], point[1]])
                    polygons.append(shapes.Polygon(["latitude", "longitude"], points))
        return [shapes.Union(["latitude", "longitude"], *polygons)]

    def incompatible_keys(self):
        return ["levellist"]

    def coverage_type(self):
        return "shapefile"
    
    def name(self):
        return "Shapefile"
    

