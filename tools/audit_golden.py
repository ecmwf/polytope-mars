"""Audit the golden corpus for values delivered to the wrong place by the legacy pipeline.

Every value produced by the fake datacube encodes ``(field_id, grid index)`` (see
``polytope_mars.testing.fake_gribjump``), so for each emitted value we know which MARS
field and which grid point it really came from. Per case this checks:

* ``param``: the source field's param is the range's param;
* ``time``: the source field's datetime matches the coverage ``t`` value at that position
  (PointSeries: one t per value; others: the single t), either as base time
  (date+time / hdate+time / year-month) or as valid time (base + step), and the source step
  equals ``mars:metadata.step`` when present;
* ``align``: all ranges of a coverage carry the same grid indices in the same order, and
  coverages with identical composite coordinates carry identical indices.

Usage: python tools/audit_golden.py [glob]   (default: all cases); add -v for per-range detail.
"""

import glob
import math
import sys
import warnings
from types import SimpleNamespace

import pandas as pd

warnings.filterwarnings("ignore")

from polytope_mars.param_db import get_params  # noqa: E402
from polytope_mars.testing.fake_gribjump import decode_value  # noqa: E402
from polytope_mars.testing.golden import (  # noqa: E402
    build_fake,
    load_case,
    run_case_dict,
)

SHORTNAME = {k: v["shortname"] for k, v in get_params(SimpleNamespace(param_db="ecmwf")).items()}


def _step_delta(step):
    step = str(step)
    if step.isdigit():
        return pd.Timedelta(hours=int(step))
    return pd.Timedelta(step.replace("h", "h ").strip())


def _times(path):
    """(base, valid) datetimes of a source field path."""
    if "month" in path and "year" in path:
        base = pd.Timestamp(year=int(path["year"]), month=int(path["month"]), day=1)
        return base, base
    base = pd.Timestamp(path.get("hdate", path.get("date")))
    if "time" in path:
        base += pd.Timedelta(hours=int(path["time"][:2]), minutes=int(path["time"][2:]))
    valid = base + _step_delta(path["step"]) if "step" in path else base
    return base, valid


def _t(value):
    return pd.Timestamp(value.replace("Z", "").replace(" ", "T"))


def _step_eq(meta_step, path_step):
    return _step_delta(meta_step if not isinstance(meta_step, int) else str(meta_step)) == _step_delta(path_step)


def audit(path, verbose=False):
    name = path.split("/")[-1]
    case = load_case(path)
    if "expect_error" in case:
        return f"{name}: expected error ({case['expect_error']['type']}), skipped"
    fake = build_fake(case)
    cov, _ = run_case_dict(case, fake)
    coverages = cov["coverages"]
    lines = [f"{name}: {len(coverages)} coverages"]
    bad_param = bad_time = bad_step = misaligned = 0
    indices_by_domain = {}
    for ci, c in enumerate(coverages):
        t_values = c["domain"]["axes"].get("t", {}).get("values", [])
        meta = c.get("mars:metadata", {})
        seqs = []
        for pname, rng in c["ranges"].items():
            seq = []
            sources = set()
            for i, v in enumerate(rng["values"]):
                if v is None or (isinstance(v, float) and math.isnan(v)):
                    seq.append(None)
                    continue
                fid, gi = decode_value(v)
                seq.append(gi)
                src = fake.fields.get(fid)
                if src is None or SHORTNAME.get(str(src.get("param"))) != pname:
                    bad_param += 1
                    continue
                sources.add(tuple(sorted(src.items())))
                if t_values:
                    t = _t(t_values[i] if len(t_values) == len(rng["values"]) and len(t_values) > 1 else t_values[0])
                    if t not in _times(src):
                        bad_time += 1
                if "step" in meta and "step" in src and not _step_eq(meta["step"], src["step"]):
                    bad_step += 1
            seqs.append(seq)
            if verbose:
                lines.append(f"  cov{ci} {pname} t={t_values[:2]} meta.step={meta.get('step')} fields={len(sources)}")
        known = [s for s in seqs if any(x is not None for x in s)]
        for s in known[1:]:
            if any(a is not None and b is not None and a != b for a, b in zip(s, known[0])) or len(s) != len(known[0]):
                misaligned += 1
        if known and "composite" in c["domain"]["axes"]:
            key = str(c["domain"]["axes"]["composite"]["values"])
            ref = indices_by_domain.setdefault(key, known[0])
            if any(a is not None and b is not None and a != b for a, b in zip(ref, known[0])):
                misaligned += 1
    lines.append(
        f"  param mismatches: {bad_param}; t mismatches: {bad_time}; step mismatches: {bad_step}; "
        f"misaligned ranges: {misaligned}"
    )
    return "\n".join(lines)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "-v"]
    pattern = args[0] if args else "*"
    for f in sorted(glob.glob(f"tests/golden/cases/{pattern}.yaml")):
        print(audit(f, verbose="-v" in sys.argv))
