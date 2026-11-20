"""Request-size checks that run before slicing (``limits.max_points_per_field``, ``limits.max_tree_bytes``).

Two things about a request can exhaust the pod before any value is fetched:

* **one field too large to extract whole** -- ``max_points_per_field`` against
  :func:`estimate_points_per_field` (the feature's area times the grid density);
* **a request tree too large to hold** -- ``max_tree_bytes`` against :func:`estimate_tree_bytes`
  (how many spatial sub-trees the request branches into, times the points of one field).

The second one is the shape polytope-feature cannot compress: a *branching* axis gets one node, one
spatial sub-tree and one slice per value, so a request's tree grows with the product of those axes'
value counts.  An axis branches when

* it is **merged** with another axis (a ``merge`` transformation in ``options.axis_config``):
  ``datacube.py`` never compresses a merged axis ("do not compress merged axes"), so every value of
  the merged pair is its own branch; or
* it is **not in** ``options.compressed_axes_config``.

What this estimate cannot see: a union whose leaf axis stays uncompressed (the pieces of a polygon,
tagged points), and any axis whose value count the request string does not give away (``ALL``,
step/time ranges in units the counters do not parse), which count as one.  The exact check after
``prepare`` (:meth:`polytope_mars.extract.BlockExtractor._prepare`) is the backstop for those.
"""

from __future__ import annotations

import math

from .utils.datetimes import count_dates, count_steps, count_times

__all__ = [
    "branching_value_counts",
    "estimate_points_per_field",
    "estimate_tree_branches",
    "estimate_tree_bytes",
    "format_bytes",
    "grid_density",
    "merged_axes",
    "request_value_count",
    "tree_byte_limit",
]

#: Earth surface in km² (sphere of radius 6371 km).
EARTH_AREA_KM2 = 4 * math.pi * 6371.0**2
#: km per degree of latitude.
KM_PER_DEG = math.pi * 6371.0 / 180.0

#: Request keys that are never datacube axes (and so never branch).
NON_AXIS_KEYS = frozenset({"feature", "format"})


def _options_dict(options) -> dict:
    if hasattr(options, "model_dump"):
        options = options.model_dump()
    return options or {}


def _mapper(options) -> dict | None:
    for axis in _options_dict(options).get("axis_config", []) or []:
        for tr in axis.get("transformations", []) or []:
            if tr.get("name") == "mapper":
                return tr
    return None


def grid_density(options, latitude: float = 0.0) -> float | None:
    """Grid points per km² near ``latitude`` for the mapper in ``options``; None when unknown."""
    m = _mapper(options)
    if m is None:
        return None
    kind, res = m.get("type"), m.get("resolution")
    cos_lat = max(math.cos(math.radians(latitude)), 1e-3)
    if kind == "lambert_conformal":
        dx, dy = m.get("Dx"), m.get("Dy")
        if isinstance(dx, (int, float)) and isinstance(dy, (int, float)) and dx > 0 and dy > 0:
            return 1e6 / (dx * dy)
        return None
    if kind == "local_regular":
        local = m.get("local")
        sizes = res if isinstance(res, (list, tuple)) else (res, res)
        if not (
            isinstance(local, (list, tuple)) and len(local) == 4 and all(isinstance(n, int) and n > 0 for n in sizes)
        ):
            return None
        d_lat = abs(local[1] - local[0]) / sizes[0]
        d_lon = abs(local[3] - local[2]) / sizes[1]
        if d_lat == 0 or d_lon == 0:
            return None
        return 1.0 / ((d_lat * KM_PER_DEG) * (d_lon * KM_PER_DEG * cos_lat))
    if not isinstance(res, int) or res <= 0:
        return None
    if kind == "octahedral":
        return (4 * res * res + 36 * res) / EARTH_AREA_KM2
    if kind in ("healpix", "healpix_nested"):
        return 12 * res * res / EARTH_AREA_KM2
    if kind == "regular":
        step = 90.0 / res
        return 1.0 / ((step * KM_PER_DEG) * (step * KM_PER_DEG * cos_lat))
    return None


def _centre_latitude(feature) -> float:
    for attr in ("points", "center", "shape"):
        pts = getattr(feature, attr, None)
        if not pts:
            continue
        flat = pts
        while flat and isinstance(flat[0], (list, tuple)) and flat[0] and isinstance(flat[0][0], (list, tuple)):
            flat = [p for poly in flat for p in poly]
        try:
            lats = [float(p[0]) for p in flat]
        except (TypeError, ValueError, IndexError):
            continue
        if lats:
            return sum(lats) / len(lats)
    return 0.0


