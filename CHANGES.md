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

# Phase 2: block IR, extraction loop, encoder registry

## Behaviour changes

- **Streaming API.** `PolytopeMars.extract_stream(request) -> Iterator[bytes]` yields the encoded document in
  pieces. The request is parsed/validated when `extract_stream` is called (errors raise before any byte); the
  first piece (the collection opening) is produced before the datacube is created and sliced. `extract(request)`
  is kept and returns `json.loads(b"".join(extract_stream(request)))`; `json.dumps(extract(r)).encode()` equals
  the streamed bytes for every golden case (`tests/golden`, both modes). After `extract_stream`,
  `pm.content_type` / `pm.file_extension` name the encoder's output.
- **`format`** (top-level request key) selects the encoder through `polytope_mars.encoders.get_encoder`;
  default `covjson`; any other value raises `ValueError("Unsupported output format 'x'; supported formats:
  covjson")` before any datacube work.
- **Extraction units** (DESIGN §2.3). The tree is sliced once and `FDBDatacube.prepare`d. Per MultiPoint field
  group (= one coverage) one `datacube.get(tree, select=<group>)` with param/levelist compressed when
  `n_points x n_params x n_levels x bytes_per_point <= limits.memory_budget_bytes` (always when the budget is
  `None`), otherwise per (param, level) in latitude bands of `budget // (bytes_per_point x (n_fields + 1))`
  points (at least one latitude line / merged point per band). **Call pattern change:** legacy made one
  gribjump `extract` call per request; now it is one per field group (budget `None`) or per (field, band).
  Point features (timeseries, position, vertical profile, trajectory) still make one call for the whole
  request.
- **Band-0 peek / missing fields** (DESIGN §2.5): the first band of every field is fetched before the group is
  emitted; a param whose fields gribjump does not have is left out of the coverage, a group without any data
  emits no coverage, bitmap-missing points are `null`. A present param with one missing level gets `null`s for
  that level.
- **Polygons and paths** are sliced with `Polytope._merge_union_rows = True` (one longitude leaf per latitude
  line, ~8 B/point instead of ~1.4 KB/point); bytes unchanged (tested for every polygon golden case).
- **`param_db` lives in polytope-mars** (`polytope_mars.param_db`, `polytope_mars/data/{ecmwf,dwd}`); nothing is
  imported from `covjsonkit.param_db` any more.
- **Config.** `encoders: {covjson: {param_db: ecmwf}}` replaces `coverageconfig` and
  `limits: {max_polygon_points: 3600, max_points_per_field: None, memory_budget_bytes: None,
  bytes_per_point: {default: 64, local_regular: 64, octahedral: 64, healpix_nested: 160}}` replaces
  `polygonrules`. Deprecated keys are still accepted: `coverageconfig.param_db` fills `encoders.covjson` and
  `polygonrules.max_points` fills `limits.max_polygon_points` unless the new sections set them;
  `polygonrules.max_area` is ignored. Default polygon vertex limit: 1000 -> 3600 (the deployed value).
- **Removed:** `Feature.split_request`, the date/number split loop of `extract`, `merge_coverage_collections`,
  `PolytopeMars.retrieve_data`, the `max_area` checks of circle/position/timeseries (a circle larger than
  `max_area` no longer raises). `limits.max_points_per_field` (off by default) rejects, before slicing, requests
  whose feature area x grid density (`polytope_mars.limits`) exceeds it.
- **`timings`** (reset per request): `first_byte_ms`, `datacube_init_ms`, `slice_ms`, `prepare_ms`, `get_ms`,
  `retrieve_ms` (= slice + prepare + get), `encode_ms`, `n_groups`, `n_units` (datacube gets), `n_bands`,
  `n_gribjump_calls`, `n_coverages`.
- **Logging:** one DEBUG line per group, one INFO summary per request. (polytope-feature still logs two INFO
  lines per `datacube.get`, i.e. per band; that is outside this repo.)
- `features.frame.Frame` implements `required_keys`/`required_axes`: frame requests work (defect 5).

## Legacy defects fixed (golden cases with `fixes:`, bytes in `tests/golden/expected_fixed/`)

