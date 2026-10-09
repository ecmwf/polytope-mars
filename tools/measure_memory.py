"""Memory/time measurements of the legacy extraction pipeline against the fake gribjump.

Not a test. Each scenario runs in its own subprocess (clean RSS, own peak RSS); the parent
prints Markdown tables (the source of MEASUREMENTS.md).

    python tools/measure_memory.py                 # everything
    python tools/measure_memory.py slice get       # some groups
    python tools/measure_memory.py --run NAME      # one scenario, prints one JSON line

Groups:

* ``slice``: RSS/wall-time of ``Polytope.slice`` alone (one field), tree size and bytes per point.
* ``get``: RSS of a bare ``datacube.get`` (gribjump result assignment onto the tree, no encoding)
  per extracted value, per mapper family.
* ``e2e``: peak RSS of ``PolytopeMars.extract`` + ``json.dumps(...).encode()`` per value (the
  fe-worker's buffered path; run against a legacy checkout it measures the legacy pipeline).
* ``stream``: peak RSS growth of ``PolytopeMars.extract_stream`` with the output discarded, for
  several ``limits.memory_budget_bytes``.  ``--budget N`` (bytes, or ``none``) overrides the budget.
* ``ranges``: points and gribjump index ranges of one field, and what they cost in gribjump's buffer.
* ``tree``: what a prepared tree costs resident with the spatial fold off and on (its arrays are
  16 + 8 B/point per sub-tree against the row tree's ~9 B/point).
* ``calibrate``: peak of one unit of n fields on the per-field path, against the exact gribjump
  term, plus the least-squares fit of ``limits.bytes_per_point_call`` and ``limits.bytes_per_value``.
* ``targets``: what the planner does with the deployment's largest requests at a 1.5 and a 1.8 GiB
  budget (3 and 3.6 GiB pods) -- fields per call and call count, without fetching anything.
"""

import copy
import datetime
import gc
import json
import os
import resource
import subprocess
import sys
import time
import warnings
from typing import Any, cast

warnings.filterwarnings("ignore")

MiB = 1024 * 1024

CDT = {
    "activity": "projections",
    "class": "d1",
    "dataset": "climate-dt",
    "experiment": "ssp3-7.0",
    "expver": "0001",
    "generation": "1",
    "model": "ifs-nemo",
    "realization": "1",
    "resolution": "high",
    "type": "fc",
    "stream": "clte",
    "levtype": "sfc",
}
EFAS = {
    "class": "ce",
    "stream": "efas",
    "type": "fc",
    "levtype": "sfc",
    "expver": "0001",
    "origin": "ecmf",
    "domain": "g",
    "model": "lisflood",
    "date": "20240101",
    "time": "0000",
}
OD = {"class": "od", "stream": "oper", "type": "fc", "levtype": "sfc", "expver": "0001", "domain": "g"}
EUROPE_POLYGON = [[35, -10], [35, 30], [45, 40], [60, 40], [71, 30], [71, -10], [60, -15], [35, -10]]


def bbox(points):
    return {"type": "boundingbox", "points": points}


SCENARIOS = {
    # -- slice: one field, tree only ----------------------------------------------------------
    "slice_healpix1024_global_bbox": (
        "slice",
        "healpix_1024",
        {**CDT, "date": "20200101", "time": "0000", "param": "167", "feature": bbox([[-90, -180], [90, 180]])},
    ),
    "slice_healpix1024_europe_polygon": (
        "slice",
        "healpix_1024",
        {
            **CDT,
            "date": "20200101",
            "time": "0000",
            "param": "167",
            "feature": {"type": "polygon", "shape": EUROPE_POLYGON},
        },
    ),
    "slice_o1280_europe_bbox": (
        "slice",
        "octahedral_1280",
        {**OD, "date": "20240101", "time": "0000", "step": "0", "param": "167", "feature": bbox([[72, -25], [34, 45]])},
    ),
    "slice_efas_danube_bbox": (
        "slice",
        "efas_local_regular",
        {**EFAS, "step": "6", "param": "240023", "feature": bbox([[50.25, 8.15], [42.08, 29.73]])},
    ),
    # -- get: bare datacube.get, 4 fields per tree --------------------------------------------
    "get_local_regular": (
        "get",
        "efas_local_regular",
        {**EFAS, "step": "6/12", "param": "240023/240024", "feature": bbox([[50.25, 8.15], [42.08, 29.73]])},
    ),
    "get_healpix_nested": (
        "get",
        "healpix_1024",
        {**CDT, "date": "20200101", "time": "0000/1200", "param": "167/165", "feature": bbox([[55, -10], [35, 30]])},
    ),
    "get_octahedral": (
        "get",
        "octahedral_1280",
        {
            **OD,
            "date": "20240101",
            "time": "0000",
            "step": "0/6",
            "param": "167/165",
            "feature": bbox([[72, -25], [34, 45]]),
        },
    ),
    # -- e2e: extract + json.dumps + encode ---------------------------------------------
    "e2e_efas_switzerland_40steps": (
        "e2e",
        "efas_local_regular",
        {**EFAS, "step": "6/to/240/by/6", "param": "240023", "feature": bbox([[47.80, 5.95], [45.82, 10.47]])},
    ),
    "e2e_healpix1024_bbox_24h": (
        "e2e",
        "healpix_1024",
        {**CDT, "date": "20200101", "time": "0000/to/2300", "param": "167", "feature": bbox([[50, 0], [39.5, 10.5]])},
    ),
}

