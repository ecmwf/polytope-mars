# Changes on `feat/streaming-encoders`

This file records what the branch changes, one section per change. The first section changes no
CovJSON output: it adds the golden corpus (`tests/golden/`), which pins the bytes the legacy
pipeline produces, including the defects listed below.

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

## Legacy behaviour captured by the corpus that looks wrong

Oracle: polytope-python 2.1.20 + covjsonkit 0.2.26 (the fe-worker pins). "Case" = `tests/golden/cases/<name>.yaml`.

1. **`NaN` in the output.** Bitmap-missing points come back from gribjump as NaN and `json.dumps` writes
   the bare token `NaN`, which is not JSON (`efas_bbox_nan_points`, `o1280_bbox_nan_points`). The streaming
   pipeline writes `null`.
2. **A missing last date wipes the whole collection.** When every field of the last date is missing,
   `walk_tree`'s all-`None` branch (`fields["dates"] = fields["dates"][:-1]` plus the `range_dict`
   deletion loop) runs once per latitude leaf, removing earlier dates and deleting their ranges. Result:
   `"coverages": []` although 20240101 has data (`o1280_bbox_missing_last_date`). The same request with
   the *first* date missing happens to come out right.
3. **Missing-field policy depends on the encoder.** `from_polytope` (bbox etc.) keeps the coverage and
   writes the missing param's range as all `null` (`o1280_bbox_missing_field`, 228 at step 6 of
   20240102). `from_polytope_reforecast` (class=ce) drops the missing param's range from that coverage
   (`efas_bbox_missing_field`). "Omit the range" is the rule in the streaming pipeline.
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

# Block IR, extraction loop, encoder registry

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
- **Extraction units.** The tree is sliced once and `FDBDatacube.prepare`d. Per MultiPoint field
  group (= one coverage) one `datacube.get(tree, select=<group>)` with param/levelist compressed when
  `n_points x n_params x n_levels x bytes_per_point <= limits.memory_budget_bytes` (always when the budget is
  `None`), otherwise per (param, level) in latitude bands of `budget // (bytes_per_point x (n_fields + 1))`
  points (at least one latitude line / merged point per band). **Call pattern change:** legacy made one
  gribjump `extract` call per request; this pipeline makes one per field group (budget `None`) or per
  (field, band).
  Point features (timeseries, position, vertical profile, trajectory) still make one call for the whole
  request.
- **Band-0 peek / missing fields**: the first band of every field is fetched before the group is
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
- **Logging:** one DEBUG line per group, one INFO summary per request. (polytope-feature logs two INFO
  lines per `datacube.get`; that is outside this repo.)
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
the oracle (`tests/golden/expected/`, tracked in git; regenerate only from the last commit that ran the
legacy encoders, see `tests/golden/README.md`).

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

# Missing fields reported as `DataNotFound`

## What the real gribjump does

Checked on the Bologna dev deployment against the remote gribjump (`fdbprod:9123`): gribjump does **not**
return an empty result for a field it does not have. The whole `extract` call raises, through pygribjump,

```
GribJumpException: Error in function 'gribjump_extract': GribJumpException: DataNotFound. Matched 1 fields but 2 were requested.
Union request: retrieve,class=od,date=20261006,...,param=121/167,step=1,...
```

(`Matched 0 fields but 1 were requested.` for a single missing field). polytope-feature's `FDBDatacube.get`
re-raises it unchanged, so the empty-result handling never ran in production and one missing field
failed the whole request (as it did in legacy, which made one call per request).

## Behaviour changes

- **Detection** (`polytope_mars.extract.is_data_not_found`): an exception whose class, or one of its bases, is
  named `GribJumpException` (matched by name, pygribjump need not be importable) and whose message contains
  `DataNotFound`. Everything else (grid-hash mismatch, missing JumpInfo, connection errors, a `DataNotFound`
  text in another exception class) propagates and fails the job as before. When the message says
  `Matched 0 fields` (`matched_no_field`), every field of the call is missing and nothing is re-fetched; an
  unreadable message is treated as a partial match.
- **Fallbacks** reproduce the empty-result semantics (omit missing params' ranges, no coverage
  for a group without data, `null` for a missing level of a present param):
  - whole-group unit (param/levelist compressed): on a partial match the group is re-fetched per
    (param, level) in one band through the banded path, whose band-0 peek keeps the fields that exist;
  - band 0 of a (param, level) (the peek): `DataNotFound` = the field is missing. A later band of a field
    whose band 0 was found re-raises (the field existed a moment ago). Missing levels of a present param
    are not fetched after the peek (both reporting modes; their `null`s are written directly);
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
  order) and counts `n_data_not_found`. `missing_mode="empty"` returns an empty result instead (`.values == []`);
  golden cases may set `fake.missing_mode`, and `build_fake(case, missing_mode=...)` overrides it.

## Verification

Every golden case (including the `*missing*` ones in `expected_fixed/`) is byte-identical under both fake
modes (`tests/golden/test_golden.py::test_golden_with_empty_results_for_missing_fields`; the raising mode is
the default for `test_golden`). `tests/test_missing_fields.py` covers the fallbacks, their call counts, the
later-band re-raise, the propagation of other errors, and point features (timeseries, position, vertical
profile, trajectory, class=ce timeseries) against the empty-result bytes.

# Several field groups per gribjump call

## Why