| defect | case | change against the oracle |
| --- | --- | --- |
| 1 `NaN` | `efas_bbox_nan_points`, `o1280_bbox_nan_points` | bare `NaN` tokens become `null`; nothing else changes |
| 2 missing last date | `o1280_bbox_missing_last_date` | `"coverages": []` becomes one coverage (20240101, 8 points, all values); 20240102 (all missing) has no coverage |
| 3 missing param | `o1280_bbox_missing_field` | the 20240102 step-6 coverage loses its all-`null` `tp` range; the other 3 coverages are unchanged |
| 3 + 4 | `cdt_bbox_missing_field` | the 1200 coverage has only `2t` (21 correct values) instead of 36-value `10u`/`2t` ranges with shifted/`null` values |
| 5 frame | `efas_frame_fc` | was `TypeError`; now one coverage with 360 points (outer box minus inner box) |
| 6 climate-dt position | `cdt_position` | was `TypeError`; now one PointSeries coverage per (point, date-time), `t` = that date-time, as `Position.from_polytope` does for grids with steps |

`tools/audit_golden.py` finds no misplaced value in any case. Every case without `fixes:` is byte-identical to
the oracle (`tests/golden/expected/`, now tracked in git; regenerate only from the Phase 0 code, see
`tests/golden/README.md`).

## Preserved legacy quirks (candidates for a later spec-compliance release)

- 7: space-separated datetimes (`"2020-01-01 00:00:00Z"`) in `t` and `Forecast date` on the `_step` path
  (climate-dt / ng polygon and timeseries); the timeseries `Forecast date` is the request's last date.
- 8: `referencing` coordinates per legacy encoder: `latitude/longitude/levelist` (bbox, circle, reforecast,
  timeseries, position, vertical profile), `x/y/z` (polygon, shapefile, frame, `_step`, clmn except circle,
  position on clmn), `t/x/y/z` for trajectories with the step as the composite tuple's first element.
- 9: int `realization` (and other type-changed axes) in `mars:metadata` while other keys are strings;
  unrounded Lambert-conformal coordinates; no `Forecast date` on efcl coverages; raw levelist values in
  composite tuples (`"500"` on climate-dt, ints where levelist has an int type change).
- `mars:metadata` key order and values follow the legacy tree walks (`polytope_mars/legacy_format.py`,
  `coverage_plan.py`), e.g. `Forecast date` sits where the date node is, `number`/`step` are appended when the
  tree has no such axis.

## Deliberate differences outside the corpus

- The collection's `parameters` lists every requested param (request order, sorted as strings like the tree
  sorts them), also params that turn out to be missing everywhere; legacy listed the tree's params
  (`from_polytope*`) or only params with data (reforecast).
- A request where every field is missing yields an empty collection (legacy `from_polytope_reforecast`
  raised `ValueError("No data was returned.")`).
- Reforecast (class=ce) MultiPoint coverages with several levels list composite tuples levels-outer like
  every other MultiPoint coverage (legacy interleaved levels per latitude line). EFAS has no levels.
- Point features: an instant (date/step...) whose params are all missing is left out of the series; a param
  missing at some instants of a series gets `null` there. Position coverages of a multi-level, multi-number
  request are ordered (point, date, number, level) instead of (point, date, level, number).
- Layouts not covered by the corpus (vertical profile / trajectory on clmn or class=ce, 3-D/4-D trajectories,
  position on class=ce) follow the legacy encoders' rules as read from the code, unverified against bytes.

# Phase 2b: missing fields reported as `DataNotFound`

## What the real gribjump does

Checked on the Bologna dev deployment against the remote gribjump (`fdbprod:9123`): gribjump does **not**
return an empty result for a field it does not have. The whole `extract` call raises, through pygribjump,

```
GribJumpException: Error in function 'gribjump_extract': GribJumpException: DataNotFound. Matched 1 fields but 2 were requested.
Union request: retrieve,class=od,date=20261006,...,param=121/167,step=1,...
```

(`Matched 0 fields but 1 were requested.` for a single missing field). polytope-feature's `FDBDatacube.get`
re-raises it unchanged, so the `values == []` handling of Phase 2 never ran in production and one missing
field failed the whole request (as it did in legacy, which made one call per request).

## Behaviour changes

- **Detection** (`polytope_mars.extract.is_data_not_found`): an exception whose class, or one of its bases, is
  named `GribJumpException` (matched by name, pygribjump need not be importable) and whose message contains
  `DataNotFound`. Everything else (grid-hash mismatch, missing JumpInfo, connection errors, a `DataNotFound`
  text in another exception class) propagates and fails the job as before. When the message says
  `Matched 0 fields` (`matched_no_field`), every field of the call is missing and nothing is re-fetched; an
  unreadable message is treated as a partial match.
