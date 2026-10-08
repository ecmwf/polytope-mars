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
    """Deprecated: use ``limits.bytes_per_value``.

    Phase 2 sized an extraction unit with one constant per grid mapper family, because HEALPix nested
    cost ~2.5x more per value than the other grids.  That difference is not a property of the grid but
    of the number of gribjump index *ranges* a field needs, which the sizing now counts from the
    prepared tree (:mod:`polytope_mars.sizing`, :mod:`polytope_mars.grid_ranges`).  A config that still
    sets this key has its ``default`` entry used as ``limits.bytes_per_value``; the per-mapper entries
    are ignored.
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
    """What bounds one request: polygon size, and the memory one ``datacube.get`` may cost.

    The unit sizing (:mod:`polytope_mars.sizing`) plans a unit of ``k`` field groups when

        ``buffer_cpp(unit) x safety_factor``
        ``  + bytes_per_point_call x n_points x n_subtrees``
        ``  + bytes_per_value x python_values``
        ``  + 2 x the encoder's max_fragment_bytes  <=  memory_budget_bytes``

    with ``buffer_cpp(unit) = n_fields x (8 x n_points + n_points / 8 + bytes_per_range x
    n_ranges)`` (gribjump's own residency, the only term the safety factor applies to),
    ``n_subtrees`` the spatial sub-trees the call asks for (one array-backed bulk node each) and
    ``python_values`` the values the Python side holds at once: **one field group** on the
    per-field path (``per_field_consumption``, the default) and the whole unit without it.  Two
    hard caps apply on top, independent of the budget: ``max_fields_per_call`` and
    ``max_values_per_unit``.  Without a budget a unit is one field group, as in Phase 2.

    A **field** is never split: a group whose fields do not fit one call together is fetched one
    (param, level) per call, and a request one field of which does not fit at all is refused
    (``max_points_per_field`` is the explicit, pre-slicing form of that refusal).

    ``bytes_per_value``, ``bytes_per_point_call`` and ``bytes_per_range`` are measured
    (MEASUREMENTS.md, ``python tools/measure_memory.py calibrate``); only
    ``memory_budget_bytes`` has to be set per deployment.
    """

    #: max number of vertices over all polygons of a request
    max_polygon_points: int = 3600
    #: max points per field, estimated before slicing from the grid density and the feature area (None: off)
    max_points_per_field: Optional[int] = None
    #: memory one ``datacube.get`` may cost; None: one field group per call, nothing refused
    memory_budget_bytes: Optional[int] = None
    #: measured Python-side peak bytes per value held at once (the leaf arrays plus the float64
    #: field copy handed to the encoder), the same constant for every grid
    bytes_per_value: int = 32
    #: measured Python-side bytes per point of every spatial sub-tree a call asks for, paid once
    #: however many fields it asks for: the bulk node's own arrays (coordinates 16 B, grid indexes
    #: 8 B), which ``prepare`` builds and the call holds throughout, plus the sort its index ranges
    #: come from
    bytes_per_point_call: int = 32
    #: bytes one gribjump index range costs in an ``ExtractionResult``: two vector headers plus two
    #: heap allocations, for the values and the bitmap of that range
    bytes_per_range: int = 96
    #: multiplier on the estimated gribjump buffer of a unit
    safety_factor: float = 1.5
    #: hard cap on the values of one ``datacube.get``, independent of the estimate and of the
    #: budget (256M values ~ 2 GB of gribjump buffer at 8 B/value): a backstop, not a planner
    max_values_per_unit: Optional[int] = 256_000_000
    #: hard cap on the fields of one ``datacube.get``: keeps the request list gribjump has to parse
    #: (and the pruned tree) bounded however large the budget is
    max_fields_per_call: int = 1024
    #: consume a unit's fields one at a time (``FDBDatacube.get_iter``) instead of fetching the
    #: whole unit with ``FDBDatacube.get``: the Python side then holds one field group instead of
    #: the whole unit, so units may be as large as gribjump's own buffer allows.  On by default;
    #: turning it off restores the whole-unit ``get`` (and the smaller units that go with it).
    #: Ignored by a datacube that has no ``get_iter`` (:mod:`polytope_mars.field_stream`).
    per_field_consumption: bool = True
    #: Deprecated alias of ``bytes_per_value`` (its ``default`` entry).
    bytes_per_point: Optional[BytesPerPointConfig] = None

    @model_validator(mode="after")
    def _check_limits(self):
        for name in ("bytes_per_value", "bytes_per_point_call", "bytes_per_range", "safety_factor"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"limits.{name} must be positive, got {value!r}")
        if self.max_values_per_unit is not None and self.max_values_per_unit < 1:
            raise ValueError(f"limits.max_values_per_unit must be positive or null, got {self.max_values_per_unit!r}")
        if self.max_fields_per_call < 1:
            raise ValueError(f"limits.max_fields_per_call must be positive, got {self.max_fields_per_call!r}")
        if self.bytes_per_point is not None and "bytes_per_value" not in self.model_fields_set:
            logging.debug("polytope-mars config: 'limits.bytes_per_point' is deprecated, use 'limits.bytes_per_value'")
            object.__setattr__(self, "bytes_per_value", self.bytes_per_point.default)
        return self


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
