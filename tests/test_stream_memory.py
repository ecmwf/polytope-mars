"""Peak RSS of streaming a large EFAS request (Danube bbox x 10 steps, 6.3M values) stays near the budget.

Each run is a fresh subprocess of ``tools/measure_memory.py`` (own peak RSS).  Takes ~10 s per run.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[1] / "tools" / "measure_memory.py"
SCENARIO = "stream_efas_danube_10steps_budget200MB"


def measure(budget, tree_bytes=None) -> dict:
    """The measurement's JSON line, or ``{"error": [...]}`` when the run refused the request."""
    arg = "none" if budget is None else str(budget)
    extra = [] if tree_bytes is None else ["--tree-bytes", str(tree_bytes)]
    proc = subprocess.run(
        [sys.executable, str(TOOL), "--run", SCENARIO, "--budget", arg] + extra,
        capture_output=True,
        text=True,
        env=dict(os.environ),
        timeout=900,
    )
    lines = proc.stdout.strip().splitlines()
    if not lines:
        return {"error": list(proc.stderr.strip().splitlines()[-5:])}
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        pytest.fail(f"measurement did not print a JSON line ({exc}): {lines[-1]!r}\n{proc.stderr[-2000:]}")


@pytest.mark.parametrize("budget", [200_000_000, 100_000_000])
def test_rss_growth_stays_below_twice_the_budget(budget):
    res = measure(budget)
    assert res["values"] >= 5_000_000
    assert res["n_groups"] == 10
    # the peak baseline must be this process's, not the forking parent's
    assert res["peak0_mib"] < res["rss_before_mib"] + 50, json.dumps(res)
    # growth includes the sliced and prepared tree (~45 MB) and slicing transients
    assert res["rss_growth_mb"] * 1e6 < 2 * max(budget, 100_000_000), json.dumps(res)
    assert res["max_chunk_mib"] < 64


def test_unbudgeted_run_produces_the_same_output_size():
    budgeted = measure(100_000_000)
    legacy_mode = measure(None)
    assert legacy_mode["n_units"] == legacy_mode["n_groups"] == 10
    assert budgeted["n_units"] <= legacy_mode["n_units"]
    assert budgeted["output_mib"] == legacy_mode["output_mib"]


def test_a_budget_smaller_than_one_field_refuses_the_request():
    """A field is fetched whole: 40 MB cannot serve a 634,550-point field (45 MB), and nothing is split.

    ``max_tree_bytes`` is set explicitly because the tree guard comes first and would answer at this
    budget: the request's tree is 15 MB measured, 25 MB estimated, against half of 40 MB.
    """
    res = measure(40_000_000, tree_bytes=30_000_000)
    assert "error" in res, json.dumps(res)
    assert any("One field of this request covers 634550 grid points" in line for line in res["error"]), res


def test_a_budget_too_small_for_the_request_tree_refuses_it_before_slicing():
    """Half of a 20 MB budget cannot hold the tree of a 634,550-point field: refused before slicing."""
    res = measure(20_000_000)
    assert "error" in res, json.dumps(res)
    assert any("The request tree alone would need about 25 MB" in line for line in res["error"]), res
