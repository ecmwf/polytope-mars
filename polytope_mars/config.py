from conflator import ConfigModel
from polytope.options import Config


class DatacubeConfig(ConfigModel):

    type: str = "gribjump"
    config: str = "config.yaml"
    uri: str = "http://localhost:8000"


class CovjsonKitConfig(ConfigModel):
    param_db: str = "ecmwf"


class PolytopeMarsConfig(ConfigModel):

    datacube: DatacubeConfig = DatacubeConfig()
    options: Config = Config()
    coverageconfig: CovjsonKitConfig = CovjsonKitConfig()
