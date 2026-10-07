import logging
from typing import Optional

from conflator import ConfigModel
from polytope_feature.options import Config
from pydantic import ConfigDict, model_validator


class DatacubeConfig(ConfigModel):
    type: str = "gribjump"
    config: str = "config.yaml"
    uri: str = "http://localhost:8000"


class CovjsonKitConfig(ConfigModel):
    param_db: str = "ecmwf"


class PolygonRulesConfig(ConfigModel):
    """Deprecated: use ``limits``. ``max_points`` maps to ``limits.max_polygon_points``; ``max_area`` is ignored."""

    # Max points is the max number of points in all polygons requested allowed
    max_points: Optional[int] = None
    # Ignored (the split_request machinery it drove is gone; memory is bounded by limits.memory_budget_bytes)
    max_area: Optional[float] = None


class CovjsonEncoderConfig(ConfigModel):
    #: name of the parameter database (``polytope_mars/data/<param_db>``)
    param_db: str = "ecmwf"


class EncodersConfig(ConfigModel):
    model_config = ConfigDict(extra="allow")

    covjson: CovjsonEncoderConfig = CovjsonEncoderConfig()


class BytesPerPointConfig(ConfigModel):
    """Peak bytes per extracted value of one ``datacube.get``, per grid mapper family.

    Seeded from polytope-mars ``MEASUREMENTS.md`` (Phase 0, bare ``datacube.get``: local_regular 48.5,
    octahedral 57.3, healpix_nested 121.6 B/value), rounded up with headroom for the per-field
    float64 copies and the encoder's per-block buffers.  Other mapper types use ``default``.
    """

    model_config = ConfigDict(extra="allow")

    default: int = 64
    local_regular: int = 64
    octahedral: int = 64
    healpix_nested: int = 160

    @model_validator(mode="after")
    def _check_extra_mappers(self):
        for name, value in (self.model_extra or {}).items():
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"limits.bytes_per_point.{name} must be a positive integer, got {value!r}")
        return self

    def for_mapper(self, mapper_type: Optional[str]) -> int:
        """Bytes per value for ``mapper_type`` (the ``type`` of the grid mapper transformation)."""
        if mapper_type:
            if mapper_type in type(self).model_fields:
                return getattr(self, mapper_type)
            if self.model_extra and mapper_type in self.model_extra:
                return self.model_extra[mapper_type]
        return self.default


class LimitsConfig(ConfigModel):
    #: max number of vertices over all polygons of a request
    max_polygon_points: int = 3600
    #: max points per field, estimated before slicing from the grid density and the feature area (None: off)
    max_points_per_field: Optional[int] = None
    #: memory budget of one extraction unit; None: never band (one unit per field group)
    memory_budget_bytes: Optional[int] = None
    bytes_per_point: BytesPerPointConfig = BytesPerPointConfig()


class PolytopeMarsConfig(ConfigModel):
    datacube: DatacubeConfig = DatacubeConfig()
    options: Config = Config()
    encoders: EncodersConfig = EncodersConfig()
    limits: LimitsConfig = LimitsConfig()
    #: Deprecated alias of ``encoders.covjson``.
    coverageconfig: Optional[CovjsonKitConfig] = None
    #: Deprecated alias of ``limits`` (``max_points`` -> ``max_polygon_points``; ``max_area`` ignored).
    polygonrules: Optional[PolygonRulesConfig] = None

    @model_validator(mode="after")
    def _apply_deprecated_aliases(self):
        # The deprecated keys only fill in what the new sections do not set explicitly.
        if self.coverageconfig is not None and "covjson" not in self.encoders.model_fields_set:
            logging.debug("polytope-mars config: 'coverageconfig' is deprecated, use 'encoders.covjson'")
            covjson = CovjsonEncoderConfig(param_db=self.coverageconfig.param_db)
            object.__setattr__(self.encoders, "covjson", covjson)
        if self.polygonrules is not None:
            logging.debug("polytope-mars config: 'polygonrules' is deprecated, use 'limits'")
            if self.polygonrules.max_points is not None and "max_polygon_points" not in self.limits.model_fields_set:
                object.__setattr__(self.limits, "max_polygon_points", self.polygonrules.max_points)
        return self