Measured on the Bologna dev deployment against the remote gribjump (`fdbprod:9123`): one `datacube.get`
costs ~**480 ms** before it reads a value (TCP round trip, request parsing, an FDB catalogue/TOC scan per
single-field request) plus ~1.3 us per value. Legacy made one call per *request* and paid only the
per-field work inside gribjump (~100 ms/field), so one call per field group adds
~15-20 minutes and 3000 TOC scans for a 3000-field ensemble (50 members x 60 steps) whose data is a few
seconds. Large single groups are not the problem (one Danube bbox step is already ~40 MB of result);
many small ones are.

## Behaviour changes

- **Extraction units can cover several field groups** (`polytope_mars.tree_units`). For
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
  `param`/`levelist` compressed. `collect_field_values` splits the leaf results per
  (group, param, level); a group's blocks are emitted only once all of the unit's results are in, groups in
  plan order, each group one band. Output bytes are unchanged for every unit size.
- **Missing fields.** `DataNotFound` on a multi-group unit means some field in it is missing: the unit is
  re-fetched one group at a time (which falls back to per (param, level) for the group that is actually
  missing a field), so present groups keep all their params and a group without any data emits no coverage
  `Matched 0 fields` still means every field of the unit is missing and nothing is
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

# Sizing a unit from what it actually costs

## Why

`limits.bytes_per_point` sized an extraction unit with one constant per grid mapper family
(64 B/value, 160 for `healpix_nested`).  On the LUMI dev cluster a
480k-point HEALPix-1024 Europe box x 24 hourly fields was therefore batched into units of 19 fields
(`480k x 160 x 19 = 1.46 GB` against a 1.5 GiB budget) and the worker was OOM-killed at 3 GiB; the same
request at one field per call passed.  Two things were missing from the model:

- **gribjump's own buffer.**  The deployed gribjump (0.12.0.26) is not lazy: `RemoteGribJump::extract`
  decodes the whole TCP reply into a vector before returning and pygribjump's iterator is a cursor over
  it, so the C++ side holds every value of the call until the call is over.  An `ExtractionResult` holds
  `std::vector<std::vector<double>> values_` and `std::vector<std::vector<std::bitset<64>>> mask_`, one
  inner vector each **per index range** (`gribjump/src/gribjump/ExtractionData.h`).
- **index ranges.**  gribjump is asked for runs of consecutive grid indices, not for points, and how many
  runs a field needs depends on the grid *and* on the request: an O1280 Europe box needs one range per
  latitude line (222,960 points in 1,080 ranges), a HEALPix-nested box nearly one per point (479,865
  points in 300,315 ranges).  That ratio -- not the grid as such -- is what the per-mapper constant was
  standing in for, and `prepare` already knows it before anything is fetched.

## Behaviour changes

- **Unit sizing** (`polytope_mars.sizing.UnitSizing`, `polytope_mars.grid_ranges`).  A unit of `k` field
  groups is planned when both

  - `buffer_bytes + bytes_per_value x python_values <= limits.memory_budget_bytes`, where
    `buffer_bytes = n_fields x (8 x n_points + n_points/8 + limits.bytes_per_range x n_ranges) x
    limits.safety_factor` is gribjump's own residency and `python_values` the values the Python side
    holds (the whole unit, or one group with per-field consumption, see below).  The two terms are
    added because they are resident at the same time.
  - `n_fields x n_points <= limits.max_values_per_unit`, a hard cap independent of the budget and of the
    estimate.

  `n_points` and `n_ranges` come from the tree: `polytope_mars.grid_ranges` counts the ranges the way
  `FDBDatacube._gribjump_requests` builds them (grid indices through the axis' own `unmap_path_key`, then
  one range per run of consecutive indices, duplicates dropped first-come-first-served), memoised per
  spatial shape so a request walks its spatial sub-tree once.  A single group that does not fit is
  fetched in latitude bands as before, the band sized by the same two terms (and by the group's own
  ranges-per-point ratio, so a HEALPix band is smaller than an octahedral one).
- **`limits`**: `bytes_per_value` (128, one constant for every grid: the measured Python-side cost of a
  value -- results on the tree, the float64 field copies, the encoder's buffers), `bytes_per_range` (96:
  two vector headers plus two heap allocations in the `ExtractionResult`), `safety_factor` (1.5, applied
  to the gribjump term), `max_values_per_unit` (8,000,000), `per_field_consumption` (off, see below).
  **`bytes_per_point` is deprecated**: a config that still sets it has its `default` entry used as
  `bytes_per_value` and the per-mapper entries ignored.  Only `memory_budget_bytes` is injected by the
  chart; `bytes_per_value` and `max_values_per_unit` are worth injecting next to it.
- **Preparing band by band.**  `FDBDatacube.prepare` computes a grid index per point, which on a
  whole-world HEALPix-1024 field is 400 s and a 3.2 GB peak for a tree whose values are 100 MB.  The
  units are therefore planned on the *sliced* tree (point and range counts do not need a prepared one)
  and, as soon as any group has to be fetched in bands, the whole tree is never prepared: each band
  prepares its own pruned copy of one field (`datacube.prepare(tree, select=..., latitude_range=...)`),
  which is where that band's coordinates and point count come from.  Requests whose groups all fit keep
  the single up-front prepare.  `timings["prepare_mode"]` says which happened.

  Bytes are unchanged at every band size: a band is a run of whole latitude nodes of the same tree and
  `prepare` only reorders points inside a leaf and drops duplicate grid indices.  A duplicate can only
  cross a band boundary if two *different* latitude nodes ask for the same index; `grid_ranges` counts
  that case and the extractor falls back to a whole-tree prepare for it.  The overlap case of
  polytope-feature's `tests/test_pruned_get.py` (a box whose longitudes wrap past the full circle)
  duplicates points within each latitude line, so it is identical either way (tested).
