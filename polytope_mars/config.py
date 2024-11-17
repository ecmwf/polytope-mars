from conflator import ConfigModel
from polytope_feature.options import Config


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
    # Area is calculated in kilometers squared
    max_area: float = float("inf")


class PolytopeMarsConfig(ConfigModel):
    datacube: DatacubeConfig = DatacubeConfig()
    options: Config = Config()
    coverageconfig: CovjsonKitConfig = CovjsonKitConfig()
    polygonrules: PolygonRulesConfig = PolygonRulesConfig()