def estimate_points_per_field(feature, options) -> float | None:
    """Points one field of ``feature`` covers, from the feature area and the grid density.

    Point features (timeseries, position, vertical profile) count their points; area features
    (bounding box, polygon, circle) use their area in km² times the grid density.  None when either is
    unknown (trajectory, shapefile, irregular grids) or not a finite number (``get_boundingbox_area``
    returns NaN for a pole-to-pole box): every limit built on this estimate is then not enforced.
    """
    name = feature.name()
    if name in ("Time Series", "Position", "Vertical Profile"):
        return len(getattr(feature, "points", []) or [])
    area = None
    if name == "Bounding Box":
        area = getattr(feature, "area_bb", None)
    elif name in ("Polygon", "Circle"):
        area = getattr(feature, "area", None)
    if not isinstance(area, (int, float)) or not math.isfinite(area) or area <= 0:
        return None
    density = grid_density(options, _centre_latitude(feature))
    if density is None:
        return None
    return area * density


def merged_axes(options) -> set:
    """Axis names on either side of a ``merge`` transformation: the axes polytope-feature never compresses."""
    merged: set = set()
    for axis in _options_dict(options).get("axis_config", []) or []:
        for tr in axis.get("transformations", []) or []:
            if tr.get("name") == "merge":
                merged.add(axis.get("axis_name"))
                other = tr.get("other_axis")
                if other:
                    merged.add(other)
    return merged


def request_value_count(key: str, value) -> int:
    """How many values a MARS request string holds; 1 when the string does not say.

    Ranges are inclusive and expanded the way the request is
    (:mod:`polytope_mars.utils.datetimes`).  ``ALL`` and anything unparseable count as one value:
    they are documented gaps of the pre-slice estimate, not errors.
    """
    text = str(value)
    try:
        if key in ("date", "hdate"):
            return count_dates(text)
        if key == "time":
            return count_times(text)
        if key == "step":
            return count_steps(text)
        parts = text.split("/")
        if "to" not in parts:
            return len(parts)
        to = parts.index("to")
        by = int(parts[parts.index("by") + 1]) if "by" in parts else 1
        return len(range(int(parts[to - 1]), int(parts[to + 1]) + 1, by))
    except (ArithmeticError, IndexError, TypeError, ValueError):
        return 1


def branching_value_counts(request: dict, options) -> dict:
    """``{request key: value count}`` for every multi-valued key whose axis will branch the tree.

    A merged axis branches however the deployment compresses it; any other axis branches when it is
    missing from ``compressed_axes_config``.
    """
    merged = merged_axes(options)
    compressed = set(_options_dict(options).get("compressed_axes_config", []) or [])
    counts = {}
    for key, value in (request or {}).items():
        if key in NON_AXIS_KEYS:
            continue
        if key not in merged and key in compressed:
            continue
        count = request_value_count(key, value)
        if count > 1:
            counts[key] = count
    return counts


def estimate_tree_branches(request: dict, options) -> int:
    """Spatial sub-trees ``request`` will slice: the product of its branching axes' value counts."""
    branches = 1
    for count in branching_value_counts(request, options).values():
        branches *= count
    return branches


def estimate_tree_bytes(request: dict, feature, options, bytes_per_point_tree: int) -> float | None:
    """Bytes the request tree will cost: branches x points per field x ``bytes_per_point_tree``.

    None when the points per field are unknown (:func:`estimate_points_per_field`), as for the
    per-field limit: the tree limit is then enforced only after ``prepare``.
    """
    points = estimate_points_per_field(feature, options)
    if points is None:
        return None
    return estimate_tree_branches(request, options) * points * bytes_per_point_tree


def tree_byte_limit(limits) -> int | None:
    """``limits.max_tree_bytes``, or half of ``limits.memory_budget_bytes``, or None when neither is set.

    Half the budget: the tree is resident for the whole request, *beside* the extraction unit the
    budget covers, so a tree larger than half of it leaves no room to extract from.
    """
    explicit: int | None = getattr(limits, "max_tree_bytes", None)
    if explicit is not None:
        return explicit
    budget: int | None = getattr(limits, "memory_budget_bytes", None)
    if budget is None:
        return None
    return budget // 2


def format_bytes(n: float) -> str:
    """A byte count as a client-facing size: ``8.3 GB``, ``412 MB``, ``3.4 kB``, ``900 bytes``."""
    for unit, scale in (("GB", 1e9), ("MB", 1e6), ("kB", 1e3)):
        if n >= scale:
            value = n / scale
            return f"{value:.1f} {unit}" if value < 10 else f"{value:.0f} {unit}"
    return f"{n:.0f} bytes"