- **Per-field consumption** (`limits.per_field_consumption`, **off by default**).  A multi-group unit is
  consumed field by field and each group's blocks are emitted and freed as soon as its (param, level)
  fields have arrived, in plan order (`polytope_mars.field_stream.GroupAssembler`), so the Python side
  holds the incomplete groups only -- one group when the group axes are outermost in the tree, as they
  are for the climate-dt hourly case.  With the flag on and a datacube that has `FDBDatacube.get_iter`
  the fields arrive one at a time and the Python-side term of the sizing covers one group instead of the
  unit; otherwise (the default) one `datacube.get` returns the whole unit through the same consumer.
  `timings["unit_source"]` reports `get` or `get_iter`.  The flag stays off until the polytope-feature
  API is released and `bytes_per_value` is re-calibrated against it.
- **`timings`**: `estimated_unit_bytes_max` (the largest unit estimate the planner produced), `n_ranges`
  (index ranges of one field of the largest group, from the tree), `n_ranges_requested` (ranges gribjump
  was actually asked for, summed over the calls -- the observed counterpart of `n_ranges`),
  `max_rss_bytes` (`getrusage(RUSAGE_SELF).ru_maxrss`), `prepare_mode`, `unit_source`,
  `buffered_fields_max`.  The INFO summary line carries the estimate, the peak RSS, the range count and
  both modes.  **Observation only:** no decision in polytope-mars reads the RSS, a cgroup or any other
  runtime signal; the planner stays a pure function of (request, config, tree).
- **Fake gribjump**: `FakeExtractResult` now mirrors pygribjump 0.12.0.26 -- one contiguous
  `values_flat` buffer per field with `values` as per-range views built only when they are read.
  polytope-feature prefers `values_flat`, so without this the fake charged the extraction ~150 MB of
  per-range numpy objects that production does not pay.

## Verification

- The golden corpus is byte-identical (both modes, both reporting modes for missing fields) and so are
  the unit- and band-invariance suites; `tests/test_streaming.py` now drives "k groups per call" through
  `max_values_per_unit`, which is exact whatever the grid, instead of through a byte budget.
- `tests/test_grid_ranges.py`: the counted ranges equal `timings["n_ranges_requested"]`, i.e. the ranges
  the fake gribjump actually received, for seven cases covering `local_regular`, `octahedral`,
  `healpix_nested`, merged polygon rows and levels, at one unit per group, one unit for everything and
  one latitude node per band.
- `tests/test_unit_sizing.py`: the two terms, and the planned `k` for the measured shapes (the LUMI
  HEALPix box at 1.5 GiB, EFAS Danube at 1 GiB, an O1280 box where the hard cap binds), the cap, the
  whole-world field that is served by bands at any budget, band sizes per grid.
- `tests/test_band_prepare.py`: per-band prepare is byte-identical to a whole-tree prepare on HEALPix,
  O1280 and the wrapping-longitude overlap case, at four band sizes; in the banded mode every `prepare`
  call carries a `select` and a `latitude_range`.
- `tests/test_field_stream.py`: the assembler (release in plan order, one group buffered when the group
  axes are outermost, parts of a key concatenated per branch, flush), the key sequence against
  `collect_field_values`, and `get_iter` end to end -- five golden cases byte-identical with
  `per_field_consumption` on, including missing fields in both reporting modes.
- Measurements and the calibration of `bytes_per_value`: MEASUREMENTS.md (`python tools/measure_memory.py
  ranges calibrate`, re-runnable).

# Per-field consumption by default, and a unit sizing that pays for one call

## Why

Measured on the Bologna dev cluster, the sizing above planned the EFAS Volga 4-param ensemble
(609,851 points x 12,000 fields, 1,131 index ranges per field) into units of **12 fields**, i.e.
~1,000 gribjump calls at ~0.4-0.5 s of fixed cost each, although the exact C++ reply of one field is
only ~5.1 MB. Two terms of the model, not the data, account for that:

- with `limits.per_field_consumption` **off** the Python-side term is charged for every field of
  the call (`bytes_per_value x n_fields x n_points`) even though the extractor already emits and
  frees a group at a time;
- 128 B/value for `bytes_per_value` is a constant calibrated on a *single-field* call, where it
  stands in for the request side (`FDBDatacube` builds one Python `int` per point before fetching
  anything). Paid per value of a 12-field call, that is ~10x what the call actually holds.

fe pods are 3 GiB, so `memory_budget_bytes` is 1.5 GiB and a call batches far more fields. The
1,024-field request-list cap stays until the gribjump team confirms how the union of a call's
requests scales on their side, and is configurable (`limits.max_fields_per_call`).

## Behaviour changes

- **`limits.per_field_consumption` defaults to `true`.** A multi-group unit is fetched through
  `FDBDatacube.get_iter` and consumed field by field, so the Python side holds the groups still
  incomplete (one group when the group axes are outermost) instead of the whole call.
  `timings["unit_source"]` reports `get_iter`; the whole-unit `FDBDatacube.get` stays as the opt-out
  (`per_field_consumption: false`) and is still used for single-group units, for latitude bands and
  for point features. A datacube without `get_iter` falls back to it silently.
