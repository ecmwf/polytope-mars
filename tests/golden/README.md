# Golden CovJSON corpus

`expected/<case>.covjson` holds the exact bytes the fe-worker ships for `cases/<case>.yaml`:
`json.dumps(PolytopeMars(config).extract(request)).encode("utf-8")`, run against the fake gribjump in
`polytope_mars.testing` (no FDB needed).

## Oracle

The expected bytes were generated with the versions the deployed fe-worker pins
(`polytope-server/workers/polytope-fe-worker/requirements.txt`):

- polytope-python **2.1.20** (package `polytope_feature`, from PyPI, not the sibling checkout)
- covjsonkit **0.2.26** (from PyPI)
- pygribjump[binary] 0.12.0.26, pyfdb 5.22.0.26, eccodes 2.47.0
- polytope-mars from this branch (only test helpers, timings and the `datacube_factory` hook differ from `main`)

To regenerate or verify against the oracle, use a pristine environment, not one with editable installs
of branches under development:

```sh
uv venv .venv-legacy --python 3.11
uv pip install --python .venv-legacy/bin/python polytope-python==2.1.20 covjsonkit==0.2.26 \
    "pygribjump[binary]==0.12.0.26" pyfdb==5.22.0.26 eccodes==2.47.0 pytest psutil -e ./polytope-mars
.venv-legacy/bin/python -m pytest polytope-mars/tests/golden -q                  # verify
.venv-legacy/bin/python -m pytest polytope-mars/tests/golden -q --golden-regen   # rewrite (or GOLDEN_REGEN=1)
```

A deliberate change to the bytes must be regenerated with the new code and listed in the branch's `CHANGES.md`.

## Case files

```yaml
description: free text
grid: efas_local_regular | healpix_1024 | octahedral_1280 | on_demand_extremes_dt
request: {...}            # MARS keys + feature, as the fe-worker passes it to extract()
fake:                     # optional, see polytope_mars/testing/golden.py
  missing: [{param: "228", step: "6"}]   # partial paths whose fields gribjump reports as missing
  nan_every: 3                            # grid indices divisible by 3 are NaN (bitmap-missing)
  nan_indices: [...]                      # or explicit grid indices
  axes / axes_update: ...                 # override the default axis table
expect_error:             # optional: legacy raises instead of producing bytes (no expected file)
  type: TypeError
  match: "substring of the message"
```

The per-request config is built like the fe-worker builds it (`fake_gribjump_config_dict`): the
deployed `options` block of the grid, `pre_path` = single-valued pre-path keys of the request, and the
LUMI `separate_datetime` date/time split for climate-dt timeseries/polygon.

## Checking values, not just bytes

Every value the fake returns is `field_id(path) * 1e5 + 1e-3 * grid_index`, so
`python tools/audit_golden.py` can check that each emitted value sits under the right param, time and
step, and that all ranges of a coverage carry the same grid points. Under the oracle every case is clean
except `cdt_bbox_missing_field` (see CHANGES.md).
