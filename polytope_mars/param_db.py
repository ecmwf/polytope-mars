"""Parameter metadata lookups (id, short name, long name, units).

polytope-mars resolves parameter metadata itself and hands encoders plain
:class:`~polytope_mars.blocks.ParamInfo` objects.  The data files are covjsonkit's copy of the ECMWF
parameter database, ``covjsonkit/data/<param_db>/{param,param_id,unit}.json``, read here directly:
``covjsonkit.param_db`` loads its configuration at import time and re-reads the files on every call.
``<param_db>`` is the config name (``encoders.covjson.param_db``, ``"ecmwf"`` or ``"dwd"``).

Every function accepts either the database name or a config object with a ``param_db`` attribute
(the shape of covjsonkit's ``CovjsonKitConfig``).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import covjsonkit

__all__ = [
    "get_param_from_db",
    "get_param_id_from_db",
    "get_param_ids",
    "get_params",
    "get_unit_from_db",
    "get_units",
]

_DATA = Path(covjsonkit.__file__).parent / "data"


def _db_name(conf) -> str:
    if conf is None:
        return "ecmwf"
    if isinstance(conf, str):
        return conf
    if isinstance(conf, dict):
        return conf.get("param_db", "ecmwf")
    return getattr(conf, "param_db", "ecmwf")


@lru_cache(maxsize=None)
def _load(db: str, name: str) -> dict:
    if not db or "/" in db or "\\" in db or db.startswith("."):
        raise ValueError(f"Invalid param_db name {db!r}")
    path = _DATA / db / f"{name}.json"
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        raise ValueError(f"Unknown param_db {db!r}: {path} does not exist") from None
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"Cannot read param_db {db!r} file {path}: {e}") from e


def get_param_ids(conf=None) -> dict:
    """``{short name: param id}`` for the database ``conf``."""
    return _load(_db_name(conf), "param_id")


def get_params(conf=None) -> dict:
    """``{param id (str): {shortname, name, description, unit_id, ...}}`` for the database ``conf``."""
    return _load(_db_name(conf), "param")


def get_units(conf=None) -> dict:
    """``{unit id (str): {name, ...}}`` for the database ``conf``."""
    return _load(_db_name(conf), "unit")


def get_param_id_from_db(param, conf=None):
    """Param id of the short name ``param``."""
    return get_param_ids(conf)[str(param)]


def get_param_from_db(param_id, conf=None) -> dict:
    """Database entry of ``param_id`` (an id, or a short name that is resolved first)."""
    try:
        param_id = int(param_id)
    except (TypeError, ValueError):
        param_id = get_param_id_from_db(param_id, conf)
    return get_params(conf)[str(param_id)]


def get_unit_from_db(unit_id, conf=None) -> dict:
    return get_units(conf)[str(unit_id)]
