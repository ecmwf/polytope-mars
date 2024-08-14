from typing import Dict, List, Literal, Optional, Union

from conflator import ConfigModel
from pydantic import ConfigDict


class DatacubeConfig(ConfigModel):

    type: str = "gribjump"
    config: str = "config.yaml"
    uri: str = "http://localhost:8000"


class TransformationConfig(ConfigModel):
    model_config = ConfigDict(extra="forbid")
    name: str = ""


class CyclicConfig(TransformationConfig):
    name: Literal["cyclic"]
    range: List[float] = [0]


class MapperConfig(TransformationConfig):
    name: Literal["mapper"]
    type: str = ""
    resolution: Union[int, List[int]] = 0
    axes: List[str] = [""]
    local: Optional[List[float]] = None


class ReverseConfig(TransformationConfig):
    name: Literal["reverse"]
    is_reverse: bool = False


class TypeChangeConfig(TransformationConfig):
    name: Literal["type_change"]
    type: str = "int"


class MergeConfig(TransformationConfig):
    name: Literal["merge"]
    other_axis: str = ""
    linkers: List[str] = [""]


action_subclasses_union = Union[
    CyclicConfig, MapperConfig, ReverseConfig, TypeChangeConfig, MergeConfig
]


class AxisConfig(ConfigModel):
    axis_name: str = ""
    transformations: list[action_subclasses_union]


path_subclasses_union = Union[str, int, float]


class GribJumpAxesConfig(ConfigModel):
    axis_name: str = ""
    values: List[str] = [""]


class Config(ConfigModel):
    axis_config: List[AxisConfig] = []
    compressed_axes_config: List[str] = [""]
    pre_path: Optional[Dict[str, path_subclasses_union]] = {}
    alternative_axes: List[GribJumpAxesConfig] = []


class CovjsonKitConfig(ConfigModel):
    param_db: str = "ecmwf"


class PolytopeMarsConfig(ConfigModel):

    datacube: DatacubeConfig = DatacubeConfig()
    options: Config = Config()
    coverageconfig: CovjsonKitConfig = CovjsonKitConfig()
