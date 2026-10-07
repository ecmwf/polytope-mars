"""Request-size checks that run before slicing (``limits.max_points_per_field``)."""

from __future__ import annotations

import math

__all__ = ["estimate_points_per_field", "grid_density"]

#: Earth surface in km² (sphere of radius 6371 km).
EARTH_AREA_KM2 = 4 * math.pi * 6371.0**2
#: km per degree of latitude.
KM_PER_DEG = math.pi * 6371.0 / 180.0


def _mapper(options) -> dict | None:
    if hasattr(options, "model_dump"):
        options = options.model_dump()
    for axis in (options or {}).get("axis_config", []) or []:
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
    unknown (trajectory, shapefile, irregular grids): the limit is then not enforced.
    """
    name = feature.name()
    if name in ("Time Series", "Position", "Vertical Profile"):
        return len(getattr(feature, "points", []) or [])
    area = None
    if name == "Bounding Box":
        area = getattr(feature, "area_bb", None)
    elif name in ("Polygon", "Circle"):
        area = getattr(feature, "area", None)
    if not isinstance(area, (int, float)) or area <= 0:
        return None
    density = grid_density(options, _centre_latitude(feature))
    if density is None:
        return None
    return area * density