#: the climate-dt Europe box that was OOM-killed on LUMI at 24 hourly fields (~480k HEALPix points)
EUROPE_BBOX = bbox([[72, -25], [34, 45]])
#: half of EUROPE_BBOX (~240k HEALPix-1024 points), to show the range ratio does not depend on size
EUROPE_BBOX_NARROW = bbox([[72, -25], [34, 10]])
DANUBE_BBOX = bbox([[50.25, 8.15], [42.08, 29.73]])
GLOBAL_BBOX = bbox([[90, -180], [-90, 180]])
#: the Volga catchment of the EFAS ensemble request that was OOM-killed: 18 vertices, ~610k
#: EFAS points, the largest EFAS forecast request in the corpus (4 params x 50 members x 60 steps)
VOLGA_POLYGON = {
    "type": "polygon",
    "shape": [
        [59.10000000998955, 33.68333332332998],
        [59.75000000999007, 47.033333343329225],
        [56.26666667665396, 50.25000000999571],
        [40.899999989975065, 49.26666667666243],
        [43.83333332331073, 42.01666665666284],
        [45.700000009978886, 43.483333323329425],
        [45.716666676645566, 44.78333332332935],
        [46.54999998997956, 43.86666665666274],
        [48.733333343314634, 44.266666656662714],
        [52.31666665665082, 46.249999989995935],
        [52.3333333233175, 35.966666656663186],
        [54.39999998998581, 33.283333323330005],
        [57.0666666766546, 31.98333332333008],
        [57.900000009988595, 35.21666665666323],
        [58.16666665665547, 35.033333323329906],
        [58.33333332332227, 35.1833333233299],
        [58.79999998998931, 33.73333332332998],
        [59.10000000998955, 33.68333332332998],
    ],
}
#: the Switzerland catchment of `fe-oom-efas-pf-switzerland-ensemble`: ~18.8k points, 1 param,
#: 50 members x 60 steps (3,000 coverages), where the per-call field cap decides the call count
SWITZERLAND_POLYGON = {
    "type": "polygon",
    "shape": [
        [46.864427389000056, 10.453811076000136],
        [45.82071848599999, 9.002426798000073],
        [46.45217865000005, 8.399156128000072],
        [45.914459534000045, 7.831232137000143],
        [46.13046702100003, 5.958839966000113],
        [47.48909210300009, 6.9733000080001375],
        [47.80116607700008, 8.558216187000085],
        [46.864427389000056, 10.453811076000136],
    ],
}
#: the four EFAS ensemble parameters of the Volga request
VOLGA_PARAMS = "228141/231002/231026/240023"


def cdt(feature, **keys):
    return {**CDT, "date": "20200101", "time": "0000", "param": "167", "feature": feature, **keys}


def od(feature, **keys):
    return {**OD, "date": "20240101", "time": "0000", "step": "0", "param": "167", "feature": feature, **keys}


def efas(feature, **keys):
    return {**EFAS, "step": "6", "param": "240023", "feature": feature, **keys}


# -- ranges: points and gribjump index ranges of one field, and what they cost in gribjump's buffer
RANGE_SCENARIOS = {
    "ranges_healpix1024_global_bbox": ("healpix_1024", cdt(GLOBAL_BBOX)),
    "ranges_o1280_global_bbox": ("octahedral_1280", od(GLOBAL_BBOX)),
    "ranges_healpix1024_europe_bbox": ("healpix_1024", cdt(EUROPE_BBOX)),
    "ranges_healpix1024_europe_narrow_bbox": ("healpix_1024", cdt(EUROPE_BBOX_NARROW)),
    "ranges_o1280_europe_bbox": ("octahedral_1280", od(EUROPE_BBOX)),
    "ranges_efas_danube_bbox": ("efas_local_regular", efas(DANUBE_BBOX)),
    "ranges_efas_volga_polygon": ("efas_local_regular", efas(VOLGA_POLYGON)),
    "ranges_efas_switzerland_polygon": ("efas_local_regular", efas(SWITZERLAND_POLYGON)),
    "ranges_efas_whole_domain_bbox": ("efas_local_regular", efas(bbox([[72.24, -25.24], [22.76, 50.24]]))),
}

#: calibration of ``limits.bytes_per_point_call`` and ``limits.bytes_per_value``: one unit of n
#: fields, consumed field by field (the production path), per request shape.  ``axes`` are the group
#: axes a unit may batch, outermost first: the builder fills the first one, then multiplies by the
#: next, so "48 fields" is 48 hourly HEALPix groups (24 times x 2 dates) or 12 Volga groups of 4
#: params.  ``group_fields`` is params x levels of one group (the values the lazy path holds).
CALIBRATE_SHAPES = {
    "efas_danube": {
        "grid": "efas_local_regular",
        "builder": "efas",
        "feature": DANUBE_BBOX,
        "axes": [("step", [str(s) for s in range(6, 361, 6)])],
        "group_fields": 1,
    },
    "efas_volga": {
        "grid": "efas_local_regular",
        "builder": "efas",
        "feature": VOLGA_POLYGON,
        "axes": [("step", [str(s) for s in range(6, 361, 6)]), ("number", [str(n) for n in range(1, 51)])],
        "keys": {"type": "pf", "param": VOLGA_PARAMS, "number": "1"},
        "group_fields": 4,
    },
    "healpix1024_europe": {
        "grid": "healpix_1024",
        "builder": "cdt",
        "feature": EUROPE_BBOX,
        "axes": [("time", [f"{h:02d}00" for h in range(24)]), ("date", ["20200101", "20200102", "20200103"])],
        "group_fields": 1,
    },
    "o1280_europe": {
        "grid": "octahedral_1280",
        "builder": "od",
        "feature": EUROPE_BBOX,
        "axes": [("step", [str(s) for s in range(0, 91, 1)])],
        "group_fields": 1,
    },
}
CALIBRATE_FIELDS = (1, 4, 12, 48)


def calibrate_request(shape: dict, n_fields: int):
    """The request of ``n_fields`` fields of ``shape``, or None when the fake's axes cannot express it."""
    group_fields = shape["group_fields"]
    if n_fields % group_fields:
        return None
    remaining = n_fields // group_fields
    selection = {}
    for axis, values in shape["axes"]:
        take = min(len(values), remaining)
        if remaining % take:
            return None
        selection[axis] = "/".join(values[:take])
        remaining //= take
        if remaining == 1:
            break
    if remaining != 1:
        return None
    builder = {"cdt": cdt, "od": od, "efas": efas}[shape["builder"]]
    return builder(shape["feature"], **{**shape.get("keys", {}), **selection})


#: scenario name -> (shape, number of fields)
CALIBRATE_SCENARIOS = {
    f"calibrate_{shape}_{n}": (shape, n)
    for shape in CALIBRATE_SHAPES
    for n in CALIBRATE_FIELDS
    if calibrate_request(CALIBRATE_SHAPES[shape], n) is not None
}

