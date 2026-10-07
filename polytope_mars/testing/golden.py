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
    ``nan_every``: ``n`` -> every grid index divisible by ``n`` is NaN in every field;
    ``missing_mode``: ``raise`` (default, like the remote gribjump) or ``empty`` (see ``FakeGribJump``).
``description`` (optional)
    free text.
``fixes`` (optional)
    numbers of the legacy defects (polytope-mars CHANGES.md) this branch fixes for the case; its expected
    bytes are then ``expected_fixed/<case>.covjson`` instead of the oracle ``expected/<case>.covjson``.
``expect_error`` (optional)
    ``{type, match}``: extraction raises (``legacy_error`` records what the oracle raised for fixed cases).

:func:`run_case` gives exactly what the fe-worker ships,
``json.dumps(PolytopeMars(config).extract(request)).encode("utf-8")``; :func:`run_case_stream` gives
``b"".join(PolytopeMars(config).extract_stream(request))``.  The two must be equal.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np

from .configs import default_axes, fake_gribjump_config_dict
from .fake_gribjump import FakeGribJump

__all__ = ["build_fake", "load_case", "make_polytope_mars", "run_case", "run_case_dict", "run_case_stream"]


def load_case(path) -> dict:
    path = Path(path)
    text = path.read_text()
    if path.suffix in (".yaml", ".yml"):
        import yaml

        return yaml.safe_load(text)
    return json.loads(text)


def build_fake(case: dict, missing_mode: str | None = None) -> FakeGribJump:
    """The fake datacube of ``case``; ``missing_mode`` overrides the case's ``fake.missing_mode``."""
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
    return FakeGribJump(
        cubes,
        missing=fake_opts.get("missing"),
        nan_indices=nan,
        missing_mode=missing_mode or fake_opts.get("missing_mode", "raise"),
    )


def _nan_every(every):
    every = int(every)

    def is_nan(path, idx):
        return np.asarray(idx) % every == 0

    return is_nan


def make_polytope_mars(case: dict, fake: FakeGribJump | None = None, config_update: dict | None = None):
    """``(PolytopeMars, request)`` for ``case`` over ``fake`` (default: :func:`build_fake`).

    ``config_update`` is merged into the top level of the config dict (e.g. ``{"limits": {...}}``).
    """
    from ..api import PolytopeMars

    fake = build_fake(case) if fake is None else fake
    request = copy.deepcopy(case["request"])
    config = fake_gribjump_config_dict(case["grid"], request)
    config.update(copy.deepcopy(config_update or {}))
    return PolytopeMars(config, datacube_factory=lambda: fake), request


def run_case_dict(case: dict, fake: FakeGribJump | None = None, config_update: dict | None = None):
    """Run a case through ``PolytopeMars.extract``; returns ``(coverage_dict, PolytopeMars)``."""
    pm, request = make_polytope_mars(case, fake, config_update)
    return pm.extract(request), pm


def run_case_stream(case: dict, fake: FakeGribJump | None = None, config_update: dict | None = None) -> bytes:
    """``b"".join(PolytopeMars.extract_stream(request))`` for ``case``."""
    pm, request = make_polytope_mars(case, fake, config_update)
    return b"".join(pm.extract_stream(request))


def run_case(case: dict, fake: FakeGribJump | None = None, config_update: dict | None = None) -> bytes:
    """The fe-worker artefact for ``case``."""
    coverage, _ = run_case_dict(case, fake, config_update)
    return json.dumps(coverage).encode("utf-8")