- **Unit sizing** (`polytope_mars.sizing.UnitSizing`). A unit of `k` groups is planned when

      buffer_cpp(unit) x safety_factor
        + bytes_per_point_call x n_points
        + bytes_per_value x python_values
        + fragment_bytes  <=  memory_budget_bytes

  with `buffer_cpp(unit) = n_fields x (8 x n_points + n_points/8 + bytes_per_range x n_ranges)` (the
  exact gribjump residency, the only term the safety factor multiplies), `python_values` the
  values the Python side holds at once (**one group** on the per-field path, the whole unit on the
  opt-out), and `fragment_bytes = 2 x` the encoder's `max_fragment_bytes` (2 x 8 MiB for covjsonkit,
  read off the encoder in use). The two hard caps are `max_fields_per_call` and
  `max_values_per_unit`. Without a budget a unit is one field group.
- **`limits`**: `bytes_per_point_call` (**new**, 128: the request-side grid indices, paid once per
  call however many fields it asks for), `bytes_per_value` 128 -> **32** (now only the values held
  at once), `max_values_per_unit` 8,000,000 -> **256,000,000** (~2 GB of gribjump buffer at
  8 B/value: a backstop the budget reaches first), `max_fields_per_call` (**new**, 1024: the
  request-list cap, counted in fields and configurable, in place of the hard-wired
  `tree_units.MAX_GROUPS_PER_UNIT`). `bytes_per_range` (96) and `safety_factor` (1.5) are
  unchanged. Both new constants
  are calibrated in MEASUREMENTS.md.
- **The cap is counted in fields, not groups.** `MAX_GROUPS_PER_UNIT` is gone: a unit may hold up to
  `max_fields_per_call` fields, so a 4-param group counts four times. The deployed value is
  unchanged for single-param requests (1024).
- **Latitude bands** are sized by the same terms (a band is one field of one call plus one band of
  every field of the group, the band-0 peek holding them all, plus the fragments), so lowering
  `bytes_per_value` does not silently make bands larger than the budget.
- **`timings`**: `fields_per_unit_max` (fields one `datacube.get` asked for at most) next to
  `groups_per_unit_max`, and a per-unit `get` histogram -- `units_get_le_1s`, `units_get_le_5s`,
  `units_get_le_30s`, `units_get_gt_30s`, `get_ms_max` -- so Splunk can show where the get time went
  without per-unit DEBUG lines. The INFO summary carries both. `n_units` now also counts a
  `get_iter` pass as one unit (it is one gribjump call).
- **Fake gribjump**: the EFAS axis table has an ensemble sub-cube (`type: pf` with `number` 1-50 and
  the four Volga parameters), so ensemble shapes can be measured and pinned.

## What polytope-config / the chart must set

