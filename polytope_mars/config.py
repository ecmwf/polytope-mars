from conflator import ConfigModel
from polytope.options import Config


class DatacubeConfig(ConfigModel):

    type: str = "gribjump"
    config: str = "config.yaml"
    uri: str = "http://localhost:8000"


class CovjsonKitConfig(ConfigModel):
    param_db: str = "ecmwf"


class PolygonRulesConfig(ConfigModel):
    max_points: int = 1000
    max_area: float = 1000.0


class PolytopeMarsConfig(ConfigModel):

    datacube: DatacubeConfig = DatacubeConfig()
    options: Config = Config()
    coverageconfig: CovjsonKitConfig = CovjsonKitConfig()
    polygonrules: PolygonRulesConfig = PolygonRulesConfig()
