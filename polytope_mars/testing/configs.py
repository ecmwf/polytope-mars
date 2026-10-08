"""Deployment-faithful PolytopeMars configs and axis tables for the fake gribjump.

The ``options`` blocks are copied verbatim from polytope-config:

* ``efas_local_regular``: ``location/bologna/config.yaml`` ``set_metadata_efas``
  (EFAS LISFLOOD 2969x4529 ``local_regular`` grid);
* ``octahedral_1280``: ``location/bologna/config.yaml`` ``tc-fe``/``fe`` pool ``options``
  (ecmwf-time-critical, O1280);
* ``healpix_1024``: ``location/lumi/config.yaml`` ``set_metadata_climate_dt``
  (climate-dt HEALPix nested 1024);
* ``on_demand_extremes_dt``: ``location/lumi/config.yaml`` ``set_metadata_on_demand_extremes_dt``
  (static Lambert conformal block; the fe-worker's dynamic-grid lookup is not reproduced).

:func:`fake_gribjump_config_dict` turns one of those blocks into the per-request config
the fe-worker (``polytope-server/workers/polytope-fe-worker/polytope.py``) hands to
``PolytopeMars``: ``pre_path`` becomes the dict of single-valued pre-path keys of the
request, and on LUMI (``separate_datetime: true``) the merged ``date``/``time`` axis is
split for climate-dt timeseries/polygon requests.
"""

from __future__ import annotations

import copy

from ..config import PolytopeMarsConfig
from .fake_gribjump import FakeGribJump

__all__ = [
    "GRIDS",
    "default_axes",
    "deployment_options",
    "fake_gribjump_config",
    "fake_gribjump_config_dict",
    "make_fake_gribjump",
]

_TYPE_INT = [{"name": "type_change", "type": "int"}]
_MERGE_DATE_TIME = [{"name": "merge", "other_axis": "time", "linkers": ["T", "00"]}]

_EFAS = {
    "options": {
        "axis_config": [
            {"axis_name": "time", "transformations": [{"name": "type_change", "type": "time"}]},
            {"axis_name": "hdate", "transformations": [{"name": "type_change", "type": "date"}]},
            {"axis_name": "date", "transformations": [{"name": "type_change", "type": "date"}]},
            {
                "axis_name": "values",
                "transformations": [
                    {
                        "name": "mapper",
                        "type": "local_regular",
                        "resolution": [2969, 4529],
                        "axes": ["latitude", "longitude"],
                        "local": [22.758333333333333, 72.24166666666666, -25.241666666666667, 50.24166666666667],
                        "axis_reversed": {"latitude": True, "longitude": False},
                        "md5_hash": "60e55b0c1f432cca2a77cfa0c3b0717c",
                    }
                ],
            },
            {"axis_name": "latitude", "transformations": [{"name": "reverse", "is_reverse": True}]},
            {"axis_name": "longitude", "transformations": [{"name": "cyclic", "range": [-180, 180]}]},
            {"axis_name": "step", "transformations": _TYPE_INT},
            {"axis_name": "number", "transformations": _TYPE_INT},
            {"axis_name": "levelist", "transformations": _TYPE_INT},
        ],
        "compressed_axes_config": [
            "longitude",
            "latitude",
            "levtype",
            "step",
            "date",
            "time",
            "hdate",
            "domain",
            "origin",
            "expver",
            "param",
            "class",
            "stream",
            "type",
            "number",
            "levelist",
        ],
        "pre_path": ["class", "stream", "type", "levtype", "expver", "date", "origin", "domain", "model"],
        "alternative_axes": [],
    },
    "polygonrules": {"max_points": 3600, "max_area": 1800000000},
    "separate_datetime": False,
}

_O1280 = {
    "options": {
        "axis_config": [
            {"axis_name": "date", "transformations": _MERGE_DATE_TIME},
            {
                "axis_name": "values",
                "transformations": [
                    {"name": "mapper", "type": "octahedral", "resolution": 1280, "axes": ["latitude", "longitude"]}
                ],
            },
            {"axis_name": "latitude", "transformations": [{"name": "reverse", "is_reverse": True}]},
            {"axis_name": "longitude", "transformations": [{"name": "cyclic", "range": [0, 360]}]},
            {"axis_name": "step", "transformations": _TYPE_INT},
            {"axis_name": "number", "transformations": _TYPE_INT},
            {"axis_name": "levelist", "transformations": _TYPE_INT},
        ],
        "compressed_axes_config": [
            "longitude",
            "latitude",
            "levtype",
            "step",
            "date",
            "domain",
            "expver",
            "param",
            "class",
            "stream",
            "type",
            "number",
            "levelist",
        ],
        "pre_path": ["class", "stream", "type", "levtype", "expver", "date", "time", "domain", "model"],
        "alternative_axes": [],
    },
    "polygonrules": {"max_points": 3600, "max_area": 1800000000},
    "separate_datetime": False,
}