Only `limits.memory_budget_bytes` (half the pod's memory: **1610612736** for a 3 GiB pod). The new
constants are defaults in code; `max_fields_per_call` is worth injecting next to the budget if the
gribjump team asks for a different request-list size. A config that still sets the deprecated
`limits.bytes_per_point` keeps working (its `default` entry fills `bytes_per_value`), but it should
be removed: at 64 B/value it now *under*-sizes nothing, it only makes units smaller than they could
be.

## Verification

- The golden corpus is byte-identical with per-field consumption on (the new default) and off, in
  both missing-field reporting modes, and so are the unit- and band-invariance suites
  (`tests/test_streaming.py`, 10 MultiPoint cases x {1, 3, all} groups per call).
  `tests/test_field_stream.py` covers the lazy path end to end: five golden cases byte-identical,
  the DataNotFound fallbacks (unit -> per group -> per (param, level)) in both reporting modes, and
  **at most one group's fields alive at a time** -- every array `get_iter` hands over is
  weak-referenced and a ten-group unit never has more than two of them alive while it streams.
- `tests/test_unit_sizing.py`: the four terms, the per-branch request side, the planned fields per
  call for the measured shapes at 1.5 and 1.8 GiB, the raised caps, and bands on a whole-world
  HEALPix field.
- `tests/test_tree_units.py::test_an_efas_ensemble_unit_batches_the_members_of_one_step`: with room
  for two groups a call fetches both members of one step, with room for four the 2 x 2 rectangle --
  the batching the Volga numbers rest on.
- Measured (MEASUREMENTS.md, `python tools/measure_memory.py calibrate targets` and
  `--run stream_healpix1024_europe_24fields_1_5GiB`): 15 calibration runs across four shapes and
  1/4/12/48 fields per call, all below their estimate; the climate-dt HEALPix Europe box x 24 hourly
  fields runs in **2 calls of 14 and 10 fields with a peak RSS of 1.79 GB** at a 1.5 GiB budget
  (target: under 2.2 GB in a 3 GiB pod), output unchanged.
- At a 1.5 GiB budget the planner gives the Volga 4-param ensemble **188 fields per call** (120
  calls for 12,000 fields, the step-major coverage order and the product rule deciding the count)
  and the Switzerland ensemble **1,000 fields per call** (3 calls for 3,000 fields, the per-call
  field cap deciding). At 1.8 GiB: Volga 200 fields per call and **60 calls** (one step per call),
  Switzerland unchanged.

# One bulk node per spatial sub-tree, and every field extracted whole

## Why

Two things bounded a unit on LUMI, both properties of the *per-row* request planning rather than of
the data:

- **index ranges.** gribjump is asked for runs of consecutive grid indices, and a HEALPix-nested box
  breaks into nearly one range per point (479,865 points in 300,315 ranges) because a ring's pixels
  are scattered over the index space. At 96 B per range that was 32.7 MB of C++ buffer per field,
  eight times the values themselves.
- **the request side.** `FDBDatacube` built one Python `int` per point per row and sorted
  `enumerate(...)` of those lists before fetching anything: ~70 B per point *per field* on the
  HEALPix request (every hourly field is its own branch), 1.33 GB of it for a 48-field call.

polytope-feature's `bulk_grid_leaves` (`../polytope/CHANGES.md`) replaces the spatial layers of a
prepared tree with one array-backed node per spatial sub-tree and derives the ranges from one sort of
the whole field's indexes. Both terms collapse, and with them the reason a field was ever cut into
latitude bands.

## Behaviour changes

- **Every request is sliced and prepared with `options["bulk_grid_leaves"] = True`** (set in
  `BlockExtractor._slice`, next to `_merge_union_rows`). The spatial walk is
  :mod:`polytope_mars.bulk_tree`: `node.coordinates` (float64 (N, 2), output order),
  `node.point_count`, `node.indexes`, one `node.result` array per field of the call. Nothing in the
  extraction holds a Python object per point any more, and `polytope_mars.grid_ranges` (which
  re-derived the ranges the way `FDBDatacube` built them) is gone: the count is
  `np.diff(np.sort(node.indexes)) > 1` plus one, exact and cheap.
- **Output bytes are unchanged.** The fold happens in `prepare` in the order the legacy encoders read
  the tree in (rows in tree order, each row's points in grid-index order), which
  `../polytope/performance/bulk_order.py` asserts for all 28 golden cases. The whole corpus is
  byte-identical in both consumption modes and both missing-field reporting modes.
- **Latitude banding is removed.** Gone: `BlockExtractor._banded`, `_prepared_band`, the band-0 peek,
  `_prepare_whole_tree` (the whole tree is always prepared now - it is what folds the nodes and plans
  the ranges), `polytope_mars.grid_ranges`, `UnitSizing.band_points`, `tests/test_band_prepare.py`,
  `tests/test_grid_ranges.py` and the band-invariance parametrisation of `tests/test_streaming.py`.
  `timings` loses `n_bands` and `prepare_mode` and gains `n_spatial_subtrees`.
- **A group that does not fit one call is fetched one (param, level) at a time**, each field whole
  (`_field_units`): gribjump's buffer then holds one field while the Python side still holds the
  group (a coverage lists the params that have data, so all of them are fetched before the first
  block). This is also the DataNotFound fallback of a whole-group unit, and it is what reports a
  missing field: a `DataNotFound` for a call asking for one field says that this field has no
  message. Missing-field detection is therefore unit -> group -> field, with no peek anywhere.
- **A field that does not fit the budget is refused** (`ValueError`, the `max_points_per_field` path):
  `One field of this request covers <n> grid points and needs about <m> MB to extract, more than the
  memory budget of <b> bytes; request a smaller area or fewer parameters per request`. There is no
  splitting of any kind left. `limits.max_points_per_field` remains the explicit, pre-slicing cap.
- **The block IR keeps its band attributes** at their single-band values (`FieldGroup.n_bands = 1`,
  `CoordsBlock`/`ValuesBlock` `band = 0`, `offset = 0`) so that covjsonkit's stream encoder (PR #140,
  which groups by `n_bands` and reads `band`/`offset` structurally) is untouched. They can be dropped
  from the IR and from the encoder together, in one later change on both sides.
- **Unit sizing** (`polytope_mars.sizing.UnitSizing`). A unit of `k` groups is planned when

      buffer_cpp(unit) x safety_factor
        + bytes_per_point_call x n_points x n_subtrees
        + bytes_per_value x live_values
        + fragment_bytes  <=  memory_budget_bytes

  with `buffer_cpp(unit) = n_fields x (8 x n_points + n_points/8 + bytes_per_range x n_ranges)` as
  before, `n_subtrees` the spatial sub-trees the call asks for (`k` of them when every group brings
  its own, one when they share), `live_values` one group's values on the per-field path (the default)
  and the unit's on the opt-out, and `fragment_bytes = 2 x` the encoder's `max_fragment_bytes`.
  `n_ranges` comes from the prepared tree's bulk nodes. `bytes_per_range` stays: the term is exact,
  it is just small now (0.1 MB of 4.0 MB for the HEALPix Europe field).
- **`limits.bytes_per_point_call` 128 -> 32.** It stands for the bulk node's own arrays
  (coordinates 16 B + indexes 8 B per point), which `prepare` builds once and the call's sub-trees
  hold throughout, plus the sort the call's ranges come from, rather than for per-point Python
  objects built per call. Measured per *call* it is ~0 (the arrays are already in the tree when the call starts, and the
  sort is absorbed by the heap the planning just freed), so 32 B/point is a deliberate margin that
  charges a unit for the part of the resident tree it touches. `bytes_per_value` stays 32 (fitted
  21 B/value), `bytes_per_range` 96, `safety_factor` 1.5, `max_values_per_unit` 256M,
  `max_fields_per_call` 1024.
- **`timings`**: `n_spatial_subtrees` (bulk nodes the request walks) is new; `n_units`,
  `n_gribjump_calls`, `fields_per_unit_max`, `groups_per_unit_max`, `estimated_unit_bytes_max`,
  `max_rss_bytes`, the `get_ms` histogram, `n_ranges`, `n_ranges_requested`, `unit_source`,
  `request_side`, `buffered_fields_max`, `n_missing_fields` and `n_fallbacks` are unchanged in
  meaning. The INFO summary drops the band count and the prepare mode and carries the sub-tree count.

## What polytope-config / the chart must set

**Nothing new.** `limits.memory_budget_bytes` (1,610,612,736 for a 3 GiB pod) is still the only value
a deployment has to set; the recalibrated `bytes_per_point_call` is a default in code. A config that
sets the deprecated `limits.bytes_per_point` keeps working. Note for the deployment: the prepared
tree is ~24 B/point *per spatial sub-tree* and is resident for the whole request, outside the
budget the unit model covers - see MEASUREMENTS.md for the two requests where that matters.

## Verification

- The golden corpus is byte-identical: 28 cases x {`extract`, `extract_stream`} x {per-field
  consumption on and off} x {`DataNotFound` and empty-result reporting}, plus the unit-invariance
  suite (`tests/test_streaming.py`, 10 MultiPoint cases at 1, 3 and all groups per call) and the new
  `test_one_call_per_field_gives_the_same_bytes` (the same 10 cases with `max_fields_per_call = 1`,
  i.e. one call per (param, level)).
- `tests/test_streaming.py::test_a_field_too_large_for_the_budget_is_refused` and
  `tests/test_stream_memory.py::test_a_budget_smaller_than_one_field_refuses_the_request`: the
  refusal happens before any gribjump call.
- `tests/test_missing_fields.py`: the fallbacks and their call counts in both reporting modes on the
  whole-group path and the per-(param, level) path, including
  `test_a_field_that_vanishes_between_calls_is_reported_missing` (what the "later band re-raises"
  case becomes when every field is fetched by exactly one call).
- `tests/test_tree_units.py::test_compressed_axes_expand_as_a_product_in_tree_order` now pins the
  order on a bulk node's `result` (one array per field of the branch) against real `FDBDatacube`
  output, which is what `collect_field_values` and `field_stream` split a unit by.
- `tests/test_unit_sizing.py`: the four terms, whole-field ranges on every grid, the planned fields
  per call for the measured shapes at 1.5 and 1.8 GiB, the caps, the two largest single fields
  fitting one call, and a group that is fetched one field per call.
- Removed with the banding: `tests/test_band_prepare.py` (6 tests) and `tests/test_grid_ranges.py`
  (11 tests), and the band-invariance and band-0-peek cases of `tests/test_streaming.py`; 18 tests
  replace them. Suite: **310 passed, 1 skipped** (was 309 passed, 1 skipped).
- Measured (MEASUREMENTS.md): whole-field ranges on nine shapes, 15 calibration runs all below their
  estimate, the planner on the three REQUESTS.md shapes at both budgets, the resident tree with the
  fold off and on, and `extract_stream` end to end -- the LUMI HEALPix request in **one call at
  803 MB** (two calls and 1,790 MB with per-row ranges and the per-point request side) and the
  whole-world HEALPix and whole-domain EFAS fields
  served whole at **1,242 MB** and **1,192 MB** against a 1.5 GiB budget.

# A request tree bounded before slicing and after prepare

## Why

The unit sizing prices extraction units; nothing priced the *tree*. polytope-feature gives every
value of a branching axis its own node, spatial sub-tree and slice -- a merged axis (`datacube.py`:
"do not compress merged axes") or any axis missing from `compressed_axes_config` -- so a request's
tree grows with the product of those axes' value counts, before a single value is fetched. Measured
on the climate-dt HEALPix-1024 Europe box x 24 hourly fields: 24 sub-trees, 35.5 s of slicing, a
276.7 MB prepared tree. The same box over a month is 720 sub-trees, ~18 min of slicing and an 8.1 GB
tree; a whole-world box x 10 datetimes is 3 GB. All of it is spent before the first gribjump call and
none of it was visible to the planner.

## Behaviour changes

- **`limits.max_tree_bytes`** (new, `None`): bytes a request tree may cost. `None` derives it as half
  of `limits.memory_budget_bytes` when that is set (800 MB in a 3 GiB pod -- the tree is resident for
  the whole request, *beside* the unit the budget covers) and is off when neither is set.
- **`limits.bytes_per_point_tree`** (new, 40): what a point of a spatial sub-tree costs. 24 B/point
  are the bulk node's arrays after `prepare` (`coordinates` 16 B + `indexes` 8 B, exact) and the
  rest covers the row leaves the slicer builds before the fold (9.4 B/point on the
  HEALPix Europe shape, 27-44 B/point where rows are short), which are resident with them.
- **Refused before slicing** (`ValueError`, the `max_points_per_field` client-error path):
  `The request tree alone would need about 13 GB (720 separate branches (dates, times or other
  uncompressed axis values) of about 466409 grid points each), more than the limit of 800 MB; request
  fewer dates and times per request`. A single-branch request is told to `request a smaller area`
  instead. The estimate is `polytope_mars.limits.estimate_tree_bytes` = branches x
  `estimate_points_per_field` x `bytes_per_point_tree`, with the branches counted from the request
  string alone (`branching_value_counts`, `request_value_count`): no datacube, no slice.
- **Refused after `prepare`** on the exact figure, still before any gribjump call:
  `The request tree holds 11516760 grid points in 24 separate branches and costs 277 MB, more than
  the limit of ...; request a smaller area, or fewer dates and times per request`. The exact figure is
  `coordinates.nbytes + indexes.nbytes` summed over the distinct bulk nodes
  (`polytope_mars.bulk_tree.tree_summary`), and it is the backstop for what the estimate cannot see:
  a union whose leaf axis stays uncompressed (polygon pieces, tagged points), and axis values the
  request string does not bound (`ALL`, step/time ranges in units the counters do not parse), which
  count as one value each.
- **`timings["tree_bytes"]`** (new): the exact prepared-tree bytes of every request, reported whether
  or not a limit is set.
- **A non-finite points-per-field estimate is "unknown"**: `get_boundingbox_area` returns NaN for a
  pole-to-pole box, and NaN compares false against any limit, so `max_points_per_field` already
  failed open there; both limits now say so explicitly and leave such a request to the exact check.
- **Interaction with the field refusal**: the tree guard answers first (it runs before the slice), so
  a budget far too small for a request now names the tree rather than the field. At the deployed
  budget the two are far apart; `tests/test_stream_memory.py` pins both (20 MB: the tree of a
  634,550-point field is 15 MB, more than half the budget; 60 MB: the tree fits, the 65 MB field does
  not).

## Separate date/time axes for every feature type

Deployments that merge `date` and `time` into one datacube axis (LUMI, `separate_datetime: true`)
split them again in the fe-worker (`unmerge_date_time_options`) for **every** feature type of the
datasets that merge them, not only for timeseries and polygon. This removes the branching above at
the source: polytope-feature never compresses a merged axis, so a merged axis gives a box request
one branch, one slice and one spatial sub-tree per datetime, while `date` and `time` as ordinary
compressed axes give it one of each whatever the number of datetimes. Measured on the HEALPix-1024
Europe box x 24 hourly fields: 24 sub-trees -> 1, slice 35.5 s -> 1.5 s, prepared tree 276.7 MB ->
11.5 MB, peak 803 MB -> 346 MB (MEASUREMENTS.md, the HEALPix-1024 Europe box x 24 h).

The restriction to timeseries and polygon followed covjsonkit: those feature types were encoded by
covjsonkit's `from_polytope_step`/`walk_tree_step`, which walk separate `date` and `time` nodes,
while boundingbox/circle/frame/shapefile went through `from_polytope`/`walk_tree`, which read the
merged timestamp. What made separate axes safe for the others is in this branch: the `"date"`-role
coverage plans take the reference datetime from the `date` node **plus** the `time` node when the
axes are separate (`Plan.datetime_z`, as `ReforecastPlan.ref()` already did for class=ce), and the
`"date"` legacy walker keeps `time` out of `mars:metadata`. With that, every golden case is
byte-identical with the axes separate (91 assertions; the climate-dt box, level, missing-field and
position cases are the ones that exercise it). `_create_base_shapes` builds separate `date`/`time`
shapes for climate-dt and class=ng requests of every feature type to match the un-merged
`axis_config`; the fe-worker rule and this one have to move together (polytope-server CHANGES.md).

## What polytope-config / the chart must set

**Nothing new.** `limits.memory_budget_bytes` already implies `max_tree_bytes` (half of it). Set
`limits.max_tree_bytes` explicitly only to override that split.

## Verification

- `tests/test_tree_limits.py` (31 tests): the value count of every MARS range form; the branch count
  of a merged date/time axis (720 for 30 dates x 24 times), of the same request with separate
  compressed axes (1) and of an axis missing from `compressed_axes_config`; the byte estimate and its
  linearity in the branches; the derived limit; both refusals and their messages, each with the
  request one byte either side of the limit; `timings["tree_bytes"]` on golden cases; and that a
  refusal happens before the fake is asked for its axes (pre-slice) or for any values (post-prepare).
- `tests/test_stream_memory.py`: the 20 MB tree refusal and the 60 MB field refusal (above).
- The golden corpus is unchanged and byte-identical (91 assertions), as is the rest of the suite:
  **343 passed, 1 skipped** over `tests/golden` and the streaming test modules (the other test modules
  need a local FDB and gribjump schema).

# Feature-extraction results as tensogram (`format: tensogram`)

## Behaviour changes

- **`format: tensogram`** selects `polytope_mars.encoders.tensogram.TensogramEncoder`, a thin adapter
  over the block IR that needs the `tensogram` package (>= 0.24.0; a clear `ImportError` names it when
  it is missing). `supported_formats()` is now `("covjson", "tensogram")`, so the frontend's
  `supported_formats` setting has to list `tensogram` for a request to reach the worker
  (polytope-server CHANGES.md). `content_type` is `application/vnd.ecmwf.tensogram`,
  `file_extension` `tgm`.
- **The message layout is defined in the module docstring** and is the format definition: a header
  message with the parameter table and the request's MARS keys, then one or more messages per
  coverage carrying `latitude`, `longitude` and one values tensor per (parameter, level), then a
  trailer message with the coverage and message counts. Every message is self-describing: its
  `_extra_` names the coverage index, its MARS metadata, its `t` values and its point count, and
  every tensor's `base[i]` entry names its parameter, level and point offset. Messages are
  concatenated, which is how tensogram defines a `.tgm` stream, so the result file reads back with
  `tensogram.iter_messages`, `tensogram.TensogramFile` or the `tensogram` CLI.

  It follows the layout ecmwf/polytope-mars#100 proposed (flat `_extra_` with `source`,
  `feature_type`, `domain_type`, `mars`, `time_values`; `base[i]` with `name`, `role`, `units`,
  `description`, `mars.param`) and differs from it where streaming requires: a values tensor per
  (parameter, level) rather than per parameter, separate `latitude`/`longitude` tensors, a coverage
  that may span messages, and the header/trailer messages that bracket the stream.
