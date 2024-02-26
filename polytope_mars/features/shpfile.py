from typing import List
from ..feature import Feature
from polytope import shapes
import shapefile

#for shp in shps:
#    print(shp.points)

class Shapefile(Feature):

    def __init__(self, config):
        
        assert config.pop('type') == "shapefile"
        self.file = config.pop('file')
        self.file_handle = shapefile.Reader(self.file)
        self.shapes = self.file_handle.shapes()

        assert len(config) == 0, f"Unexpected keys in config: {config.keys()}"

    def get_shapes(self):

        # frame is a four seperate boxes requested based on the inner and outer boxes
        polygons = []
        for shp in self.shapes:
            points = []
            for point in shp.points:
                points.append([point[0], point[1]])
            polygons.append(shapes.Polygon(["latitude", "longitude"], points))
        return [shapes.Union(["latitude", "longitude"],
            *polygons)]

    def incompatible_keys(self):
        return ["levellist"]

    def coverage_type(self):
        return "shapefile"
    
    def name(self):
        return "Shapefile"
    

