from conflator import ConfigModel
from polytope.options import Config


class DatacubeConfig(ConfigModel):

    type: str = "gribjump"
    config: str = "config.yaml"
    uri: str = "http://localhost:8000"


class CovjsonKitConfig(ConfigModel):
    param_db: str = "ecmwf"


class PolygonRulesConfig(ConfigModel):
    # Max points is the max number of points in all polygons requested allowed
    max_points: int = 1000
    # Max area is the max area of all polygons requested that is allowed.
    # Area is in abstract units as a projection would otherwise be required
    # to calculate the area
    max_area: float = 1000.0


class PolytopeMarsConfig(ConfigModel):

    datacube: DatacubeConfig = DatacubeConfig()
    options: Config = Config()
    coverageconfig: CovjsonKitConfig = CovjsonKitConfig()
    polygonrules: PolygonRulesConfig = PolygonRulesConfig()