- **Coverages keep the extraction order for every domain type.** CovJSON's PointSeries,
  VerticalProfile and Trajectory layouts are point-major across field groups, which is why covjsonkit
  buffers a whole collection to transpose it; the tensogram stream writes the field-group order it is
  produced in, because each tensor already carries the point offset, level and datetimes a consumer
  needs to group by point. A tensogram collection is therefore never buffered, whatever the feature.
- **Fragments.** `encode_iter` yields one complete message per fragment. A message is closed before
  a tensor that would take its raw payload over `max_fragment_bytes` (8 MiB by default, as
  covjsonkit), and a tensor longer than the bound is split into point-slices, so the encoder holds
  one message at a time whatever the request. The unit sizing reads `max_fragment_bytes` off the
  encoder as before.
- **NaN is the missing value.** Tensogram rejects non-finite values unless told to record their
  positions, so every tensor is written with `allow_nan` / `allow_inf`: a value CovJSON writes as
  `null` decodes as NaN. `_extra_["missing_value"]` says so in every message.
- **Compression is tensogram's own** (`zstd` per data object by default), so the result is served
  without HTTP content encoding (polytope-server `codec_for_response`).
- **Config**: `encoders.tensogram` (`max_fragment_bytes` 8 MiB, `compression` `zstd`,
  `compression_level`, `hash` `xxh3`) beside `encoders.covjson`. Nothing a deployment has to set.
