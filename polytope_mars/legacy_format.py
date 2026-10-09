"""Value formatting rules of the legacy covjsonkit encoders (covjsonkit 0.2.26), reproduced exactly.

The streaming pipeline computes the coverage ``t`` values and ``mars:metadata`` in polytope-mars
(:mod:`polytope_mars.coverage_plan`); these helpers are ports of the covjsonkit functions that
produced those strings and numbers, so the output stays byte-identical.  Odd results (space-separated
datetimes on the ``_step`` path, ``int`` realization, ...) are preserved on purpose; see CHANGES.md.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

__all__ = [
    "LEGACY_WALKERS",
    "normalize_step_value",
    "referencing_coordinates",
    "parse_step_string",
    "reforecast_stringify",
    "step_timedelta",
    "stamp_date_plus_step",
    "stamp_date_plus_time",
    "timedelta_to_step_string",
    "tree_metadata",
]


def _hours_minutes(td: timedelta) -> tuple[int, int]:
    total_seconds = td // timedelta(seconds=1)  # floor, like legacy int(td.total_seconds()) for td >= 0
    return total_seconds // 3600, (total_seconds % 3600) // 60


def timedelta_to_step_string(td: timedelta) -> str:
    """covjsonkit ``timedelta_to_step_string``: 13h30m -> "13h30m", 13h -> "13h", 0 -> "0h"."""
    hours, minutes = _hours_minutes(td)
    if hours > 0 and minutes > 0:
        return f"{hours}h{minutes}m"
    if hours > 0:
        return f"{hours}h"
    if minutes > 0:
        return f"{minutes}m"
    return "0h"


def parse_step_string(step_str) -> float:
    """covjsonkit ``parse_step_string``: "13h30m" -> 13.5 (hours)."""
    if isinstance(step_str, (int, float)):
        return float(step_str)
    original = step_str = str(step_str)
    hours = 0.0
    minutes = 0.0
    try:
        if "h" in step_str:
            parts = step_str.split("h")
            hours = float(parts[0])
            step_str = parts[1] if len(parts) > 1 else ""
        if "m" in step_str and step_str:
            minutes = float(step_str.replace("m", ""))
    except ValueError:
        raise ValueError(f"Cannot parse step {original!r}; expected e.g. '13h', '30m' or '13h30m'") from None
    return hours + (minutes / 60.0)


def normalize_step_value(step):
    """covjsonkit ``normalize_step_value``: whole hours -> int, sub-hourly -> "XhYm", strings unchanged."""
    if isinstance(step, str):
        return step
    if isinstance(step, (timedelta, pd.Timedelta, np.timedelta64)):
        td = pd.Timedelta(step).to_pytimedelta()
        hours, minutes = _hours_minutes(td)
        if minutes > 0:
            return timedelta_to_step_string(td)
        return hours
    if isinstance(step, np.integer):
        return step.item()
    if isinstance(step, int):
        return step
    if isinstance(step, (float, np.floating)):
        x = step.item() if isinstance(step, np.floating) else step
        if not math.isfinite(x):
            return str(step)
        hours = math.trunc(x)
        minutes = math.trunc(x * 60) % 60
        if minutes > 0:
            return f"{hours}h{minutes}m" if hours > 0 else f"{minutes}m"
        return hours
    return str(step)


def step_timedelta(step) -> timedelta:
    """covjsonkit ``Encoder._reforecast_step_timedelta`` (of a normalized step)."""
    if isinstance(step, timedelta):
        return step
    if isinstance(step, np.timedelta64):
        return pd.to_timedelta(step).to_pytimedelta()
    if isinstance(step, str):
        return timedelta(hours=parse_step_string(step))
    try:
        return timedelta(hours=float(step))
    except (TypeError, ValueError):
        return timedelta(0)


def time_offset(value) -> timedelta:
    """covjsonkit ``Encoder._reforecast_timedelta``."""
    if value is None:
        return timedelta(0)
    if isinstance(value, timedelta):
        return value
    return pd.to_timedelta(value).to_pytimedelta()


def reforecast_stringify(value):
    """covjsonkit ``Encoder._reforecast_stringify`` (mars:metadata values on the reforecast path)."""
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, (np.datetime64, np.timedelta64, timedelta)):
        return str(value)
    return value


def stamp_date_plus_step(date_z: str, step, time_off=None) -> str:
    """``date + step`` as the PointSeries/VerticalProfile ``from_polytope`` walkers print it.

    ``date_z`` is the legacy ``f"{date}Z"`` string.  Integer steps are hours; a string step that is
    not an integer is reduced to its first character, exactly like legacy (``int(step[0])``).
    """
    date = date_z[:-1] if isinstance(date_z, str) and date_z.endswith("Z") else date_z
    fmt = "%Y%m%dT%H%M%S"
    start = datetime.strptime(pd.Timestamp(date).strftime(fmt), fmt)
    if time_off is not None:
        start = start + time_off
    if isinstance(step, timedelta):
        return (start + step).isoformat() + "Z"
    try:
        hours = int(step)
    except ValueError:
        try:
            hours = int(step[0])
        except (ValueError, TypeError, IndexError):
            raise ValueError(f"Cannot convert step {step!r} to hours") from None
    return (start + timedelta(hours=hours)).isoformat() + "Z"


def stamp_date_plus_time(date_z: str, time) -> str:
    """``date + time`` as ``walk_tree_step`` prints it: ``"2020-01-01 06:00:00Z"`` (space, not ``T``)."""
    return str(pd.Timestamp(date_z) + time).split("+")[0] + "Z"


# Axes each legacy walker keeps out of mars:metadata, and whether it writes "Forecast date" at the date node.
LEGACY_WALKERS = {
    # Encoder.walk_tree (date_key="date")
    "date": {"exclude": ("latitude", "longitude", "param", "date", "time"), "forecast_date_axes": ("date", "time")},
    # Encoder.walk_tree (date_key="hdate")
    "hdate": {"exclude": ("latitude", "longitude", "param", "hdate"), "forecast_date_axes": ("hdate", "time")},
    # Encoder.walk_tree_step
    "step": {"exclude": ("latitude", "longitude", "param", "date", "time"), "forecast_date_axes": ()},
    # Encoder.walk_tree_month
    "month": {"exclude": ("latitude", "longitude", "param", "year", "month"), "forecast_date_axes": ()},
}

#: The coordinate name sets the legacy encoders wrote (the trajectory variant is spelled out below).
_LATLON = ("latitude", "longitude", "levelist")
_XYZ = ("x", "y", "z")


def referencing_coordinates(domain_type: str, feature_type: str, time_axis: str) -> tuple[str, ...]:
    """Coordinate names of the collection's reference system, as the legacy encoders wrote them.

    Which of ``latitude/longitude/levelist``, ``x/y/z`` or ``t/x/y/z`` a collection declares follows from
    the legacy encoder method that served the request rather than from the coordinates themselves, so it
    is a table over (domain type, feature type, time-axis role) like :data:`LEGACY_WALKERS` above.  The
    composite axis of every coverage declares the same names.  Preserved quirk 8 in CHANGES.md.

    Shapefile requests arrive here as ``MultiPoint`` with their own feature type, which is how they keep
    ``x/y/z``.
    """
    if domain_type == "Trajectory":
        return _LATLON if time_axis == "hdate" else ("t", "x", "y", "z")
    if domain_type == "VerticalProfile":
        return _LATLON
    if domain_type == "PointSeries":
        if time_axis == "step":
            return _XYZ
        if time_axis == "month" and feature_type == "position":
            return _XYZ
        return _LATLON
    # MultiPoint
    if time_axis == "hdate":
        return _LATLON
    if time_axis == "date":
        return _LATLON if feature_type in ("boundingbox", "circle") else _XYZ
    if time_axis == "month":
        return _LATLON if feature_type == "circle" else _XYZ
    return _XYZ


def _walker_value(axis: str, value, walker: str):
    if isinstance(value, np.datetime64):
        return str(value)
    if walker == "month":
        return value
    if isinstance(value, timedelta):
        return timedelta_to_step_string(value)
    if axis == "step":
        return normalize_step_value(value)
    return value


def tree_metadata(nodes, walker: str) -> dict:
    """The ``mars_metadata`` dict a legacy walker accumulates over the non-spatial tree nodes.

    ``nodes`` is the depth-first sequence of ``(axis_name, values)`` of every non-spatial node
    (root excluded).  Keys appear in first-visit order and hold the ``values[0]`` of the last visit,
    as in the legacy walkers, which shared one dict over the whole walk.
    """
    spec = LEGACY_WALKERS[walker]
    meta: dict = {}
    for axis, values in nodes:
        if axis not in spec["exclude"]:
            meta[axis] = _walker_value(axis, values[0], walker)
        if axis in spec["forecast_date_axes"]:
            meta["Forecast date"] = str(values[0])
    return meta