_HEALPIX_1024 = {
    "options": {
        "axis_config": [
            {"axis_name": "date", "transformations": _MERGE_DATE_TIME},
            {
                "axis_name": "values",
                "transformations": [
                    {
                        "name": "mapper",
                        "type": "healpix_nested",
                        "resolution": 1024,
                        "axes": ["latitude", "longitude"],
                    }
                ],
            },
            {"axis_name": "longitude", "transformations": [{"name": "cyclic", "range": [0, 360]}]},
            {"axis_name": "latitude", "transformations": [{"name": "reverse", "is_reverse": True}]},
            {"axis_name": "realization", "transformations": _TYPE_INT},
            {"axis_name": "month", "transformations": _TYPE_INT},
            {"axis_name": "year", "transformations": _TYPE_INT},
        ],
        "pre_path": [
            "activity",
            "class",
            "dataset",
            "date",
            "experiment",
            "expver",
            "generation",
            "levtype",
            "model",
            "month",
            "param",
            "realization",
            "resolution",
            "stream",
            "type",
            "year",
        ],
        "compressed_axes_config": [
            "date",
            "latitude",
            "levelist",
            "longitude",
            "month",
            "param",
            "realization",
            "time",
            "year",
        ],
    },
    "polygonrules": {"max_points": 3600, "max_area": 300000000},
    "separate_datetime": True,
}

_ON_DEMAND_EXTREMES_DT = {
    "options": {
        "axis_config": [
            {"axis_name": "date", "transformations": _MERGE_DATE_TIME},
            {
                "axis_name": "values",
                "transformations": [
                    {
                        "name": "mapper",
                        "type": "lambert_conformal",
                        "md5_hash": "1d66d6149ca01269994d180a23427e5a",
                        "is_spherical": True,
                        "radius": 6371229,
                        "nv": 0,
                        "nx": 1489,
                        "ny": 1489,
                        "LoVInDegrees": 353.671,
                        "Dx": 500,
                        "Dy": 500,
                        "latFirstInRadians": 0.9096562305555556,
                        "lonFirstInRadians": 6.077528447222222,
                        "LoVInRadians": 6.172541369444445,
                        "Latin1InRadians": 0.9702959069444445,
                        "Latin2InRadians": 0.9702959069444445,
                        "LaDInRadians": 0.9702959069444445,
                        "axes": ["latitude", "longitude"],
                    }
                ],
            },
            {"axis_name": "longitude", "transformations": [{"name": "cyclic", "range": [0, 360]}]},
            {"axis_name": "step", "transformations": [{"name": "type_change", "type": "subhourly_step"}]},
            {"axis_name": "number", "transformations": _TYPE_INT},
            {"axis_name": "levelist", "transformations": _TYPE_INT},
        ],
        "pre_path": ["class", "date", "dataset", "expver", "levtype", "param", "stream", "time", "type", "georef"],
        "compressed_axes_config": [
            "date",
            "latitude",
            "levelist",
            "longitude",
            "number",
            "param",
            "step",
            "time",
            "georef",
        ],
        "use_catalogue": False,
        "engine_options": {
            "step": "hullslicer",
            "date": "hullslicer",
            "levtype": "hullslicer",
            "georef": "hullslicer",
            "param": "hullslicer",
            "class": "hullslicer",
            "dataset": "hullslicer",
            "stream": "hullslicer",
            "expver": "hullslicer",
            "type": "hullslicer",
            "number": "hullslicer",
            "levelist": "hullslicer",
            "latitude": "quadtree",
            "longitude": "quadtree",
        },
    },
    "polygonrules": {"max_points": 3600, "max_area": 300000000},
    "separate_datetime": True,
}