- **The dependency is optional**: `pip install polytope-mars[tensogram]`, and
  `tests/requirements_test.txt` carries it so the suite covers the format. Deployments install it
  with the worker (polytope-server `requirements.txt`).
- **Tensogram output is not byte-reproducible**: the library stamps a timestamp and a UUID into every
  message's `_reserved_` section. There is therefore no golden-bytes corpus for this format; the
  tests compare decoded content.

## Verification

- `tests/test_tensogram.py` (58 tests): ten golden cases -- MultiPoint box and polygon, an ensemble,
  levels, bitmap-missing points, a missing field, a time series on both coverage plans, a vertical
  profile and a trajectory -- encoded as tensogram, decoded with the `tensogram` package and compared
  with the CovJSON of the same request, record by record (datetime, parameter, level, latitude,
  longitude, ensemble member). For MultiPoint domains the coverages are also compared in order:
  `mars:metadata`, the `t` axis, the coordinates and each range's values against the matching tensor.
  Also: the header's parameter table against the CovJSON collection's `parameters`, the trailer's
  counts, `null` against NaN count for bitmap-missing points, a missing parameter left out of its
  coverage, the fragment bound at 512 and 2048 bytes (every message within it, the pieces
  reassembling to the same records), one message per coverage at the default bound, and the same
  records with one field per gribjump call and with all of them in one.
