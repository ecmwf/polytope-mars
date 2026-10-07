"""Golden-corpus case runner: one case = (grid config, fake datacube options, request) -> CovJSON bytes.

A case file (YAML or JSON) has the keys:

``grid``
    one of :data:`polytope_mars.testing.configs.GRIDS`.
``request``
    the MARS + ``feature`` request as the fe-worker hands it to ``PolytopeMars.extract``.
``fake`` (optional)
    ``axes``: full axis table override (dict or list of sub-cubes);
    ``axes_update``: ``{axis: [values]}`` applied to every default sub-cube that has that axis;
    ``missing``: list of partial MARS paths whose fields are missing;
    ``nan_indices``: absolute grid indices that are NaN in every field;
    ``nan_every``: ``n`` -> every grid index divisible by ``n`` is NaN in every field.
``description`` (optional)
    free text.

The produced bytes are exactly what the fe-worker ships:
``json.dumps(PolytopeMars(config).extract(request)).encode("utf-8")``.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np

from .configs import default_axes, fake_gribjump_config_dict
from .fake_gribjump import FakeGribJump

__all__ = ["build_fake", "load_case", "run_case", "run_case_dict"]


def load_case(path) -> dict:
    path = Path(path)
    text = path.read_text()
    if path.suffix in (".yaml", ".yml"):
        import yaml

        return yaml.safe_load(text)
    return json.loads(text)


def build_fake(case: dict) -> FakeGribJump:
    grid = case["grid"]
    fake_opts = case.get("fake") or {}
    axes = copy.deepcopy(fake_opts["axes"]) if "axes" in fake_opts else default_axes(grid)
    cubes = [axes] if isinstance(axes, dict) else axes
    for axis, values in (fake_opts.get("axes_update") or {}).items():
        for cube in cubes:
            if axis in cube:
                cube[axis] = [str(v) for v in values]
    if "nan_indices" in fake_opts:
        nan = fake_opts["nan_indices"]
    elif "nan_every" in fake_opts:
        nan = _nan_every(fake_opts["nan_every"])
    else:
        nan = None
    return FakeGribJump(cubes, missing=fake_opts.get("missing"), nan_indices=nan)


def _nan_every(every):
    every = int(every)

    def is_nan(path, idx):
        return np.asarray(idx) % every == 0

    return is_nan


def run_case_dict(case: dict, fake: FakeGribJump | None = None):
    """Run a case through the legacy ``PolytopeMars.extract``; returns ``(coverage_dict, PolytopeMars)``."""
    from ..api import PolytopeMars

    fake = build_fake(case) if fake is None else fake
    request = copy.deepcopy(case["request"])
    config = fake_gribjump_config_dict(case["grid"], request)
    pm = PolytopeMars(config, datacube_factory=lambda: fake)
    return pm.extract(request), pm


def run_case(case: dict, fake: FakeGribJump | None = None) -> bytes:
    """The fe-worker artefact for ``case``."""
    coverage, _ = run_case_dict(case, fake)
    return json.dumps(coverage).encode("utf-8")