#: Deployment blocks by grid name.
GRIDS = {
    "efas_local_regular": _EFAS,
    "octahedral_1280": _O1280,
    "healpix_1024": _HEALPIX_1024,
    "on_demand_extremes_dt": _ON_DEMAND_EXTREMES_DT,
}


def _steps(start, stop, by):
    return [str(s) for s in range(start, stop + 1, by)]


def _dates(*dates):
    return list(dates)


_HOURS = [f"{h:02d}00" for h in range(24)]
# 0 to 2h every 10 minutes, spelled the way the subhourly_step type change prints them.
_SUBHOURLY_STEPS = ["0", *(f"{m}m" for m in range(10, 60, 10)), "1", *(f"1h{m}m" for m in range(10, 60, 10)), "2"]

# Axis tables as gribjump would report them (string values), one dict per FDB sub-cube.
_AXES = {
    "efas_local_regular": [
        {
            "class": ["ce"],
            "stream": ["efas"],
            "type": ["fc"],
            "levtype": ["sfc"],
            "expver": ["0001"],
            "origin": ["ecmf"],
            "domain": ["g"],
            "model": ["lisflood"],
            "date": _dates("20240101", "20240102"),
            "time": ["0000", "1200"],
            "step": _steps(6, 360, 6),
            "param": ["240023", "240024"],
        },
        {
            # EFAS ensemble (the Volga 4-param request of REQUESTS.md): type pf with a number axis.
            "class": ["ce"],
            "stream": ["efas"],
            "type": ["pf"],
            "levtype": ["sfc"],
            "expver": ["0001"],
            "origin": ["ecmf"],
            "domain": ["g"],
            "model": ["lisflood"],
            "date": _dates("20240101", "20240102"),
            "time": ["0000", "1200"],
            "step": _steps(6, 360, 6),
            "number": _steps(1, 50, 1),
            "param": ["228141", "231002", "231026", "240023", "240024"],
        },
        {
            "class": ["ce"],
            "stream": ["efcl"],
            "type": ["sfo"],
            "levtype": ["sfc"],
            "expver": ["0001"],
            "origin": ["ecmf"],
            "domain": ["g"],
            "model": ["lisflood"],
            "date": ["20230101"],
            "hdate": _dates("20250101", "20250102", "20250103", "20250104", "20250105"),
            "time": ["0000", "0600", "1200", "1800"],
            "step": ["6", "12", "18", "24"],
            "param": ["240023"],
        },
    ],
    "octahedral_1280": [
        {
            "class": ["od"],
            "stream": ["oper"],
            "type": ["fc"],
            "levtype": ["sfc"],
            "expver": ["0001"],
            "domain": ["g"],
            "date": _dates("20240101", "20240102"),
            "time": ["0000", "1200"],
            "step": _steps(0, 90, 1) + _steps(93, 144, 3),
            "param": ["165", "166", "167", "228"],
        },
        {
            "class": ["od"],
            "stream": ["oper"],
            "type": ["fc"],
            "levtype": ["pl"],
            "expver": ["0001"],
            "domain": ["g"],
            "date": _dates("20240101", "20240102"),
            "time": ["0000", "1200"],
            "step": _steps(0, 90, 1) + _steps(93, 144, 3),
            "levelist": ["50", "100", "200", "250", "300", "500", "700", "850", "925", "1000"],
            "param": ["129", "130", "131", "157"],
        },
        {
            "class": ["od"],
            "stream": ["enfo"],
            "type": ["pf"],
            "levtype": ["sfc"],
            "expver": ["0001"],
            "domain": ["g"],
            "date": _dates("20240101", "20240102"),
            "time": ["0000", "1200"],
            "step": _steps(0, 144, 6),
            "number": _steps(1, 50, 1),
            "param": ["167", "228"],
        },
    ],
    "healpix_1024": [
        {
            "activity": ["projections"],
            "class": ["d1"],
            "dataset": ["climate-dt"],
            "experiment": ["ssp3-7.0"],
            "expver": ["0001"],
            "generation": ["1"],
            "levtype": ["sfc"],
            "model": ["ifs-nemo"],
            "realization": ["1"],
            "resolution": ["high"],
            "stream": ["clte"],
            "type": ["fc"],
            "date": _dates("20200101", "20200102", "20200103"),
            "time": _HOURS,
            "param": ["165", "166", "167"],
        },
        {
            "activity": ["projections"],
            "class": ["d1"],
            "dataset": ["climate-dt"],
            "experiment": ["ssp3-7.0"],
            "expver": ["0001"],
            "generation": ["1"],
            "levtype": ["pl"],
            "model": ["ifs-nemo"],
            "realization": ["1"],
            "resolution": ["high"],
            "stream": ["clte"],
            "type": ["fc"],
            "date": _dates("20200101", "20200102", "20200103"),
            "time": _HOURS,
            "levelist": ["500", "850", "1000"],
            "param": ["130", "157"],
        },
        {
            "activity": ["projections"],
            "class": ["d1"],
            "dataset": ["climate-dt"],
            "experiment": ["ssp3-7.0"],
            "expver": ["0001"],
            "generation": ["1"],
            "levtype": ["sfc"],
            "model": ["ifs-nemo"],
            "realization": ["1"],
            "resolution": ["high"],
            "stream": ["clmn"],
            "type": ["fc"],
            "year": ["2020", "2021"],
            "month": [str(m) for m in range(1, 13)],
            "param": ["167"],
        },
    ],
    "on_demand_extremes_dt": [
        {
            "class": ["d1"],
            "dataset": ["on-demand-extremes-dt"],
            "stream": ["oper"],
            "type": ["fc"],
            "levtype": ["sfc"],
            "expver": ["0099"],
            "georef": ["gcgkrb"],
            "date": ["20250926"],
            "time": ["0000"],
            "step": _SUBHOURLY_STEPS,
            "param": ["167", "165"],
        },
    ],
}