- Measured (MEASUREMENTS.md): the climate-dt HEALPix Europe x 24 hourly request and the EFAS Danube
  x 10 steps request through both formats. The peak is within 2% of the CovJSON run either way
  (352.5 MB against 346.1 MB, 302.2 MB against 311.2 MB) and the output is 7.7x and 30x smaller.
- The CovJSON corpus is untouched: suite **401 passed, 1 skipped** (was 343 passed, 1 skipped).

# One extraction path, and the request-costing helpers removed

The sections above arrived at a single way to extract a request: bulk spatial nodes, one call per unit
of consecutive field groups, every field fetched whole and consumed field by field. This section
removes the alternatives and the measurements that were kept beside it, so that what the worker runs is
what the repo contains.

## Request costing

- **`polytope_mars.utils.areas.field_area` and `request_cost` are gone**, together with `count_values`
  (a MARS value counter only those two used) and `tests/test_costing.py`. They priced a request as
  `shape area x number of fields` for the `max_area` refusal, which `limits` replaced with
  `max_polygon_points`, `max_points_per_field` and `max_tree_bytes` -- limits expressed in grid points
  rather than in square kilometres. `Feature.field_area` is gone with them; the shape areas
  (`get_boundingbox_area`, `get_polygon_area`, `get_circle_area_from_coords`) stay, they feed the
  points-per-field estimate of `limits`.

## Config keys

- **`limits.bytes_per_point` is gone** (`BytesPerPointConfig` with it). It was the per-mapper-family
  table that `limits.bytes_per_value` replaced with one constant plus the index-range count read off the
  prepared tree; no deployment set it. `coverageconfig` and `polygonrules` remain accepted as aliases of
  `encoders.covjson` and `limits` -- polytope-config sets both.

## Observability

- **`timings` loses `retrieve_ms`** (it was slice + prepare + get). The fe-worker computes its own
  `retrieve_ms` over the whole request and overwrites the value, so the one reported here was never read.
  `slice_ms`, `prepare_ms` and `get_ms` are unchanged and add up to the same number.
- polytope-feature drops `datacube.prototype_metrics["returned_range_arrays"]` (`../polytope/CHANGES.md`),
  which reported 0 for every request.

## Dead code

- Gone, with no caller anywhere in the extraction: `extract.mapper_type` (and its `__all__` entry),
  `extract.BlockExtractor._slice_and_prepare`, `coverage_plan._branch_matches`, `Plan.header_extra` and
  `TimeSeriesReforecastPlan.header_extra` (`api.PolytopeMars._build_header` decides the
  `pointseries_order` quirk where it builds the header), `bulk_tree.tree_bytes` (callers use
  `tree_summary`), `bulk_tree.RangeCounts.n_counted` and `sizing.UnitSizing.fits_group` (the planner and
  its tests ask `max_unit_groups(...) >= 1`).

## Test suite

- The unit-layout suite (`tests/test_streaming.py`) runs nine MultiPoint cases instead of ten:
  `ode_bbox_subhourly` is the only Lambert-conformal case and slicing its quadtree costs 7 s per run,
  while its unit planning has the same shape as `cdt_polygon_sfc`'s and its subhourly step formatting is
  pinned byte for byte by two golden cases. `tests/test_streaming.py` runs in 2.3 s instead of 38.8 s.
