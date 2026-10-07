# Changes on `feat/streaming-encoders`

Per-branch note for the PR description. Phase 0 changes no CovJSON output: the golden corpus
(`tests/golden/`) pins today's bytes, including the defects listed below.

## Behaviour changes

- `PolytopeMars.__init__` takes an optional `datacube_factory` (zero-argument callable returning the
  gribjump handle). Default is `pygribjump.GribJump()`, still looked up at call time, so monkeypatching
  `polytope_mars.api.gj.GribJump` keeps working.
- `PolytopeMars.timings` (reset by every `extract`): `datacube_init_ms`, `retrieve_ms` = `slice_ms` +
  `get_ms` (the get is timed by wrapping the datacube's `get` for the duration of `Polytope.retrieve`),
  `encode_ms`, `n_coverages`. Values accumulate over the sub-requests of a split request.
- The `print(result.pprint())` after retrieval is gone (`pprint` logs at DEBUG and returned `None`, so it
  only ever printed `None` to stdout).
- New package `polytope_mars.testing` (fake gribjump, deployment configs, golden-case runner). Not used at
  runtime.

## Legacy behaviour captured by the corpus that looks wrong (not changed in Phase 0)

Oracle: polytope-python 2.1.20 + covjsonkit 0.2.26 (the fe-worker pins). "Case" = `tests/golden/cases/<name>.yaml`.

1. **`NaN` in the output.** Bitmap-missing points come back from gribjump as NaN and `json.dumps` writes
   the bare token `NaN`, which is not JSON (`efas_bbox_nan_points`, `o1280_bbox_nan_points`). DESIGN §2.6(a)
   fixes this to `null`.
2. **A missing last date wipes the whole collection.** When every field of the last date is missing,
   `walk_tree`'s all-`None` branch (`fields["dates"] = fields["dates"][:-1]` plus the `range_dict`
   deletion loop) runs once per latitude leaf, removing earlier dates and deleting their ranges. Result:
   `"coverages": []` although 20240101 has data (`o1280_bbox_missing_last_date`). The same request with
   the *first* date missing happens to come out right.
3. **Missing-field policy depends on the encoder.** `from_polytope` (bbox etc.) keeps the coverage and
   writes the missing param's range as all `null` (`o1280_bbox_missing_field`, 228 at step 6 of
   20240102). `from_polytope_reforecast` (class=ce) drops the missing param's range from that coverage
   (`efas_bbox_missing_field`). DESIGN §2.5 makes "omit the range" the rule.
4. **Missing field on grids whose leaves span several index ranges (HEALPix nested) corrupts
   neighbouring values.** `FDBDatacube.assign_fdb_output_to_nodes` appends `len(leaf)` `None`s once per
   *range* of the leaf, so the leaf result is too long: the 1200 coverage of `cdt_bbox_missing_field` has
   36 values for 21 points in each range, and 17 of the 2t (present) values are `null`/shifted.
   `tools/audit_golden.py` flags it as misaligned. See also "Changed by the polytope-feature branch".
5. **`frame` cannot be requested.** `features.frame.Frame` does not implement the abstract
   `required_keys`/`required_axes`, so `extract` raises `TypeError: Can't instantiate abstract class Frame`
   (`efas_frame_fc`, recorded as `expect_error`). The existing `tests/test_frame.py` tests are skipped.
6. **`position` on climate-dt raises.** `Position.from_polytope` assumes a `step` axis
   (`len(fields["step"])` on the int default) and climate-dt has none: `TypeError: object of type 'int' has
   no len()` (`cdt_position`, `expect_error`).
7. **Non-ISO datetimes from the step/timeseries walkers.** `from_polytope_step` (climate-dt polygon and
   timeseries) writes `t` values and `Forecast date` as `"2020-01-01 00:00:00Z"` (space, not `T`); the
   other paths write `"2020-01-01T00:00:00Z"`. For a timeseries spanning two dates, `Forecast date` is the
   *last* date (`cdt_timeseries`).
8. **Inconsistent `referencing` coordinates.** bbox/position/reforecast use
   `["latitude", "longitude", "levelist"]`, polygon/timeseries via `from_polytope_step` and all clmn
   coverages use `["x", "y", "z"]`, trajectory uses `["t", "x", "y", "z"]` with the step in the
   composite tuple.
9. Smaller oddities kept as bytes: climate-dt `realization` comes out as an int in `mars:metadata`
   (`1`) while other keys are strings; Lambert-conformal coordinates are not rounded (17 significant
   digits) while the other mappers' are; efcl coverages have no `Forecast date` (intended upstream).

Note for the fake: the leaf value layout follows the order of the axes in polytope's request tree, which
follows the key order of `gribjump.axes()`. gribjump returns them from a `std::map`, i.e. sorted; the
legacy walkers silently assume that order (param above step/time). With unsorted axes the fake reproduced
scrambled param/time assignments, which is why `FakeGribJump.axes` sorts its keys.

## Changed by the polytope-feature branch

Checked against `../polytope` at `3ba4d49d` ("Fill one None per point for missing fields whose leaf spans
several index ranges") plus that checkout's uncommitted changes, via the shared editable `.venv`:

- `cdt_bbox_missing_field`: the 1200 coverage now has 21 values per range, `10u` all `null` and `2t`
  intact (fixes item 4). All other 26 cases are byte-identical to the oracle.