DANUBE_10_STEPS = {**EFAS, "step": "6/to/60/by/6", "param": "240023", "feature": bbox([[50.25, 8.15], [42.08, 29.73]])}
# -- stream: extract_stream, output discarded; (kind, grid, request, memory_budget_bytes)
#: the climate-dt HEALPix Europe box x 24 hourly fields (the request that was OOM-killed on LUMI)
#: and the EFAS Danube box x 40 steps
HEALPIX_EUROPE_24H = {
    **CDT,
    "date": "20200101",
    "time": "/".join(f"{h:02d}00" for h in range(24)),
    "param": "167",
    "feature": EUROPE_BBOX,
}
DANUBE_40_STEPS = {**EFAS, "step": "6/to/240/by/6", "param": "240023", "feature": DANUBE_BBOX}
#: the three largest deployed request shapes, at a 1.5 and a 1.8 GiB budget (half of a 3 GiB and
#: of a 3.6 GiB pod): (grid, request, budgets)
BUDGETS = (3 * 1024**3 // 2, 9 * 1024**3 // 5)
VOLGA_ENSEMBLE_4PARAM = {
    **EFAS,
    "type": "pf",
    "param": VOLGA_PARAMS,
    "number": "/".join(str(n) for n in range(1, 51)),
    "step": "/".join(str(s) for s in range(6, 361, 6)),
    "feature": VOLGA_POLYGON,
}
SWITZERLAND_ENSEMBLE = {
    **EFAS,
    "type": "pf",
    "param": "240023",
    "number": "/".join(str(n) for n in range(1, 51)),
    "step": "/".join(str(s) for s in range(6, 361, 6)),
    "feature": SWITZERLAND_POLYGON,
}
TARGET_SCENARIOS = {
    "targets_efas_volga_ensemble_4param": ("efas_local_regular", VOLGA_ENSEMBLE_4PARAM, BUDGETS),
    "targets_efas_switzerland_ensemble": ("efas_local_regular", SWITZERLAND_ENSEMBLE, BUDGETS),
    "targets_healpix1024_europe_24h": ("healpix_1024", HEALPIX_EUROPE_24H, BUDGETS),
}

#: the polygon of `fe-oom-climate-dt-polygon-2027-hourly-year` (polytope-config
#: `location/lumi/requests.heavy-fe.jsonc`): ~2.5k HEALPix-1024 points, every hour of a year.  A
#: climate-dt *polygon* request has its date and time axes unmerged and both compressed, so all
#: 8,760 hourly fields share **one** spatial sub-tree
CDT_YEAR_POLYGON = {
    "type": "polygon",
    "shape": [
        [0.014869101089765205, 42.93374856181829],
        [3.3855298642355875, 42.93374856181829],
        [3.3855298642355875, 40.465083525508696],
        [0.014869101089765205, 40.465083525508696],
        [0.014869101089765205, 42.93374856181829],
    ],
}
#: whole-world and whole-domain single fields: the largest requests a deployment serves
WHOLE_WORLD_HEALPIX = {**CDT, "date": "20200101", "time": "0000", "param": "167", "feature": GLOBAL_BBOX}
EFAS_WHOLE_DOMAIN = {**EFAS, "step": "6", "param": "240023", "feature": bbox([[72.24, -25.24], [22.76, 50.24]])}


#: the same rectangle as a bounding box: a box keeps climate-dt's merged date/time axis, which puts
#: every hour in its own branch -- 8,760 spatial sub-trees of one field each, the shape that pays most
#: for the fold's arrays
CDT_YEAR_BBOX = bbox([[42.93374856181829, 0.014869101089765205], [40.465083525508696, 3.3855298642355875]])


def dates_from(n_days: int) -> list:
    """``n_days`` consecutive dates from 2020-01-01, as the fake's axis values."""
    return [(datetime.date(2020, 1, 1) + datetime.timedelta(days=n)).strftime("%Y%m%d") for n in range(n_days)]


def cdt_hourly(feature, n_days: int) -> dict:
    """The hourly climate-dt request over ``n_days`` days (24 fields each)."""
    dates = dates_from(n_days)
    return {
        **CDT,
        "date": f"{dates[0]}/to/{dates[-1]}",
        "time": "/".join(f"{h:02d}00" for h in range(24)),
        "param": "167",
        "feature": feature,
    }


def dated_axes(grid: str, n_days: int) -> list:
    """The fake's axis table with ``n_days`` dates on every sub-cube that has a date axis."""
    from polytope_mars.testing import default_axes

    axes = default_axes(grid)
    for cube in axes:
        if "date" in cube:
            cube["date"] = dates_from(n_days)
    return axes


#: days of the hourly climate-dt scenarios below.  A whole year (8,760 branches) does not fit this
#: machine: *slicing* 8,760 branches of a box peaks over 5 GB (~220 B/point, the slicer's own cost,
#: nothing to do with the fold), so the shape is measured over 30 days (720 branches) and scales
#: linearly in the branch count.
HOURLY_DAYS = 30

#: (grid, request, days of dates for the fake) -- what a prepared tree costs resident
TREE_SCENARIOS = {
    "tree_healpix1024_europe_24h": ("healpix_1024", HEALPIX_EUROPE_24H, None),
    "tree_cdt_hourly_polygon": ("healpix_1024", cdt_hourly(CDT_YEAR_POLYGON, HOURLY_DAYS), HOURLY_DAYS),
    "tree_cdt_hourly_bbox": ("healpix_1024", cdt_hourly(CDT_YEAR_BBOX, HOURLY_DAYS), HOURLY_DAYS),
}


def tensogram(request: dict) -> dict:
    """``request`` served as tensogram instead of CovJSON (``polytope_mars.encoders.tensogram``)."""
    return {**request, "format": "tensogram"}


STREAM_SCENARIOS = {
    "stream_healpix1024_europe_24fields_1_5GiB": ("stream", "healpix_1024", HEALPIX_EUROPE_24H, 3 * 1024**3 // 2),
    # the two largest single fields of the corpus, each whole in one call at the deployed budget
    "stream_healpix1024_whole_world_1_5GiB": ("stream", "healpix_1024", WHOLE_WORLD_HEALPIX, 3 * 1024**3 // 2),
    "stream_efas_whole_domain_1_5GiB": ("stream", "efas_local_regular", EFAS_WHOLE_DOMAIN, 3 * 1024**3 // 2),
    "stream_efas_danube_40steps_1GiB": ("stream", "efas_local_regular", DANUBE_40_STEPS, 1024**3),
    "stream_efas_danube_10steps_budget200MB": ("stream", "efas_local_regular", DANUBE_10_STEPS, 200_000_000),
    "stream_efas_danube_10steps_budget20MB": ("stream", "efas_local_regular", DANUBE_10_STEPS, 20_000_000),
    "stream_efas_danube_10steps_nobudget": ("stream", "efas_local_regular", DANUBE_10_STEPS, None),
    # the same two requests as tensogram, to compare the peak with the CovJSON runs above
    "stream_healpix1024_europe_24fields_tensogram_1_5GiB": (
        "stream",
        "healpix_1024",
        tensogram(HEALPIX_EUROPE_24H),
        3 * 1024**3 // 2,
    ),
    "stream_efas_danube_10steps_tensogram_budget200MB": (
        "stream",
        "efas_local_regular",
        tensogram(DANUBE_10_STEPS),
        200_000_000,
    ),
}


def rss():
    import psutil

    gc.collect()
    return psutil.Process().memory_info().rss


def peak_rss():
    """Peak RSS of this process (``VmHWM``; ``ru_maxrss`` as a fallback).

    ``ru_maxrss`` of a child starts at the RSS its parent had when it forked (a pytest parent can be
    at 1 GB), so prefer ``VmHWM``, which :func:`reset_peak_rss` can reset.
    """
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmHWM:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024


def reset_peak_rss():
    """Reset ``VmHWM`` to the current RSS (Linux >= 4.0); no-op where unsupported."""
    try:
        with open("/proc/self/clear_refs", "w") as f:
            f.write("5")
    except OSError:
        pass


def tree_stats(tree):
    """(spatial nodes, spatial points, result values) of a polytope request tree.

    A prepared tree holds one array-backed bulk node per spatial sub-tree; a sliced one holds a latitude
    node per grid row, each with its longitude leaves.
    """
    from polytope_feature.datacube.tensor_index_tree import (
        BulkMergedTensorIndexNode,
        MergedTensorIndexNode,
    )

    n_spatial = n_pts = n_vals = 0
    stack = [tree]
    while stack:
        node = stack.pop()
        if isinstance(node, BulkMergedTensorIndexNode):
            n_spatial += 1
            n_pts += node.point_count
            n_vals += sum(len(values) for values in node.result)
            continue
        if isinstance(node, MergedTensorIndexNode):
            n_spatial += 1
            n_pts += 1
            n_vals += len(node.result)
            continue
        if node.axis.name == "latitude":
            n_spatial += 1
        if not node.children:
            n_pts += len(node.values)
            n_vals += len(node.result)
        stack.extend(node.children)
    return n_spatial, n_pts, n_vals


def _array_bytes(obj, seen: set) -> int:
    """Bytes ``obj`` owns: a numpy array's buffer (counted once per base), a container's items."""
    import numpy as np

    if isinstance(obj, np.ndarray):
        base = obj.base if obj.base is not None else obj
        if id(base) in seen:
            return 0  # a view (eg. a bulk grid node's lon_values) or an array already counted
        seen.add(id(base))
        nbytes: int = getattr(base, "nbytes", 0)
        return nbytes
    if isinstance(obj, (list, tuple, set, frozenset)):
        return sys.getsizeof(obj) + sum(_array_bytes(item, seen) for item in obj)
    if obj is None:
        return 0
    return sys.getsizeof(obj)


def tree_bytes(tree) -> int:
    """Bytes the tree itself holds: every node's shell and dict plus the arrays it owns.

    An estimate (``sys.getsizeof`` for the Python objects, ``nbytes`` for the arrays, views counted
    once), to be read next to the measured RSS: it says *where* a tree's memory is.
    """
    seen: set = set()
    total = 0
    stack = [tree]
    while stack:
        node = stack.pop()
        if id(node) in seen:
            continue
        seen.add(id(node))
        total += sys.getsizeof(node) + sys.getsizeof(getattr(node, "__dict__", {}))
        for name in ("values", "indexes", "coordinates", "lat_values", "tag_ids", "tag_sets", "result"):
            total += _array_bytes(getattr(node, name, None), seen)
        children = getattr(node, "children", ())
        total += sys.getsizeof(children)
        stack.extend(children)
    return total


def datacube_of(api) -> Any:
    """``api.datacube`` as an ``FDBDatacube`` (``Polytope`` types it as an optional union)."""
    datacube = api.datacube
    if datacube is None or not hasattr(datacube, "prepare"):
        raise SystemExit(f"expected an FDBDatacube, got {type(datacube).__name__}")
    return datacube


def _prepare(grid, request, axes=None):
    """``(fake, api, preq)``: everything ``PolytopeMars`` does up to (not including) the slice.

    The ``Polytope`` is built exactly as :meth:`BlockExtractor._slice` builds it (merged union rows), so
    a measurement taken here is a measurement of the production path.
    """
    from polytope_feature.polytope import Polytope, Request

    from polytope_mars.api import PolytopeMars, features
    from polytope_mars.config import PolytopeMarsConfig
    from polytope_mars.testing import fake_gribjump_config_dict, make_fake_gribjump

    request = copy.deepcopy(request)
    fake = make_fake_gribjump(grid, axes=dated_axes(grid, axes) if isinstance(axes, int) else axes)
    pm = PolytopeMars(fake_gribjump_config_dict(grid, request), datacube_factory=lambda: fake)
    conf = cast(PolytopeMarsConfig, pm.conf)
    feature_config = request.pop("feature")
    feature_type = feature_config["type"]
    feature = features[feature_type](dict(feature_config), conf)
    request = feature.parse(request, dict(feature_config))
    shapes = pm._create_base_shapes(request, feature_type) + feature.get_shapes()
    preq = Request(*shapes)
    options = conf.options.model_dump()
    api = Polytope(datacube=fake, options=options)
    api._merge_union_rows = True
    # Polytope.retrieve minus the nearest-point bookkeeping (no Point shapes here) and the get.
    datacube_of(api).check_branching_axes(preq)
    api.switch_polytope_dim(preq)
    return fake, api, preq


def run_slice_or_get(kind, grid, request):
    fake, api, preq = _prepare(grid, request)
    rss0 = rss()
    t0 = time.perf_counter()
    tree = api.slice(api.datacube, preq.polytopes())
    t_slice = time.perf_counter() - t0
    rss1 = rss()
    n_spatial, n_pts, _ = tree_stats(tree)
    out = {
        "slice_s": round(t_slice, 2),
        "rss_before_mib": round(rss0 / MiB, 1),
        "rss_after_slice_mib": round(rss1 / MiB, 1),
        "spatial_nodes": n_spatial,
        "tree_points": n_pts,
        "slice_bytes_per_point": round((rss1 - rss0) / max(n_pts, 1), 1),
    }
    if kind == "get":
        t0 = time.perf_counter()
        datacube_of(api).get(tree)
        t_get = time.perf_counter() - t0
        rss2 = rss()
        _, _, n_vals = tree_stats(tree)
        out.update(
            {
                "get_s": round(t_get, 2),
                "rss_after_get_mib": round(rss2 / MiB, 1),
                "values": n_vals,
                "fields": fake.n_requests,
                "get_bytes_per_value": round((rss2 - rss1) / max(n_vals, 1), 1),
            }
        )
    out["peak_rss_mib"] = round(peak_rss() / MiB, 1)
    return out


def run_e2e(grid, request):
    from polytope_mars.api import PolytopeMars
    from polytope_mars.testing import fake_gribjump_config_dict, make_fake_gribjump

    fake = make_fake_gribjump(grid)
    pm = PolytopeMars(fake_gribjump_config_dict(grid, request), datacube_factory=lambda: fake)
    rss0 = rss()
    peak0 = peak_rss()
    t0 = time.perf_counter()
    coverage = pm.extract(copy.deepcopy(request))
    t_extract = time.perf_counter() - t0
    peak_extract = peak_rss()
    t0 = time.perf_counter()
    artefact = json.dumps(coverage).encode("utf-8")
    t_dumps = time.perf_counter() - t0
    peak = peak_rss()
    n_vals = fake.n_values
    return {
        "values": n_vals,
        "fields": fake.n_requests,
        "n_coverages": pm.timings["n_coverages"],
        "output_mib": round(len(artefact) / MiB, 1),
        "output_bytes_per_value": round(len(artefact) / max(n_vals, 1), 1),
        "extract_s": round(t_extract, 1),
        "dumps_s": round(t_dumps, 1),
        "timings_ms": {k: round(v) for k, v in pm.timings.items() if k.endswith("_ms")},
        "rss_before_mib": round(rss0 / MiB, 1),
        "peak_rss_mib": round(peak / MiB, 1),
        "peak_after_extract_mib": round(peak_extract / MiB, 1),
        "peak0_mib": round(peak0 / MiB, 1),
        "peak_bytes_per_value": round((peak - rss0) / max(n_vals, 1), 1),
    }


def run_stream(grid, request, budget):
    from polytope_mars.api import PolytopeMars
    from polytope_mars.testing import fake_gribjump_config_dict, make_fake_gribjump

    fake = make_fake_gribjump(grid)
    config = fake_gribjump_config_dict(grid, request)
    config["limits"] = {"memory_budget_bytes": budget}
    pm = PolytopeMars(config, datacube_factory=lambda: fake)
    rss0 = rss()
    reset_peak_rss()
    peak0 = peak_rss()
    t0 = time.perf_counter()
    n_bytes = n_chunks = 0
    max_chunk = 0
    for chunk in pm.extract_stream(copy.deepcopy(request)):
        n_bytes += len(chunk)
        n_chunks += 1
        max_chunk = max(max_chunk, len(chunk))
    t_stream = time.perf_counter() - t0
    peak = peak_rss()
    n_vals = fake.n_values
    return {
        "format": request.get("format", "covjson"),
        "budget_mb": None if budget is None else round(budget / 1e6),
        "values": n_vals,
        "n_groups": pm.timings["n_groups"],
        "n_units": pm.timings["n_units"],
        "groups_per_unit_max": pm.timings["groups_per_unit_max"],
        "n_spatial_subtrees": pm.timings["n_spatial_subtrees"],
        "estimated_unit_mb": round(pm.timings["estimated_unit_bytes_max"] / 1e6, 1),
        "n_ranges": pm.timings["n_ranges"],
        "fields_per_unit_max": pm.timings["fields_per_unit_max"],
        "max_rss_mb": round(pm.timings["max_rss_bytes"] / 1e6, 1),
        "output_mib": round(n_bytes / MiB, 1),
        "chunks": n_chunks,
        "max_chunk_mib": round(max_chunk / MiB, 2),
        "stream_s": round(t_stream, 1),
        "timings_ms": {k: round(v) for k, v in pm.timings.items() if k.endswith("_ms")},
        "rss_before_mib": round(rss0 / MiB, 1),
        "peak0_mib": round(peak0 / MiB, 1),
        "peak_rss_mib": round(peak / MiB, 1),
        "rss_growth_mb": round((peak - rss0) / 1e6, 1),
        "peak_bytes_per_value": round((peak - rss0) / max(n_vals, 1), 1),
    }


def run_ranges(grid, request):
    """Points and gribjump index ranges of one field, and what they cost in gribjump's buffer.

    No extraction: the counts come from the prepared tree's bulk spatial nodes exactly as the planner
    reads them (``polytope_mars.bulk_tree``), and the bytes from ``polytope_mars.sizing``.
    """
    from polytope_mars.bulk_tree import RangeCounts
    from polytope_mars.coverage_plan import analyse_tree
    from polytope_mars.extract import spatial_counts, spatial_nodes
    from polytope_mars.sizing import UnitSizing

    fake, api, preq = _prepare(grid, request)
    rss0 = rss()
    t0 = time.perf_counter()
    tree = api.slice(api.datacube, preq.polytopes())
    t_slice = time.perf_counter() - t0
    t0 = time.perf_counter()
    tree = datacube_of(api).prepare(tree)
    t_prepare = time.perf_counter() - t0
    rss_prepared = rss()

    info = analyse_tree(tree)
    counter = RangeCounts()
    t0 = time.perf_counter()
    nodes = spatial_nodes(info, [0])
    counts = spatial_counts(info, [0])
    range_counts = [counter.of(node) for node in nodes]
    t_count = time.perf_counter() - t0
    points, ranges = sum(counts), sum(range_counts)

    sizing = UnitSizing()
    values_bytes = 8 * points
    mask_bytes = points // 8
    range_bytes = sizing.bytes_per_range * ranges
    return {
        "subtrees": len(counts),
        "points": points,
        "ranges": ranges,
        "points_per_range": round(points / max(ranges, 1), 2),
        "gribjump_mb": round((values_bytes + mask_bytes + range_bytes) / 1e6, 1),
        "gribjump_b_per_value": round((values_bytes + mask_bytes + range_bytes) / max(points, 1), 1),
        "range_term_mb": round(range_bytes / 1e6, 1),
        "python_mb": round(sizing.bytes_per_value * points / 1e6, 1),
        "prepared_tree_mb": round(tree_bytes(tree) / 1e6, 1),
        "slice_s": round(t_slice, 1),
        "prepare_s": round(t_prepare, 1),
        "count_s": round(t_count, 1),
        "rss_before_mib": round(rss0 / MiB, 1),
        "rss_prepared_mib": round(rss_prepared / MiB, 1),
        "peak_rss_mib": round(peak_rss() / MiB, 1),
    }


def run_tree(grid, request, axes=None):
    """What a prepared request tree costs resident.

    A bulk node holds ``coordinates`` (16 B/point) and ``indexes`` (8 B/point) of its sub-tree for the
    whole request: on a request with thousands of sub-trees that is what the tree guard prices, and this
    is where it is measured.  RSS is the number that counts; ``tree_mb`` says where it sits (see
    :func:`tree_bytes`).
    """
    fake, api, preq = _prepare(grid, request, axes=axes)
    gc.collect()
    rss0 = rss()
    reset_peak_rss()
    t0 = time.perf_counter()
    tree = api.slice(api.datacube, preq.polytopes())
    t_slice = time.perf_counter() - t0
    gc.collect()
    rss_sliced = rss()
    sliced_mb = tree_bytes(tree) / 1e6
    t0 = time.perf_counter()
    tree = datacube_of(api).prepare(tree)
    t_prepare = time.perf_counter() - t0
    gc.collect()
    rss_prepared = rss()
    n_spatial, n_pts, _ = tree_stats(tree)
    prepared_mb = tree_bytes(tree) / 1e6
    metrics = getattr(api.datacube, "prototype_metrics", {}) or {}
    return {
        "subtrees": n_spatial,
        "points": n_pts,
        "ranges_per_field": metrics.get("ranges_per_field"),
        "slice_s": round(t_slice, 1),
        "prepare_s": round(t_prepare, 1),
        "sliced_tree_mb": round(sliced_mb, 1),
        "tree_mb": round(prepared_mb, 1),
        "tree_b_per_point": round(prepared_mb * 1e6 / max(n_pts, 1), 1),
        "rss_before_mib": round(rss0 / MiB, 1),
        "rss_sliced_mib": round(rss_sliced / MiB, 1),
        "rss_prepared_mib": round(rss_prepared / MiB, 1),
        "prepare_growth_mb": round((rss_prepared - rss_sliced) / 1e6, 1),
        "prepare_growth_b_per_point": round((rss_prepared - rss_sliced) / max(n_pts, 1), 1),
        "peak_rss_mib": round(peak_rss() / MiB, 1),
    }


def run_calibrate(name, n_fields):
    """Peak RSS growth of one unit of ``n_fields`` fields of one shape, consumed field by field.

    The budget and the caps are set out of the way so that the whole request is one unit (one
    gribjump call, all fields) on the production path (``per_field_consumption``), and the peak is
    measured from the moment the tree is sliced and prepared: what is left is what the call itself
    costs, i.e. gribjump's buffer plus the Python terms the sizing has to cover.

    ``cpp_mb`` is the exact gribjump term of that call (no safety factor) and ``residual_mb`` what
    the Python terms (``bytes_per_point_call`` x points + ``bytes_per_value`` x one group's values
    + the encoder's fragments) must account for.  Re-run after polytope-feature changes how
    requests are built or results consumed, and after covjsonkit changes its fragment size.
    """
    from polytope_mars.api import PolytopeMars
    from polytope_mars.extract import BlockExtractor
    from polytope_mars.sizing import UnitSizing
    from polytope_mars.testing import fake_gribjump_config_dict, make_fake_gribjump

    shape = CALIBRATE_SHAPES[name]
    grid = shape["grid"]
    request = calibrate_request(shape, n_fields)
    if request is None:
        raise SystemExit(f"{name}: the fake's axes cannot express {n_fields} fields")
    fake = make_fake_gribjump(grid)
    config = fake_gribjump_config_dict(grid, request)
    config["limits"] = {
        "memory_budget_bytes": 10**12,
        "max_values_per_unit": None,
        "max_fields_per_call": 4096,
        "per_field_consumption": True,
    }
    pm = PolytopeMars(config, datacube_factory=lambda: fake)

    # The peak is measured from after the tree is prepared, so that slicing and preparing (which do
    # not scale with the number of fields) are not counted in the unit's own cost.  The budget above
    # keeps the request to one whole-tree prepare.
    marks = {}
    original = BlockExtractor._prepare

    def spy(self, datacube, tree, **kwargs):
        prepared = original(self, datacube, tree, **kwargs)
        marks["rss"] = rss()
        reset_peak_rss()
        marks["peak0"] = peak_rss()
        return prepared

    BlockExtractor._prepare = spy
    try:
        t0 = time.perf_counter()
        n_bytes = max_chunk = 0
        for chunk in pm.extract_stream(copy.deepcopy(request)):
            n_bytes += len(chunk)
            max_chunk = max(max_chunk, len(chunk))
        t_stream = time.perf_counter() - t0
    finally:
        BlockExtractor._prepare = original
    peak = peak_rss()
    n_vals = fake.n_values
    points = n_vals // max(n_fields, 1)
    growth = peak - marks["rss"]
    group_fields = min(shape["group_fields"], n_fields)
    sizing = UnitSizing(safety_factor=1.0)
    cpp = sizing.buffer_bytes(n_fields, points, pm.timings["n_ranges"])
    # how often this call pays the request side: once, or once per group (groups in own branches)
    branches = n_fields // group_fields if pm.timings["request_side"] == "per_group" else 1
    return {
        "shape": name,
        "fields": n_fields,
        "group_fields": group_fields,
        "points": points,
        "values": n_vals,
        "group_values": group_fields * points,
        "branches": branches,
        "request_side": pm.timings["request_side"],
        "n_ranges": pm.timings["n_ranges"],
        "n_units": pm.timings["n_units"],
        "unit_source": pm.timings["unit_source"],
        "estimated_unit_mb": round(pm.timings["estimated_unit_bytes_max"] / 1e6, 1),
        "output_mib": round(n_bytes / MiB, 1),
        "max_chunk_mib": round(max_chunk / MiB, 2),
        "max_chunk_b_per_point": round(max_chunk / max(points, 1), 1),
        "stream_s": round(t_stream, 1),
        "rss_after_prepare_mib": round(marks["rss"] / MiB, 1),
        "peak_rss_mib": round(peak / MiB, 1),
        "growth_mb": round(growth / 1e6, 1),
        "cpp_mb": round(cpp / 1e6, 1),
        "residual_mb": round((growth - cpp) / 1e6, 1),
        "max_rss_mb": round(pm.timings["max_rss_bytes"] / 1e6, 1),
    }


class _Planned(Exception):
    """Raised by the planner spy of :func:`run_targets` once the units are known."""


def _group_specs_of(grid, request):
    """``(specs, group_fields)`` of a request: what the extractor plans its units from.

    The real planning path (slice, prepare, plan, count ranges), stopped before the first
    ``datacube.get``: the numbers below are the ones a worker would use.
    """
    from polytope_mars.api import PolytopeMars
    from polytope_mars.extract import BlockExtractor
    from polytope_mars.testing import fake_gribjump_config_dict, make_fake_gribjump

    fake = make_fake_gribjump(grid)
    config = fake_gribjump_config_dict(grid, request)
    config["limits"] = {"memory_budget_bytes": 3 * 1024**3 // 2}
    pm = PolytopeMars(config, datacube_factory=lambda: fake)
    captured = {}
    original = BlockExtractor._multipoint_blocks

    def spy(self, datacube, tree, info, plan, groups, specs, sizing):
        captured["specs"] = specs
        captured["subtrees"] = self.counters.n_spatial_subtrees
        raise _Planned

    BlockExtractor._multipoint_blocks = spy
    try:
        for _ in pm.extract_stream(copy.deepcopy(request)):
            pass
    except _Planned:
        pass
    finally:
        BlockExtractor._multipoint_blocks = original
    specs = captured.get("specs")
    if not specs:
        raise SystemExit("the planner was never reached")
    return specs, captured


def run_targets(name):
    """What the planner does with one request at several budgets: fields per call and call count.

    No data is fetched: the request is sliced, prepared and planned, and the units are replanned
    for each budget with the deployed defaults (:class:`polytope_mars.sizing.UnitSizing`).
    """
    import dataclasses

    from polytope_mars.config import PolytopeMarsConfig
    from polytope_mars.sizing import UnitSizing
    from polytope_mars.tree_units import plan_units

    grid, request, budgets = TARGET_SCENARIOS[name]
    t0 = time.perf_counter()
    specs, captured = _group_specs_of(grid, request)
    t_plan = time.perf_counter() - t0
    first = specs[0]
    plans = {}
    for budget in budgets:
        conf = PolytopeMarsConfig.model_validate({"limits": {"memory_budget_bytes": budget}})
        sizing = UnitSizing.from_limits(conf.limits, per_field_consumption=True)
        sized = [
            dataclasses.replace(
                s,
                max_groups=sizing.max_unit_groups(
                    s.n_points, s.n_fields, s.n_ranges, n_subtrees=s.n_subtrees, own_branch=s.own_branch
                ),
            )
            for s in specs
        ]
        units = plan_units(sized)
        groups_max = max(length for _, length in units)
        fields_max = groups_max * first.n_fields
        estimate = sizing.estimate_bytes(
            fields_max,
            first.n_points,
            first.n_ranges,
            group_fields=first.n_fields,
            n_branches=first.n_subtrees * (groups_max if first.own_branch else 1),
        )
        plans[f"{budget / 1024 ** 3:.2f}GiB"] = {
            "groups_per_call": groups_max,
            "fields_per_call": fields_max,
            "calls": len(units),
            "estimated_unit_mb": round(estimate / 1e6, 1),
        }
    return {
        "groups": len(specs),
        "points": first.n_points,
        "ranges": first.n_ranges,
        "fields_per_group": first.n_fields,
        "fields": len(specs) * first.n_fields,
        "subtrees_per_group": first.n_subtrees,
        "subtrees": captured["subtrees"],
        "plan_s": round(t_plan, 1),
        "request_side": "per_group" if first.own_branch else "per_call",
        "plans": plans,
        "peak_rss_mib": round(peak_rss() / MiB, 1),
    }


def run_one(name, budget: object = "default"):
    if name in RANGE_SCENARIOS:
        grid, request = RANGE_SCENARIOS[name]
        return run_ranges(grid, request)
    if name in TREE_SCENARIOS:
        return run_tree(*TREE_SCENARIOS[name])
    if name in TARGET_SCENARIOS:
        return run_targets(name)
    if name in CALIBRATE_SCENARIOS:
        return run_calibrate(*CALIBRATE_SCENARIOS[name])
    if name in STREAM_SCENARIOS:
        kind, grid, request, default_budget = STREAM_SCENARIOS[name]
        return run_stream(grid, request, default_budget if budget == "default" else budget)
    kind, grid, request = SCENARIOS[name]
    if kind == "e2e":
        return run_e2e(grid, request)
    return run_slice_or_get(kind, grid, request)


TABLE_COLUMNS = {
    "slice": [
        "spatial_nodes",
        "tree_points",
        "slice_s",
        "rss_before_mib",
        "rss_after_slice_mib",
        "slice_bytes_per_point",
        "peak_rss_mib",
    ],
    "get": [
        "tree_points",
        "fields",
        "values",
        "slice_bytes_per_point",
        "get_s",
        "rss_after_slice_mib",
        "rss_after_get_mib",
        "get_bytes_per_value",
    ],
    "e2e": [
        "values",
        "n_coverages",
        "extract_s",
        "dumps_s",
        "output_mib",
        "output_bytes_per_value",
        "rss_before_mib",
        "peak_rss_mib",
        "peak_bytes_per_value",
        "timings_ms",
    ],
    "stream": [
        "format",
        "budget_mb",
        "values",
        "n_groups",
        "n_units",
        "groups_per_unit_max",
        "fields_per_unit_max",
        "n_spatial_subtrees",
        "estimated_unit_mb",
        "n_ranges",
        "output_mib",
        "max_chunk_mib",
        "stream_s",
        "rss_before_mib",
        "peak_rss_mib",
        "rss_growth_mb",
        "max_rss_mb",
        "peak_bytes_per_value",
        "timings_ms",
    ],
    "ranges": [
        "subtrees",
        "points",
        "ranges",
        "points_per_range",
        "gribjump_mb",
        "gribjump_b_per_value",
        "range_term_mb",
        "python_mb",
        "prepared_tree_mb",
        "slice_s",
        "prepare_s",
        "count_s",
        "peak_rss_mib",
    ],
    "tree": [
        "subtrees",
        "points",
        "ranges_per_field",
        "slice_s",
        "prepare_s",
        "sliced_tree_mb",
        "tree_mb",
        "tree_b_per_point",
        "rss_sliced_mib",
        "rss_prepared_mib",
        "prepare_growth_mb",
        "prepare_growth_b_per_point",
        "peak_rss_mib",
    ],
    "calibrate": [
        "fields",
        "group_fields",
        "points",
        "values",
        "n_ranges",
        "unit_source",
        "estimated_unit_mb",
        "max_chunk_mib",
        "stream_s",
        "rss_after_prepare_mib",
        "peak_rss_mib",
        "growth_mb",
        "cpp_mb",
        "residual_mb",
    ],
    "targets": [
        "groups",
        "fields",
        "points",
        "ranges",
        "fields_per_group",
        "subtrees_per_group",
        "request_side",
        "plan_s",
        "plans",
    ],
}


def _fit_calibration(rows) -> str:
    """Least squares of ``peak growth - the exact gribjump term`` over the Python-side terms.

    Model: ``residual = bytes_per_point_call x points + bytes_per_value x group_values +
    fragment_bytes``, with ``fragment_bytes`` fixed at the encoder's (2 x 8 MiB), so the fit has
    the two unknowns the config has.  Also reports, per row, what the measured growth demands of
    each constant when the other one is at its default -- the defaults must cover the worst row.
    """
    import numpy as np

    from polytope_mars.config import PolytopeMarsConfig
    from polytope_mars.sizing import DEFAULT_FRAGMENT_BYTES, UnitSizing

    usable = [r for _, r in rows if "residual_mb" in r]
    if not usable:
        return ""
    # The request side is paid once per branch of the call (MEASUREMENTS.md), so that is the column
    # of the design matrix, not the points of the call.
    points = np.array([r["points"] * r.get("branches", 1) for r in usable], dtype=float)
    group_values = np.array([r["group_values"] for r in usable], dtype=float)
    residual = np.array([r["residual_mb"] * 1e6 - DEFAULT_FRAGMENT_BYTES for r in usable], dtype=float)
    design = np.stack([points, group_values], axis=1)
    (bpc, bpv), *_ = np.linalg.lstsq(design, residual, rcond=None)

    limits = PolytopeMarsConfig().limits
    default = UnitSizing.from_limits(limits, per_field_consumption=True)
    lines = [
        f"Least squares over {len(usable)} runs (residual = growth - exact gribjump term - 16 MiB of"
        f" fragments): bytes_per_point_call = {bpc:.1f}, bytes_per_value = {bpv:.1f}",
        "",
        "| run | request points | group values | residual MB | needs B/point_call | needs B/value |"
        " estimate MB | covered |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for (name, _), r in zip([row for row in rows if "residual_mb" in row[1]], usable):
        request_points = r["points"] * r.get("branches", 1)
        rest_value = default.bytes_per_value * r["group_values"] + DEFAULT_FRAGMENT_BYTES
        rest_point = default.bytes_per_point_call * request_points + DEFAULT_FRAGMENT_BYTES
        need_point = (r["residual_mb"] * 1e6 - rest_value) / max(request_points, 1)
        need_value = (r["residual_mb"] * 1e6 - rest_point) / max(r["group_values"], 1)
        estimate = default.estimate_bytes(
            r["fields"],
            r["points"],
            r["n_ranges"],
            group_fields=r["group_fields"],
            n_branches=r.get("branches", 1),
        )
        lines.append(
            f"| {name} | {request_points:,} | {r['group_values']:,} | {r['residual_mb']} |"
            f" {need_point:.1f} | {need_value:.1f} | {estimate / 1e6:.1f} |"
            f" {'yes' if estimate >= r['growth_mb'] * 1e6 else 'NO'} |"
        )
    return "\n".join(lines)


def _parse_result(proc):
    """The JSON line a ``--run`` subprocess printed last, or an ``error`` entry."""
    # The JSON line is what counts: the child may still die in native teardown after printing it.
    lines = proc.stdout.strip().splitlines()
    try:
        return json.loads(lines[-1])
    except (IndexError, json.JSONDecodeError):
        return {"error": [f"exit {proc.returncode}"] + proc.stderr.strip().splitlines()[-1:]}


def _table(rows, cols):
    lines = ["| scenario | " + " | ".join(cols) + " |", "| --- |" + " ---: |" * len(cols)]
    for name, res in rows:
        lines.append(f"| {name} | " + " | ".join(str(res.get(c, "")) for c in cols) + " |")
    return "\n".join(lines)


def main(argv):
    if argv[:1] == ["--run"]:
        budget: object = "default"
        if "--budget" in argv:
            value = argv[argv.index("--budget") + 1]
            try:
                budget = None if value == "none" else int(value)
            except ValueError:
                raise SystemExit(f"--budget takes a byte count or 'none', got {value!r}") from None
        print(json.dumps(run_one(argv[1], budget)), flush=True)
        # Skip interpreter teardown: the pygribjump/eckit libraries can segfault at exit.
        os._exit(0)
    groups = argv or ["slice", "get", "e2e", "stream"]
    kinds = {name: spec[0] for name, spec in {**SCENARIOS, **STREAM_SCENARIOS}.items()}
    kinds.update({name: "ranges" for name in RANGE_SCENARIOS})
    kinds.update({name: "tree" for name in TREE_SCENARIOS})
    kinds.update({name: "calibrate" for name in CALIBRATE_SCENARIOS})
    kinds.update({name: "targets" for name in TARGET_SCENARIOS})
    results = {}
    for name, kind in kinds.items():
        if kind not in groups:
            continue
        t0 = time.perf_counter()
        proc = subprocess.run(
            [sys.executable, __file__, "--run", name], capture_output=True, text=True, env=dict(os.environ)
        )
        results[name] = _parse_result(proc)
        results[name]["wall_s"] = round(time.perf_counter() - t0, 1)
        print(f"{name}: {results[name]}", file=sys.stderr, flush=True)
    order = ("slice", "get", "e2e", "stream", "ranges", "tree", "calibrate", "targets")
    by_kind = {k: [(n, results[n]) for n in results if kinds[n] == k] for k in order}
    for kind, rows in by_kind.items():
        if not rows:
            continue
        print(_table(rows, TABLE_COLUMNS[kind]) + "\n")
        if kind == "calibrate":
            print(_fit_calibration(rows) + "\n")


if __name__ == "__main__":
    main(sys.argv[1:])