- **Fallbacks** reproduce the empty-result semantics of DESIGN §2.5 (omit missing params' ranges, no coverage
  for a group without data, `null` for a missing level of a present param):
  - whole-group unit (param/levelist compressed): on a partial match the group is re-fetched per
    (param, level) in one band through the banded path, whose band-0 peek keeps the fields that exist;
  - band 0 of a (param, level) (the peek): `DataNotFound` = the field is missing. A later band of a field
    whose band 0 was found re-raises (the field existed a moment ago). Missing levels of a present param
    are no longer fetched after the peek (both reporting modes; their `null`s are written directly);
  - point features (one `get` for the whole tree): per param, then, for a param that is only partly
    missing, per (group, param), then per level of a multi-level group. Output layout and order of the
    present fields are those of the all-present case.
- **Call-count cost, only when data is missing** (nothing changes when everything is present):
  - MultiPoint group, one param missing: 1 failed call + 1 call per (param, level) instead of 1 call;
    all fields of the group missing, or a one-field group: just the failed call;
  - banded groups: unchanged (the peek already fetched per field); a missing field costs 1 failed call;
  - point features, a param missing everywhere: 1 failed call + 1 call per param; a param missing at some
    instants only: additionally 1 call per group (instant) of that param, plus 1 per level for multi-level
    groups that still fail.
- **`timings`**: `n_missing_fields` (fields found missing, either reporting) and `n_fallbacks` (units re-fetched
  in smaller pieces after `DataNotFound`). `n_units` / `n_gribjump_calls` include the failed calls. One DEBUG
  line per missing field, none at INFO.
- **Fake gribjump**: `FakeGribJump(missing_mode="raise")` is the new default and mirrors the remote server:
  an `extract` call whose (distinct) request paths include a missing field raises
  `pygribjump.GribJumpException` (a stand-in class of the same name when pygribjump cannot be imported) with
  the message above, `Union request:` built from the call's paths (keys sorted, values `/`-joined in first-seen
  order) and counts `n_data_not_found`. `missing_mode="empty"` keeps the Phase 2 behaviour (`.values == []`);
  golden cases may set `fake.missing_mode`, and `build_fake(case, missing_mode=...)` overrides it.

## Verification

Every golden case (including the `*missing*` ones in `expected_fixed/`) is byte-identical under both fake
modes (`tests/golden/test_golden.py::test_golden_with_empty_results_for_missing_fields`; the raising mode is
the default for `test_golden`). `tests/test_missing_fields.py` covers the fallbacks, their call counts, the
later-band re-raise, the propagation of other errors, and point features (timeseries, position, vertical
profile, trajectory, class=ce timeseries) against the empty-result bytes.

# Phase 2c: several field groups per gribjump call

## Why

Measured on the Bologna dev deployment against the remote gribjump (`fdbprod:9123`): one `datacube.get`
costs ~**480 ms** before it reads a value (TCP round trip, request parsing, an FDB catalogue/TOC scan per
single-field request) plus ~1.3 us per value. Legacy made one call per *request* and paid only the
per-field work inside gribjump (~100 ms/field), so the Phase 2 pattern of one call per field group adds
~15-20 minutes and 3000 TOC scans for a 3000-field ensemble (50 members x 60 steps) whose data is a few
seconds. Large single groups are not the problem (one Danube bbox step is already ~40 MB of result);
many small ones are.

## Behaviour changes

- **Extraction units can cover several field groups** (DESIGN §2.3, `polytope_mars.tree_units`). For
  MultiPoint domains a unit is the longest run of *consecutive* groups (plan order) that satisfies all of:

  - it fits the budget: `n_points x n_params x n_levels x k x bytes_per_point <= limits.memory_budget_bytes`,
    i.e. `k = budget // (n_points x n_params x n_levels x bytes_per_point)`;
  - `k <= 1024` (`tree_units.MAX_GROUPS_PER_UNIT`), so one call's request list and the pruned tree stay
    bounded however large the budget is;
  - the groups agree on their point count, params and levels (a run never crosses a change of spatial
    sub-tree shape, of `param` or of `levelist`);
  - the group-axis values of the run are exactly a cartesian product. One `select` leaves the group axes
    (`step`, `number`, `date`, `hdate`, `month`, ...) *compressed*, and compressed axes expand to the
    product of their values, so e.g. 3 numbers x 2 steps with room for 3 groups gives units of 2, not 3.

  `limits.memory_budget_bytes = None` keeps one group per call (unchanged, and still the default). When a
  single group does not fit, that group goes through the per-(param, level) banded path as before.
