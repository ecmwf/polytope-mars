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
  fe-worker's buffered path; with the Phase 0 code this measured the legacy pipeline).
* ``stream``: peak RSS growth of ``PolytopeMars.extract_stream`` with the output discarded, for
  several ``limits.memory_budget_bytes``.  ``--budget N`` (bytes, or ``none``) overrides the budget.
"""

import copy
import gc
import json
import os
import resource
import subprocess
import sys
import time
import warnings

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

DANUBE_10_STEPS = {**EFAS, "step": "6/to/60/by/6", "param": "240023", "feature": bbox([[50.25, 8.15], [42.08, 29.73]])}
# -- stream: extract_stream, output discarded; (kind, grid, request, memory_budget_bytes)
STREAM_SCENARIOS = {
    "stream_efas_danube_10steps_budget200MB": ("stream", "efas_local_regular", DANUBE_10_STEPS, 200_000_000),
    "stream_efas_danube_10steps_budget20MB": ("stream", "efas_local_regular", DANUBE_10_STEPS, 20_000_000),
    "stream_efas_danube_10steps_nobudget": ("stream", "efas_local_regular", DANUBE_10_STEPS, None),
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
    """(latitude nodes, spatial points, leaf values) of a polytope request tree."""
    from polytope_feature.datacube.tensor_index_tree import MergedTensorIndexNode

    n_lat = n_pts = n_vals = 0
    stack = [tree]
    while stack:
        node = stack.pop()
        if isinstance(node, MergedTensorIndexNode):
            n_pts += 1
            n_vals += len(node.result)
            continue
        if node.axis.name == "latitude":
            n_lat += 1
        if not node.children:
            n_pts += len(node.values)
            n_vals += len(node.result)
        stack.extend(node.children)
    return n_lat, n_pts, n_vals


def _prepare(grid, request):
    from polytope_feature.polytope import Polytope, Request

    from polytope_mars.api import PolytopeMars, features
    from polytope_mars.testing import fake_gribjump_config_dict, make_fake_gribjump

    request = copy.deepcopy(request)
    fake = make_fake_gribjump(grid)
    pm = PolytopeMars(fake_gribjump_config_dict(grid, request), datacube_factory=lambda: fake)
    feature_config = request.pop("feature")
    feature_type = feature_config["type"]
    feature = features[feature_type](dict(feature_config), pm.conf)
    request = feature.parse(request, dict(feature_config))
    shapes = pm._create_base_shapes(request, feature_type) + feature.get_shapes()
    preq = Request(*shapes)
    api = Polytope(datacube=fake, options=pm.conf.options.model_dump())
    # Polytope.retrieve minus the nearest-point bookkeeping (no Point shapes here) and the get.
    api.datacube.check_branching_axes(preq)
    api.switch_polytope_dim(preq)
    return fake, api, preq


def run_slice_or_get(kind, grid, request):
    fake, api, preq = _prepare(grid, request)
    rss0 = rss()
    t0 = time.perf_counter()
    tree = api.slice(api.datacube, preq.polytopes())
    t_slice = time.perf_counter() - t0
    rss1 = rss()
    n_lat, n_pts, _ = tree_stats(tree)
    out = {
        "slice_s": round(t_slice, 2),
        "rss_before_mib": round(rss0 / MiB, 1),
        "rss_after_slice_mib": round(rss1 / MiB, 1),
        "lat_nodes": n_lat,
        "tree_points": n_pts,
        "slice_bytes_per_point": round((rss1 - rss0) / max(n_pts, 1), 1),
    }
    if kind == "get":
        t0 = time.perf_counter()
        api.datacube.get(tree)
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
        "budget_mb": None if budget is None else round(budget / 1e6),
        "values": n_vals,
        "n_groups": pm.timings["n_groups"],
        "n_units": pm.timings["n_units"],
        "groups_per_unit_max": pm.timings["groups_per_unit_max"],
        "n_bands": pm.timings["n_bands"],
        "output_mib": round(n_bytes / MiB, 1),
        "chunks": n_chunks,
        "max_chunk_mib": round(max_chunk / MiB, 1),
        "stream_s": round(t_stream, 1),
        "timings_ms": {k: round(v) for k, v in pm.timings.items() if k.endswith("_ms")},
        "rss_before_mib": round(rss0 / MiB, 1),
        "peak0_mib": round(peak0 / MiB, 1),
        "peak_rss_mib": round(peak / MiB, 1),
        "rss_growth_mb": round((peak - rss0) / 1e6, 1),
        "peak_bytes_per_value": round((peak - rss0) / max(n_vals, 1), 1),
    }


def run_one(name, budget="default"):
    if name in STREAM_SCENARIOS:
        kind, grid, request, default_budget = STREAM_SCENARIOS[name]
        return run_stream(grid, request, default_budget if budget == "default" else budget)
    kind, grid, request = SCENARIOS[name]
    if kind == "e2e":
        return run_e2e(grid, request)
    return run_slice_or_get(kind, grid, request)


TABLE_COLUMNS = {
    "slice": [
        "lat_nodes",
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
        "budget_mb",
        "values",
        "n_groups",
        "n_units",
        "groups_per_unit_max",
        "n_bands",
        "output_mib",
        "max_chunk_mib",
        "stream_s",
        "rss_before_mib",
        "peak_rss_mib",
        "rss_growth_mb",
        "peak_bytes_per_value",
        "timings_ms",
    ],
}


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
        budget = "default"
        if "--budget" in argv:
            value = argv[argv.index("--budget") + 1]
            budget = None if value == "none" else int(value)
        print(json.dumps(run_one(argv[1], budget)), flush=True)
        # Skip interpreter teardown: the pygribjump/eckit libraries can segfault at exit.
        os._exit(0)
    groups = argv or ["slice", "get", "e2e", "stream"]
    kinds = {name: spec[0] for name, spec in {**SCENARIOS, **STREAM_SCENARIOS}.items()}
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
    by_kind = {k: [(n, results[n]) for n in results if kinds[n] == k] for k in ("slice", "get", "e2e", "stream")}
    for kind, rows in by_kind.items():
        if rows:
            print(_table(rows, TABLE_COLUMNS[kind]) + "\n")


if __name__ == "__main__":
    main(sys.argv[1:])