def deployment_options(grid: str) -> dict:
    """The deployment block for ``grid`` (``options`` with ``pre_path`` as a list of axis names)."""
    return copy.deepcopy(GRIDS[grid])


def default_axes(grid: str) -> list[dict]:
    """The default fake axis table (list of sub-cubes) for ``grid``."""
    return copy.deepcopy(_AXES[grid])


def make_fake_gribjump(grid: str, axes=None, **kwargs) -> FakeGribJump:
    """A :class:`FakeGribJump` over ``axes`` (default: :func:`default_axes` of ``grid``)."""
    return FakeGribJump(default_axes(grid) if axes is None else axes, **kwargs)


def _pre_path(request: dict, pre_path_axes: list) -> dict:
    # Same rule as the fe-worker: only single-valued pre-path keys are fixed.
    pre_path = {}
    for k, v in request.items():
        if k not in pre_path_axes:
            continue
        values = v.split("/") if isinstance(v, str) else v
        if isinstance(values, list):
            if len(values) == 1:
                pre_path[k] = values[0]
        else:
            pre_path[k] = values
    return pre_path


def _unmerge_date_time(request: dict, options: dict) -> None:
    # fe-worker unmerge_date_time_options (LUMI separate_datetime: true).
    if request.get("dataset") == "climate-dt" or request.get("class") == "ng" or request.get("stream") == "efcl":
        for mapping in options["axis_config"]:
            if mapping["axis_name"] in ("date", "hdate"):
                mapping["transformations"] = [{"name": "type_change", "type": "date"}]
        options["axis_config"].append(
            {"axis_name": "time", "transformations": [{"name": "type_change", "type": "time"}]}
        )


def fake_gribjump_config_dict(grid: str, request: dict | None = None) -> dict:
    """PolytopeMars config dict for ``grid``, specialised for ``request`` the way the fe-worker does it.

    Without a request, ``pre_path`` is empty.
    """
    block = deployment_options(grid)
    options = block["options"]
    pre_path_axes = options.pop("pre_path")
    options["pre_path"] = {}
    if request is not None:
        request = {
            k: (str(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v) for k, v in request.items()
        }
        options["pre_path"] = _pre_path(request, pre_path_axes)
        if block["separate_datetime"]:
            _unmerge_date_time(request, options)
    return {
        "datacube": {"type": "gribjump"},
        "options": options,
        "coverageconfig": {"param_db": "ecmwf"},
        "polygonrules": block["polygonrules"],
    }


def fake_gribjump_config(grid: str, request: dict | None = None) -> PolytopeMarsConfig:
    """Like :func:`fake_gribjump_config_dict` but validated into a :class:`PolytopeMarsConfig`."""
    return PolytopeMarsConfig.model_validate(fake_gribjump_config_dict(grid, request))