- **One call per unit.** The unit's sub-tree is pruned from the sliced tree with the group axes carrying
  the unit's values (`tree_units.prune_values`; `TensorIndexTree.prune` only selects one value per axis),
  `param`/`levelist` compressed as in Phase 2. `collect_field_values` splits the leaf results per
  (group, param, level); a group's blocks are emitted only once all of the unit's results are in, groups in
  plan order, each group one band. Output bytes are unchanged for every unit size.
- **Missing fields.** `DataNotFound` on a multi-group unit means some field in it is missing: the unit is
  re-fetched one group at a time (which falls back to per (param, level) for the group that is actually
  missing a field), so present groups keep all their params and a group without any data emits no coverage
  (DESIGN §2.5). `Matched 0 fields` still means every field of the unit is missing and nothing is
  re-fetched. Cost of a 10-group unit with one group missing: 1 failed call + 10 calls (+2 when only one
  param of that group is missing) instead of 10.
- **`timings`**: `groups_per_unit_max` (most groups fetched by one `datacube.get`; 1 without a budget).
  The INFO summary reports it as `<= n groups per unit`.
- Point features (timeseries, position, vertical profile, trajectory) are unchanged: one call for the whole
  request.

## The order the per-(group, param, level) split relies on

`FDBDatacube._gribjump_requests` (`polytope_feature/datacube/backends/fdb.py:237-259`) expands each
branch's compressed axes with `product(*compressed_request[0].values())` over the leaf path's keys, which
`get_fdb_requests` inserts while it descends the tree (root to leaf), and `assign_fdb_output_to_nodes`
appends each request's ranges to the leaf in call order. A leaf's `result` is therefore its points once
per field of the branch, the fields in C-order over the branch's compressed axes in tree order -- what
`collect_field_values` splits by (`np.ndindex` over `Branch.path`). Pinned by
`tests/test_tree_units.py::test_compressed_axes_expand_as_a_product_in_tree_order` on real `FDBDatacube`
output, not assumed.

Two properties of the request trees make this work without a polytope-feature change: a merged `date`/`time`
axis is sliced into one branch per datetime (never compressed), so the `date`/`time` key pair the merger
unmaps never multiplies out; and axes that are compressed (`step`, `number`, `levelist`, `param`, `month`)
unmap to one key each.

## Verification

- `tests/test_streaming.py::test_unit_invariance_over_consecutive_groups`: every MultiPoint golden case with
  budgets forcing 1, 3 and all groups per unit is byte-identical to the corpus, and `fake.n_extract_calls`
  equals the number of units predicted independently from the case's group grid (brute force over the group
  keys), with `groups_per_unit_max` the largest unit.
- `test_unit_runs_stop_at_a_non_rectangular_group_set` (3 numbers x 2 steps, room for 3) and
  `test_multi_group_unit_assigns_every_field_to_its_own_group` (every range of a 4-group unit carries
  exactly its own field, decoded from the fake's values) cover the two rules the split depends on.
- `tests/test_tree_units.py`: the planner (budget, cap, shape changes, product rule, groups without group-axis
  values) and `prune_values` (selected values only, whole branches on the merged date axis, parent tree
  untouched, errors).
- `tests/test_missing_fields.py::test_multi_group_unit_falls_back_per_group` and
  `test_multi_group_unit_fallback_keeps_the_params_that_exist`: a step missing inside a 10-group unit, both
  reporting modes, same bytes as one unit per group.
- EFAS Danube bbox x 10 steps (6.3M values, `tools/measure_memory.py`): with a 200 MB budget 3 units
  (4 + 4 + 2 groups) instead of 10 calls, peak RSS growth 204 MB (163 MB at one group per call), output
  byte count unchanged.

Predicted calls for the requests that motivated this (budget / `bytes_per_point` as deployed):

| request | groups | per group | k | calls (was) |
| --- | --- | --- | --- | --- |
| Switzerland ensemble 18.8k points x 50 numbers x 60 steps, 1 param, 1 GiB, 64 B | 3000 | 1.20 MB | 892 -> 840 (14 numbers x 60 steps) | **4** (3000) |
| EFAS Danube bbox 633k points x 40 steps, 1 param, 1 GiB, 64 B | 40 | 40.5 MB | 26 | **2** (40); 10 with the deployed 200 MB budget |
| climate-dt month box 24.7k points x 744 datetimes, 1 param, 1.5 GiB, 160 B | 744 | 3.95 MB | 407 | **2** (744) |

The Switzerland unit is cut from 892 to 840 groups by the product rule (units must be whole numbers x all
steps); at ~480 ms per call the fixed cost drops from ~24 min to ~2 s.
