"""Block IR between the extraction loop and the output encoders.

The extraction loop (:mod:`polytope_mars.extract`) walks the sliced request tree and emits, per
request, one :class:`RequestHeader` followed by a stream of blocks; an encoder
(:mod:`polytope_mars.encoders`) turns them into bytes.  These are plain data objects: encoders only
read attributes and must not depend on polytope-feature or on this module (covjsonkit consumes them
structurally).

Emission order per field group (one output coverage for MultiPoint domains)::

    CoordsBlock
    for param in group.params:
        for level in group.levels (or [None] when group.levels == ()):
            ValuesBlock
    GroupEnd

A group is one block of points: a field is fetched whole, so the ``band`` / ``offset`` / ``n_bands``
attributes below are always 0, 0 and 1.  They are kept because covjsonkit's stream encoder reads them
structurally (it groups by ``n_bands`` and places a block by its ``band`` and ``offset``); they can be
dropped from the IR and from the encoder together, in one change on both sides.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

__all__ = ["CoordsBlock", "FieldGroup", "GroupEnd", "ParamInfo", "RequestHeader", "ValuesBlock"]


@dataclass(frozen=True)
class ParamInfo:
    id: str  # e.g. "167"
    shortname: str  # "2t"
    name: str  # "2 metre temperature"
    unit: str  # "K"
    description: str  # may be ""


@dataclass(frozen=True)
class RequestHeader:
    #: request feature type ("boundingbox", "polygon", "timeseries", ...)
    feature_type: str
    #: "MultiPoint" | "PointSeries" | "VerticalProfile" | "Trajectory"
    domain_type: str
    #: which group-path key feeds the t axis: "date" | "hdate" | "step" | "month"
    time_axis: str
    #: emission order
    parameters: tuple[ParamInfo, ...]
    #: request keys common to all coverages, insertion order preserved
    mars_metadata: dict[str, str]
    #: encoder-specific knobs (e.g. legacy variant selection); see ``polytope_mars.extract``
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class FieldGroup:
    #: 0-based emission order
    index: int
    #: group-fixed MARS keys (date, time, step, number, hdate, month, year, ...)
    path: dict[str, str]
    #: ISO-8601 'Z' datetimes for the coverage t axis, computed by polytope-mars
    t: tuple[str, ...]
    #: param ids PRESENT in this group (the ones gribjump has a message for), emission order
    params: tuple[str, ...]
    #: levelist values, () when none (encoders treat () as one implicit level 0 where legacy did)
    levels: tuple[Any, ...]
    #: points per (param, level)
    n_points: int
    #: always 1: a field is never split (see the module doc)
    n_bands: int
    #: per-coverage mars:metadata exactly as legacy produced it (keys + order)
    mars_metadata: dict[str, Any]


@dataclass(frozen=True)
class CoordsBlock:
    group: FieldGroup
    #: always 0 (see the module doc)
    band: int
    #: point offset within the field, always 0
    offset: int
    #: float64 [n]
    lat: np.ndarray
    #: float64 [n]
    lon: np.ndarray


@dataclass(frozen=True)
class ValuesBlock:
    group: FieldGroup
    param: str
    #: one of group.levels, or None when levels == ()
    level: Any
    #: always 0, as on CoordsBlock
    band: int
    offset: int
    #: float64 [n]; NaN where missing
    values: np.ndarray


@dataclass(frozen=True)
class GroupEnd:
    group: FieldGroup
