# Legacy pipeline measurements

Produced by `python tools/measure_memory.py [slice|get|e2e]` with the pristine oracle environment
(`.venv-legacy`: polytope-python 2.1.20, covjsonkit 0.2.26, numpy 2.4.6, Python 3.11) against the fake
gribjump (`polytope_mars.testing`), on an AMD Ryzen 9 7950X. Every scenario runs in its own process.
RSS is `psutil` RSS after `gc.collect()`; peak is `getrusage` max RSS. A fresh process sits at ~175-180 MiB
after imports and datacube construction (`rss_before`). Wall times are for orientation only.

The fake returns float64 numpy arrays per range like real gribjump, so `datacube.get` costs are
representative; it does no I/O, so the gribjump C++ side (decode buffers, remote transfer) is not included.

## 1. Slice-time cost (`Polytope.slice` only, one field)

| scenario | grid | lat nodes | points | slice s | RSS before MiB | RSS after MiB | bytes/point |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| (a) global bbox | HEALPix nested 1024 | 4095 | 12,583,936 | 140.0 | 181.6 | 999.6 | 68.2 |
| (b) Europe polygon (8 vertices, 35-71N, 15W-40E) | HEALPix nested 1024 | 753 | 321,936 | 6.4 | 176.7 | 602.1 | 1385.4 |
| (c) Europe bbox `[[72,-25],[34,45]]` | octahedral 1280 | 540 | 222,960 | 0.9 | 177.6 | 209.8 | 151.6 |
| (d) Danube bbox `[[50.25,8.15],[42.08,29.73]]` | EFAS local_regular 2969x4529 | 490 | 634,550 | 7.5 | 176.2 | 208.1 | 52.7 |

bytes/point = (RSS after - RSS before) / points; the tree is still alive when RSS is read.

- Bounding boxes produce one compressed longitude leaf per latitude line (O1280 Europe: 1,090 nodes, 540
  leaves), so the tree is ~50-150 B per point, mostly the leaf's tuple of longitudes and index list.
  (c) is high per point only because the absolute delta (32 MiB) is small.
- **Polygons do not compress longitudes**: the Europe polygon tree has 322,705 nodes for 321,936 points,
  one `TensorIndexTree` leaf (plus `SortedList`) per point. tracemalloc puts the live tree at ~381 MiB
  (~1.2 KB/point: 182 MiB of tree nodes, 94 MiB of `SortedList`s, 66 MiB from `copy`). After deleting the
  tree, traced Python memory drops to 39 MiB but RSS stays (the allocator does not hand it back).
  A global polygon at H1024 would therefore need ~15 GB just for the tree; per-point trees are the
  dominant slice-time cost for polygons, not the bbox case.
- The global H1024 bbox (12.6M points) fits in ~0.8 GiB of tree but takes 140 s to slice.

## 2. `bytes_per_point` of a bare `datacube.get`

Slice a bbox, then call `datacube.get(tree)` (gribjump extraction + assignment of results onto the tree,
no encoding); 4 fields (2 params x 2 steps/times) per tree.

| mapper family | scenario | tree points | fields | values | slice B/point | get s | RSS after slice MiB | RSS after get MiB | **get B/value** |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| local_regular | EFAS Danube bbox, 2 params x 2 steps | 634,550 | 4 | 2,538,200 | 52.9 | 0.78 | 208.5 | 325.9 | **48.5** |
| healpix_nested | H1024 bbox `[[55,-10],[35,30]]`, 2 params x 2 times | 342,700 | 4 | 685,400 | 82.6 | 2.95 | 204.4 | 283.9 | **121.6** |
| octahedral | O1280 Europe bbox, 2 params x 2 steps | 222,960 | 4 | 891,840 | 151.6 | 0.17 | 209.9 | 258.6 | **57.3** |

`tree points` counts leaf points over all tree branches (for HEALPix the merged date/time axis puts the
two times above latitude, so 171,350 spatial points appear twice). Each value ends up as a Python
`np.float64` object (32 B) plus a list slot (8 B) in the leaf's `result` list, hence ~50 B/value for the
grids whose leaves map to one contiguous index range per latitude. HEALPix nested leaves map to many
short index ranges (nested ordering), and the extra per-range work and temporary arrays show up both in
time (17x slower per value than local_regular) and in memory (~120 B/value; HEALPix `peak_rss` was
337 MiB vs 284 MiB after get). Suggested constants for the band-size formula: local_regular 50,
octahedral 60, healpix_nested 125 bytes per value, plus the slice cost per spatial point above.

## 3. Legacy end-to-end bytes per value (`extract` + `json.dumps(...).encode()`)

| scenario | values | coverages | extract s | dumps s | output MiB | output B/value | RSS before MiB | peak RSS MiB | **peak B/value** |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| EFAS Switzerland bbox `[[47.80,5.95],[45.82,10.47]]`, 40 steps (32,249 points) | 1,289,960 | 40 | 11.6 | 1.3 | 67.6 | 55.0 | 174.9 | 1215.6 | **845.9** |
| H1024 bbox `[[50,0],[39.5,10.5]]`, 24 hourly datetimes (23,831 points) | 571,944 | 24 | 4.6 | 0.6 | 29.3 | 53.7 | 175.0 | 402.8 | **417.7** |

peak B/value = (peak RSS - RSS before extract) / values. `PolytopeMars.timings` (ms):

| scenario | datacube_init | slice | get | encode |
| --- | ---: | ---: | ---: | ---: |
| EFAS Switzerland, 40 steps | 2 | 217 | 104 | 11,268 |
| H1024 bbox, 24 datetimes | 6 | 665 | 2,914 | 1,037 |

- EFAS (class=ce) goes through `from_polytope_reforecast`, which flattens the tree into one Python dict
  per value (`_reforecast_records`) before grouping: encode is 97% of the time and the peak (~850 B/value)
  is reached inside `extract`, before `json.dumps`.
- The fe-worker then hands the encoded bytes to Rust (one more full copy of the output, ~55 B/value) which
  is not included here.
- Fake values print as 15-16 significant digits (e.g. `77542400612.685`), the same order as real
  float64 field values, so output bytes per value should be representative.

## Scaling notes

All scenarios ran at the requested size; none needed scaling down. The global H1024 slice is the slowest
(2.3 min). A global H1024 *polygon* was not attempted (projected ~15 GB from (b)).

# Streaming pipeline measurements

`python tools/measure_memory.py stream` (one subprocess per run, `.venv` with polytope-feature at
`50018d5a`, same machine and fake gribjump as above). Request: EFAS Danube bbox
`[[50.25,8.15],[42.08,29.73]]`, class=ce stream=efas, steps 6 to 60 by 6, one param: 634,550 points x 10 steps =
**6,345,500 values**, 10 coverages, 337 MiB of CovJSON. The output is consumed chunk by chunk and discarded (as
the fe-worker will stream it). Growth = peak RSS (`VmHWM`, reset at the start) minus RSS before `extract_stream`
(~176 MiB after imports).

| run | memory_budget_bytes | units (gets) | bands | largest chunk MiB | wall s | RSS growth MB | B/value |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| streaming | 200,000,000 | 10 | 10 | 23.5 | 7.8 | **163** | 25.6 |
| streaming | 20,000,000 | 50 | 50 | 5.8 | 7.1 | **123** | 19.5 |
| streaming, no budget | None | 10 | 10 | 23.5 | 7.6 | 163 | 25.7 |
| new `extract()` + `json.dumps` (the fe-worker's buffered path) | None | 10 | 10 | - | 18.4 | 2,050 | 323 |
| legacy `extract()` + `json.dumps` (`.venv-legacy`) | - | 1 | - | - | 56.6 | **5,242** | 826 |

- Every field group here fits a 200 MB budget (634,550 points x 1 field x 64 B = 41 MB), so the 200 MB and
  no-budget runs are the same call pattern: one get per step. At 20 MB each step is cut into 5 latitude bands.
- The floor of ~120 MB is the sliced/prepared tree (~30 MB for 634k points) plus slicing transients; it does
  not grow with the number of steps. The remaining ~40 MB at 200 MB is one coverage's unit (get result, float64
  field copy, the formatted coordinate block of 23.5 MiB).
- `tests/test_stream_memory.py` asserts growth < 2 x max(budget, 100 MB) for the 200 MB and 20 MB runs.
- Stage timings of the 200 MB run (ms): slice 3,335, prepare 283, get 2,847, encode 1,164, first byte after
  20 ms (before slicing).
- The buffered `extract()` is kept for compatibility; it holds the whole document as Python objects
  (`json.loads`), 2.5x less than legacy but still ~320 B/value.

# Sizing an extraction unit

Same machine and fake gribjump as above, `.venv` with polytope-feature `53ccb1fe` (flat per-field result
assignment). Re-runnable:

    python tools/measure_memory.py ranges      # points and index ranges per field, and what they cost
    python tools/measure_memory.py calibrate   # limits.bytes_per_value

Re-run both after polytope-feature changes how results are fetched or consumed (`get_iter`), and after
covjsonkit changes its fragment sizes.

## 1. Points, index ranges and gribjump's residency (one field)

Counted from the prepared tree by `polytope_mars.grid_ranges` (the same ranges `_gribjump_requests` builds,
pinned against the fake's received requests in `tests/test_grid_ranges.py`). gribjump MB =
`8 x points + points/8 + 96 x ranges` (`ExtractionData.h`: one values vector and one bitmap vector per
range), without the safety factor. Python MB = `128 x points`.

| request | grid | lat nodes | points | ranges | points/range | gribjump MB | B/value | of which ranges | Python MB |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| global bbox `[[90,-180],[-90,180]]` | HEALPix nested 1024 | 4,095 | 12,582,912 | 7,864,320 | 1.60 | **857.2** | 68.1 | 755.0 | 1,610.6 |
| global bbox | octahedral 1280 | 2,560 | 6,599,680 | 2,560 | 2578.0 | **53.9** | 8.2 | 0.2 | 844.8 |
| Europe bbox `[[72,-25],[34,45]]` | HEALPix nested 1024 | 1,595 | 479,865 | 300,315 | 1.60 | 32.7 | 68.2 | 28.8 | 61.4 |
| Europe bbox, half as wide (`34..72N, 25W..10E`) | HEALPix nested 1024 | 797 | 239,821 | 150,209 | 1.60 | 16.4 | 68.3 | 14.4 | 30.7 |
| Europe bbox | octahedral 1280 | 540 | 222,960 | 1,080 | 206.4 | 1.9 | 8.6 | 0.1 | 28.5 |
| Danube bbox `[[50.25,8.15],[42.08,29.73]]` | EFAS local_regular | 490 | 634,550 | 490 | 1295.0 | 5.2 | 8.2 | 0.0 | 81.2 |

- **HEALPix nested does not merge into runs, at any size**: 1.6 points per range for the Europe box and
  for the whole world alike. A single global HEALPix-1024 field is **7.86M ranges**, whose vector pairs are
  **755 MB of the 857 MB** gribjump holds -- 7.5x the 101 MB of values. Everything else measured here is
  within 8.6 B/value of the bare values. A range-merge (or a mask/stride request) in gribjump or
  polytope-feature would take a global HEALPix field from 857 MB to ~102 MB: **a required follow-up** if
  whole-world HEALPix fields are to be served in one call.
- No request measured here asks for the same grid index from two different latitude nodes
  (`cross_node_duplicates` false), including boxes that wrap past the longitude seam, so latitude bands could
  be prepared independently (the banded extraction this once supported is gone: a field is never split).
- Counting the ranges walks every point once, like `prepare`: 0.4 s for the Danube box, 7 s for the HEALPix
  Europe box, **398 s for a global HEALPix field** (`prepare` itself takes 402 s for it). Planning a
  whole-world HEALPix request therefore doubles its slice-time cost; polytope-feature returning the counts
  it already computes in `prepare` would remove that.

## 2. `limits.bytes_per_value`: the Python side of one `datacube.get`

Peak RSS growth of one `datacube.get` + block emission (`python tools/measure_memory.py calibrate`), the
peak measured from after the tree is sliced and prepared, with the budget and the cap set out of the way so
that the whole request is one unit. Required B/value = `(growth - gribjump term) / values`, i.e. what
`bytes_per_value` must be for the estimate to cover the measurement.

| shape | fields | points | values | ranges/field | growth MB | B/value | estimate MB | required B/value |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| EFAS Danube | 1 | 634,550 | 634,550 | 490 | 73.8 | 116.3 | 89.0 | 104.0 |
| EFAS Danube | 4 | 634,550 | 2,538,200 | 490 | 81.9 | 32.3 | 356.1 | 20.0 |
| EFAS Danube | 12 | 634,550 | 7,614,600 | 490 | 162.9 | 21.4 | 1,068.3 | 9.1 |
| HEALPix-1024 Europe | 1 | 479,865 | 479,865 | 300,315 | 101.5 | 211.6 | 110.5 | **109.2** |
| HEALPix-1024 Europe | 4 | 479,865 | 1,919,460 | 300,315 | 295.5 | 154.0 | 442.1 | 51.6 |
| HEALPix-1024 Europe | 12 | 479,865 | 5,758,380 | 300,315 | 830.8 | 144.3 | 1,326.2 | 42.0 |
| O1280 Europe | 1 | 222,960 | 222,960 | 1,080 | 19.5 | 87.5 | 31.4 | 74.5 |
| O1280 Europe | 4 | 222,960 | 891,840 | 1,080 | 21.3 | 23.9 | 125.6 | 11.0 |
| O1280 Europe | 12 | 222,960 | 2,675,520 | 1,080 | 48.4 | 18.1 | 376.9 | 5.2 |

**Default: `bytes_per_value = 128`** -- the worst measured case needs 109.2 (HEALPix, one field), and every
row's estimate is above its growth. Least squares per shape (`growth = intercept + slope x values`):

| shape | slope B/value | intercept MB |
| --- | ---: | ---: |
| EFAS Danube | 13.4 | 58.0 |
| O1280 Europe | 12.5 | 14.0 |
| HEALPix-1024 Europe | 138.4 | 32.9 |

- The per-value cost itself is ~13 B/value on both grids whose fields are few ranges; the rest is per
  *call*, which is why one field costs 5-10x more per value than twelve.
- The HEALPix slope is mostly **an artefact of the fake**: it synthesises one numpy array per range before
  concatenating them into `values_flat` (300,315 arrays per field, ~33 MB), while real gribjump fills
  `values_flat` in C++ and `polytope_feature.datacube.fdb_assign.field_values_flat` reads it without
  building any per-range object. The fake was changed in this phase to expose `values_flat` with lazy
  per-range views, which removed ~150 MB from the 4-field HEALPix run; what remains is its own synthesis.
  Production's HEALPix cost is the ~13 B/value of the other grids plus the per-call cost of building 300k
  request ranges in `_gribjump_requests` (~90 MB for this shape, independent of the number of fields).
- So 128 B/value is conservative for everything except a single-field HEALPix call, which is what it is
  calibrated on. Re-measure against real gribjump before lowering it: at 32 B/value the units of the two
  cases below would be ~4x larger.

## 3. The two requests the sizing has to get right

`python tools/measure_memory.py stream`, budget as the chart injects it.

| request | budget | groups | planned k | units | estimated unit MB | peak RSS MB | growth MB | B/value | wall s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| HEALPix-1024 Europe box x 24 hourly fields (11.5M values) | 1.5 GiB | 24 | **14** | 2 | 1,547.2 | **1,788.7** | 1,602.6 | 139.2 | 522 |
| EFAS Danube bbox x 40 steps (25.4M values) | 1 GiB | 40 | **12** | 4 | 1,068.3 | **474.7** | 288.9 | 11.4 | 9 |

- The HEALPix request is the one that was OOM-killed at 3 GiB on LUMI with 19-field units
  (`480k x 160 x 19 = 1.46 GB` against the same budget). It now runs in two calls of 14 and 10 fields with a
  peak of 1.79 GB, 40% under the 3 GiB limit, and its output is unchanged.
- Peak RSS is the whole process, so it also holds the sliced and prepared tree of all 24 branches and the
  slicing transients; the planner's estimate covers the unit alone. The chart's
  `limits.memory_budget_bytes` must therefore stay a *share* of the pool's memory, not the whole of it.
- 230 s of the HEALPix run is `prepare` on the whole tree (11.5M grid-index lookups, one per point per
  branch) and 29 s is slicing. A unit that fits is still prepared with the whole tree; preparing per unit
  (as the banded path already prepares per band) would cut that to one branch's worth.
- The EFAS request was 2 units under the per-mapper constant (k=26 at 64 B/point and no gribjump term); the model halves
  it to 12 groups per call, i.e. 4 calls instead of 2 -- about 1 s more at ~480 ms per call.

## 4. Largest fragment the CovJSON encoder emits per block

`max_chunk_mib` of the calibration runs: the biggest single `bytes` object the encoder returns for one
block, which is a coordinate block (the `composite` tuples), **38.0-38.8 B per point** on every grid and
independent of the number of fields:

| field | points | largest fragment | B/point |
| --- | ---: | ---: | ---: |
| EFAS Danube | 634,550 | 23.5 MiB | 38.8 |
| HEALPix-1024 Europe | 479,865 | 17.4 MiB | 38.0 |
| O1280 Europe | 222,960 | 8.2 MiB | 38.5 |

A 26M-point field (a whole-world O1280 bbox is 6.6M, a global HEALPix-1024 one 12.6M; 26M is a
high-resolution global grid) would therefore be emitted as a **single ~1.0 GB fragment** of coordinates,
whatever the extraction unit size: the band only bounds what polytope-mars holds, not what the encoder
builds per block. Values blocks are smaller (~17-20 B/value). Bounding the fragment is covjsonkit's side of
the contract (`CovjsonStreamEncoder.encode_iter`), not polytope-mars'.

# Per-field consumption, and what one call really costs

Same machine and fake gribjump as above, `.venv` with polytope-feature `d3656bd2`
(`FDBDatacube.get_iter`). Re-runnable:

    python tools/measure_memory.py ranges      # points and index ranges per field (unchanged)
    python tools/measure_memory.py calibrate   # limits.bytes_per_point_call, limits.bytes_per_value
    python tools/measure_memory.py targets     # what the planner does with the deployed request shapes
    python tools/measure_memory.py --run stream_healpix1024_europe_24fields_1_5GiB   # measured peak

Re-run `calibrate` after polytope-feature changes how requests are built or results consumed, and
after covjsonkit changes `max_fragment_bytes`.

## 1. What one call costs, per shape and per field count

`tools/measure_memory.py calibrate`: one unit of *n* fields on the production path
(`per_field_consumption`, `FDBDatacube.get_iter`), the budget and the caps set out of the way so
that the whole request is one call, the peak measured from after the tree is sliced and prepared.
`cpp MB` is the exact gribjump term of that call (`n_fields x (8 x points + points/8 + 96 x
ranges)`, no safety factor) and `residual` what the Python terms have to cover. The EFAS shapes keep
their group axes compressed in one branch (`request side` = per call); the HEALPix shape is
climate-dt hourly, whose merged date/time axis gives every field its own branch (per group).

| run | fields | group fields | branches | points | ranges/field | growth MB | cpp MB | residual MB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| efas_danube_1 | 1 | 1 | 1 | 634,550 | 490 | 74.2 | 5.2 | 69.0 |
| efas_danube_4 | 4 | 1 | 1 | 634,550 | 490 | 72.7 | 20.8 | 51.9 |
| efas_danube_12 | 12 | 1 | 1 | 634,550 | 490 | 89.7 | 62.4 | 27.3 |
| efas_danube_48 | 48 | 1 | 1 | 634,550 | 490 | 276.8 | 249.7 | 27.0 |
| efas_volga_4 | 4 | 4 | 1 | 609,851 | 1,131 | 64.7 | 20.3 | 44.5 |
| efas_volga_12 | 12 | 4 | 1 | 609,851 | 1,131 | 120.5 | 60.8 | 59.8 |
| efas_volga_48 | 48 | 4 | 1 | 609,851 | 1,131 | 425.6 | 243.1 | 182.6 |
| healpix1024_europe_1 | 1 | 1 | 1 | 479,865 | 300,315 | 101.6 | 32.7 | 68.9 |
| healpix1024_europe_4 | 4 | 1 | 4 | 479,865 | 300,315 | 309.7 | 130.9 | 178.8 |
| healpix1024_europe_12 | 12 | 1 | 12 | 479,865 | 300,315 | 819.0 | 392.7 | 426.2 |
| healpix1024_europe_48 | 48 | 1 | 48 | 479,865 | 300,315 | 2904.0 | 1571.0 | 1333.0 |
| o1280_europe_1 | 1 | 1 | 1 | 222,960 | 1,080 | 19.6 | 1.9 | 17.7 |
| o1280_europe_4 | 4 | 1 | 1 | 222,960 | 1,080 | 19.8 | 7.7 | 12.1 |
| o1280_europe_12 | 12 | 1 | 1 | 222,960 | 1,080 | 28.2 | 23.0 | 5.2 |
| o1280_europe_48 | 48 | 1 | 1 | 222,960 | 1,080 | 94.3 | 91.9 | 2.4 |

Fitting ``residual = bytes_per_point_call x (points x branches) + bytes_per_value x group values

- 16 MiB of fragments`` over all 15 runs by least squares:

    bytes_per_point_call = 57.6 B/point     bytes_per_value = 16.8 B/value

**Defaults: `bytes_per_point_call = 128`, `bytes_per_value = 32`** -- about twice the fit, which
together with the safety factor on the gribjump term leaves every measured run below its
estimate (worst margin 1.26x, on the 48-field Volga unit):

| run | request points | group values | residual MB | needs B/point_call | needs B/value | estimate MB | covered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| calibrate_efas_danube_1 | 634,550 | 634,550 | 69.0 | 50.3 | -45.7 | 126.1 | yes |
| calibrate_efas_danube_4 | 634,550 | 634,550 | 51.9 | 23.4 | -72.6 | 149.5 | yes |
| calibrate_efas_danube_12 | 634,550 | 634,550 | 27.3 | -15.4 | -111.4 | 212.0 | yes |
| calibrate_efas_danube_48 | 634,550 | 634,550 | 27.0 | -15.9 | -111.9 | 492.9 | yes |
| calibrate_efas_volga_4 | 609,851 | 2,439,404 | 44.5 | -82.5 | -20.6 | 203.3 | yes |
| calibrate_efas_volga_12 | 609,851 | 2,439,404 | 59.8 | -57.5 | -14.4 | 264.0 | yes |
| calibrate_efas_volga_48 | 609,851 | 2,439,404 | 182.6 | 143.9 | 36.0 | 537.5 | yes |
| calibrate_healpix1024_europe_1 | 479,865 | 479,865 | 68.9 | 76.6 | -19.4 | 142.6 | yes |
| calibrate_healpix1024_europe_4 | 1,919,460 | 479,865 | 178.8 | 76.4 | -174.4 | 474.2 | yes |
| calibrate_healpix1024_europe_12 | 5,758,380 | 479,865 | 426.2 | 68.4 | -682.8 | 1358.3 | yes |
| calibrate_healpix1024_europe_48 | 23,033,520 | 479,865 | 1333.0 | 56.5 | -3401.1 | 5336.9 | yes |
| calibrate_o1280_europe_1 | 222,960 | 222,960 | 17.7 | -27.9 | -123.9 | 55.3 | yes |
| calibrate_o1280_europe_4 | 222,960 | 222,960 | 12.1 | -53.0 | -149.0 | 63.9 | yes |
| calibrate_o1280_europe_12 | 222,960 | 222,960 | 5.2 | -83.9 | -179.9 | 86.9 | yes |
| calibrate_o1280_europe_48 | 222,960 | 222,960 | 2.4 | -96.5 | -192.5 | 190.3 | yes |

- "needs B/point_call" is what the measurement would demand of that constant with the other one at
  its default and *without* the safety factor; a negative value means the other terms already cover
  the row. Only the 48-field Volga unit asks for more than 128 B/point (144), and the safety factor
  covers it.
- **The request side is paid once per spatial sub-tree, not once per call.** `FDBDatacube` builds a
  Python `int` per point per branch and keeps them until the call returns, and the fields of a branch
  share them. The EFAS rows (`number`/`step` compressed in one branch) therefore cost the same 50 B
  per point at 1 and at 48 fields, while the HEALPix rows (one branch per hourly field) pay ~70 B per
  point per field: 1.33 GB of residual for 48 fields. That is what `UnitSizing.request_bytes`
  multiplies by the unit's branch count, and it is why a 24-hour HEALPix request is planned into
  14-field units while a 12,000-field EFAS ensemble goes 188 fields at a time.
- The per-value term is small and grid-independent (16.8 B/value fitted, polytope-feature measures
  ~24 B/value for the same thing): the leaf arrays plus the float64 field copy handed to the encoder.
  This is what per-field consumption buys -- it applies to one field group instead of to the whole
  call.
- `efas_danube_1`, `efas_volga_4`, `healpix1024_europe_1` and `o1280_europe_1` are single-group
  requests, which never take the multi-group path: they are fetched with one whole-unit `get`
  (`unit_source` = `get`) and are in the table as the one-field baseline.
- The fake builds `values_flat` in one vectorised pass rather than one numpy array per index range
  (300,315 of them per HEALPix field); synthesising them one at a time dominates every HEALPix
  measurement and is not something production pays for.

## 2. The planner on the deployed request shapes

`python tools/measure_memory.py targets`: the request is sliced, prepared and planned (no data
fetched) and its units replanned at both budgets with the deployed defaults. Points and ranges are
per field; "fields per call" is the largest unit the planner produced.

| request | groups x fields | points | ranges/field | request side | 1.5 GiB: fields/call, calls | 1.8 GiB: fields/call, calls |
| --- | ---: | ---: | ---: | --- | ---: | ---: |
| EFAS Volga ensemble, 4 params x 50 members x 60 steps | 3,000 x 4 | 609,851 | 1,131 | per call | **188, 120** (est. 1,601 MB) | **200, 60** (est. 1,692 MB) |
| EFAS Switzerland ensemble, 1 param x 50 x 60 | 3,000 x 1 | 18,834 | 151 | per call | **1,000, 3** (est. 271 MB) | **1,000, 3** |
| climate-dt HEALPix-1024 Europe box x 24 hourly | 24 x 1 | 479,865 | 300,315 | per group | **14, 2** (est. 1,579 MB) | **17, 2** (est. 1,911 MB) |

- **Volga**: 188 fields per call at 1.5 GiB against 12 fields when the Python term is charged for
  every field of the call, i.e. ~15x fewer
  calls (~2 min of fixed cost instead of ~8 min at 0.5 s per call). The call *count* is 120 rather
  than 12,000/188 = 64 because coverages come out (reference, step, number) -- all 50 members of a
  step, then the next step (`tests/golden/expected/efas_bbox_ensemble.covjson`) -- and a unit must be
  a cartesian product of the group axes, so a unit of 47 groups covers 47 of the 50 members of one
  step and the remaining 3 go in a second call. 60 calls (one step each) need room for 50 groups =
  200 fields, which is what the 1.8 GiB budget buys. A budget between the two does not help: the
  next useful size after 50 groups is 100 (two whole steps).
- **Switzerland**: the per-call field cap decides (1,024 fields), and the product rule rounds the
  unit down to 20 steps x 50 members = 1,000 groups, so 3 calls instead of 3,000. The budget is
  irrelevant here (271 MB of 1.5 GiB).
- **HEALPix Europe x 24**: 14 fields per call. Every hourly field is its own branch (the merged
  date/time axis), so this unit pays the request side 14 times -- that term, not gribjump's buffer,
  is what bounds it.

## 3. Measured peak of the HEALPix case

`python tools/measure_memory.py --run stream_healpix1024_europe_24fields_1_5GiB` (the request that
was OOM-killed on LUMI at 3 GiB with 19-field units), budget 1.5 GiB:

| | units (gets) | fields per unit | estimated unit MB | peak RSS | growth | wall | get / prepare / slice |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| whole-unit `get` | 2 | 14 | 1,547 | 1,789 MB | 1,603 MB | 522 s | - |
| per-field `get_iter` | 2 | 14 | 1,579 | **1,790 MB** | 1,603 MB | 511 s | 237 s / 235 s / 29 s |

**1.79 GB peak against the 2.2 GB target** (3 GiB pod, 1.5 GiB budget), output byte count unchanged.
The peak is the whole process: the sliced and prepared tree of all 24 branches and the slicing
transients are in it, which is why it exceeds the planner's estimate for the unit alone. Half the
wall time is `prepare` on the whole tree (11.5M grid-index lookups); preparing per unit would cut
that, as the banded path already does per band.

## 3b. The same requests on the dev clusters (real gribjump, fe-worker pods at 3 GiB)

Worker image (`polytope-mars` `ce8482eb4021`, `limits.memory_budget_bytes` 1,610,612,736),
`timings` from the worker's `request completed` line. `max_rss_bytes` is the whole process
(interpreter, imports, the sliced tree, the Rust side), not the unit alone.

LUMI, climate-dt HEALPix-1024 Europe box (479,865 points, 300,315 ranges per field, one branch per
hourly field), one call each, **fresh pod per run** (`rollout restart` before each):

| fields in the call | planner's unit estimate | peak RSS | RSS after the request |
| ---: | ---: | ---: | ---: |
| 1 | 143 MB | 393 MB | 287 MB |
| 4 | 474 MB | 784 MB | 534 MB |
| 14 | 1,579 MB | 1,995 MB | 977 MB |

A straight line: **peak = 265 MB + 123 MB per field**. The model's slope with the safety factor is
110 MB per field (`cpp` 32.7 MB x 1.5 + 128 B/point x 479,865), so the per-field cost of the real
pygribjump/remote path is ~11% above the fitted one, and the 265 MB intercept is the process
baseline the unit estimate deliberately leaves to the other half of the pod. The 24-hour request
(2 calls, 14 + 10 fields) peaked at 1,995 MB in a fresh pod and at 2,279 MB in a pod that had
served a 944 MB request first (memory the allocator keeps), both under the 3 GiB limit.

Bologna (`fdbtest`, EFAS as expver 0099):

| request | calls | fields per call | unit estimate | peak RSS | wall | get (max per call) |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| EFAS Danube bbox, 40 steps (1.28 GB out) | **1** (4) | 40 | 430 MB | 528 MB | 33 s | 21 s |
| EFAS Switzerland ensemble, 50 x 60 (2.97 GB out), cold | **3** (8) | 1,000 | 271 MB | 528 MB | 698 s | 696 s (243 s) |
| the same request again, 9 min later | 3 | 1,000 | 271 MB | 528 MB | 265 s | 262 s (96 s) |
| IFS enfo Volga polygon ensemble, O1280, 7,250 coverages (5.97 GB out) | **8** (17) | 1,015 | 235 MB | 437 MB | 195 s | 187 s (68 s) |

The parenthesised call count is what the same request needed when the Python term was charged for
every field of a call (128 B/value, per-field consumption off).

The wall time of the ensemble requests is gribjump's, whatever the batching: Switzerland costs the
server 0.23 s per field cold and 0.09 s warm (the second run found the GRIB files in the page
cache), so the fewer calls buy the fixed per-call cost back (~2 s here) and nothing else. Peak RSS
never moved from the 528 MB the 40-field Danube unit had set on that pod.

## 4. Largest fragment the CovJSON encoder emits per block

`max_chunk_mib` of the calibration runs: **5.4-5.5 MiB** on every shape and field count, against
covjsonkit's `max_fragment_bytes` of 8 MiB. The sizing charges `2 x max_fragment_bytes` (16.8 MB,
one fragment being built while the previous is still referenced), which the measurements never
approach: a coordinate block is emitted as fragments rather than as one 17-23 MiB object.

# One bulk node per spatial sub-tree: whole-field ranges and whole-field calls

Same machine and fake gribjump as above, `.venv` with polytope-feature `6ac17964`
(`bulk_grid_leaves`, the fold in `prepare`). Re-runnable:

    python tools/measure_memory.py ranges      # points and whole-field index ranges
    python tools/measure_memory.py calibrate   # limits.bytes_per_value
    python tools/measure_memory.py targets     # what the planner does with the deployed request shapes
    python tools/measure_memory.py tree        # what a prepared tree costs
    python tools/measure_memory.py --run stream_healpix1024_whole_world_1_5GiB
    python tools/measure_memory.py --run stream_efas_whole_domain_1_5GiB

## 1. Whole-field index ranges

`tools/measure_memory.py ranges`: one field, the counts read off the prepared tree's bulk node the
way the planner reads them. "per row" is the count of the same request when the ranges are derived
row by row (one range per run of consecutive indices *within a latitude row*).

| field | points | ranges | per row | points per range | gribjump B/value |
| --- | ---: | ---: | ---: | ---: | ---: |
| HEALPix-1024 whole world | 12,582,912 | **1** | 7,864,320 | 12,582,912 | 8.1 |
| O1280 whole world | 6,599,680 | **1** | 2,560 | 6,599,680 | 8.1 |
| HEALPix-1024 Europe box | 479,865 | **1,388** | 300,315 | 346 | 8.4 |
| HEALPix-1024 Europe box, half as wide | 239,821 | **1,005** | 150,209 | 239 | 8.5 |
| O1280 Europe box | 222,960 | **541** | 1,080 | 412 | 8.4 |
| EFAS Danube box | 634,550 | 490 | 490 | 1,295 | 8.2 |
| EFAS Volga polygon | 609,851 | 1,131 | 1,131 | 539 | 8.3 |
| EFAS Switzerland polygon | 18,834 | 151 | 151 | 125 | 8.9 |
| EFAS whole domain | 13,439,104 | 2,968 | 2,970 | 4,528 | 8.1 |

(the "per row" column is the row-by-row measurement of the same request, section 1 of the sizing
above; the EFAS
shapes and the Volga/Switzerland polygons cover their rows in ascending index order, so the whole-field
sort finds the same ranges.)

The gribjump term is **8.1-8.9 B/value on every grid and shape**, against 65 B/value row by row on
the HEALPix Europe box: the range count does not depend on how the grid numbers its points, so it
does not decide how many fields a call may ask for. `bytes_per_range` (96 B) stays because the term
is exact, but it is 0.1 MB of the 4.0 MB a HEALPix Europe field costs. A box that covers whole
rows is one range (the sort merges adjacent rows), which also halves the O1280 Europe count.

## 2. What one call costs, per shape and per field count

`tools/measure_memory.py calibrate`: one unit of *n* fields on the production path
(`FDBDatacube.get_iter`), the budget and the caps set out of the way so that
the whole request is one call, the peak measured from after the tree is sliced **and prepared**.
`cpp MB` is the exact gribjump term of that call (`n_fields x (8 x points + points/8 + 96 x ranges)`,
no safety factor) and `residual` what the Python terms have to cover.

| run | fields | group fields | sub-trees | points | ranges/field | growth MB | cpp MB | residual MB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| efas_danube_1 | 1 | 1 | 1 | 634,550 | 490 | 20.7 | 5.2 | 15.5 |
| efas_danube_4 | 4 | 1 | 1 | 634,550 | 490 | 40.5 | 20.8 | 19.7 |
| efas_danube_12 | 12 | 1 | 1 | 634,550 | 490 | 80.9 | 62.4 | 18.5 |
| efas_danube_48 | 48 | 1 | 1 | 634,550 | 490 | 266.8 | 249.7 | 17.0 |
| efas_volga_4 | 4 | 4 | 1 | 609,851 | 1,131 | 35.0 | 20.3 | 14.8 |
| efas_volga_12 | 12 | 4 | 1 | 609,851 | 1,131 | 104.4 | 60.8 | 43.6 |
| efas_volga_48 | 48 | 4 | 1 | 609,851 | 1,131 | 412.4 | 243.1 | 169.3 |
| healpix1024_europe_1 | 1 | 1 | 1 | 479,865 | 1,388 | 16.3 | 4.0 | 12.3 |
| healpix1024_europe_4 | 4 | 1 | 4 | 479,865 | 1,388 | 26.1 | 16.1 | 10.0 |
| healpix1024_europe_12 | 12 | 1 | 12 | 479,865 | 1,388 | 52.2 | 48.4 | 3.8 |
| healpix1024_europe_48 | 48 | 1 | 48 | 479,865 | 1,388 | 195.5 | 193.5 | 2.0 |
| o1280_europe_1 | 1 | 1 | 1 | 222,960 | 541 | 10.1 | 1.9 | 8.2 |
| o1280_europe_4 | 4 | 1 | 1 | 222,960 | 541 | 16.3 | 7.5 | 8.9 |
| o1280_europe_12 | 12 | 1 | 1 | 222,960 | 541 | 29.4 | 22.4 | 7.1 |
| o1280_europe_48 | 48 | 1 | 1 | 222,960 | 541 | 93.4 | 89.4 | 3.9 |

Fitting `residual = bytes_per_point_call x (points x sub-trees) + bytes_per_value x group values

- 16 MiB of fragments` over all 15 runs by least squares:

    bytes_per_point_call = -1.4 B/point     bytes_per_value = 21.2 B/value

**The per-call request side costs nothing.** Building a Python `int` per point before fetching
anything costs 50-77 B/point *per spatial sub-tree*; the bulk node's coordinates and indexes are
built once, in `prepare`, and the call only sorts the indexes to get its ranges - a transient the
heap freed by the planning absorbs. The HEALPix rows show it directly: the residual of a 48-field
call over 48 sub-trees (23M request points) is **2.0 MB**, against 1,333 MB when the request side is
built per call.

**Default: `bytes_per_value = 32`,** 1.5x the fitted 21.2; all 15 runs stay below their estimate
(`covered` = yes), the worst margin being 1.16x on the 48-field Volga unit. **There is no
`bytes_per_point_call` term**: the rows above fit it at ~0, and what it was standing in for - the bulk
nodes' own arrays, 24 B/point - is resident for the whole request and priced by `limits.max_tree_bytes`
(section 4 and the section after it), not by the unit. Charging it twice only made units smaller.
The fit is now one unknown (`python tools/measure_memory.py calibrate` reports it as such).

## 3. The planner on the same shapes with whole-field ranges

`python tools/measure_memory.py targets`: the request is sliced, prepared and planned (no data
fetched) and its units replanned at both budgets with the deployed defaults. Points and ranges are
per field; "fields per call" is the largest unit the planner produced. The last column is the same
request with per-row ranges and a 128 B/point request side.

| request | groups x fields | points | ranges/field | 1.5 GiB: fields/call, calls | 1.8 GiB | per-row ranges at 1.5 GiB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| EFAS Volga ensemble, 4 params x 50 members x 60 steps | 3,000 x 4 | 609,851 | 1,131 | **196, 120** (est. 1,584 MB) | **200, 60** | 188, 120 |
| EFAS Switzerland ensemble, 1 param x 50 x 60 | 3,000 x 1 | 18,834 | 151 | **1,000, 3** (est. 269 MB) | **1,000, 3** | 1,000, 3 |
| climate-dt HEALPix-1024 Europe box x 24 hourly | 24 x 1 | 479,865 | 1,388 | **24, 1** (est. 177 MB) | **24, 1** | 14, 2 |

- **The LUMI HEALPix request is a single call** of all 24 hourly fields, estimated at 177 MB
  against the 1,579 MB that per-row ranges estimate for 14 of them. Both terms that bounded it are gone: the
  C++ buffer per field fell from 32.7 MB to 4.0 MB (1,388 ranges instead of 300,315) and the request
  side is not charged to a call at all.
- **Dropping the request-side term makes units larger** on every shape whose fields are large enough
  for it to matter, the HEALPix Europe box most of all. Groups one 1.5 GiB call may hold, at one field
  per group: 258 -> **260** when the groups share a sub-tree (separate date/time axes, which is what the
  deployments send) and 73 -> **260** when every group brings its own (a merged date/time axis). The
  24-hour request needs 24 of them either way, so its call count is unchanged and its estimate falls from
  193 MB (one sub-tree) or 546 MB (24 sub-trees) to **177 MB**. EFAS Danube goes 199 -> 201 fields per
  call, O1280 Europe 565 -> 567, Volga 196 (unchanged: its 4-param groups are bounded by gribjump's
  buffer) and Switzerland 1,000 (bounded by `max_fields_per_call`).
- **Volga** gains little from the budget (196 fields per call against 188 with per-row ranges): it is
  bounded by
  gribjump's buffer for 4 params x 609,851 points, which whole-field ranges barely change (1,131
  ranges either way on a row-ordered grid). The call count is still 120 because coverages come out
  (reference, step, number) and a unit must be a cartesian product, so 49 of the 50 members of a step
  go in one call; 1.8 GiB buys the 50th and halves the calls to 60.
- **Switzerland** is still decided by `max_fields_per_call` (1,024, rounded down to 20 steps x 50
  members by the product rule).

## 4. What the prepared tree costs resident, with the fold off and on

`python tools/measure_memory.py tree`: slice (always with `_merge_union_rows`), then `prepare`, in a fresh
subprocess each.  A bulk node holds `coordinates`
(16 B/point) and `indexes` (8 B/point) for its whole sub-tree, where the row tree held the latitude
nodes and the longitude leaf arrays; `tree MB` is a structural estimate (`getsizeof` of the nodes plus
the arrays' `nbytes`, views counted once), RSS is what the process actually holds.

The `fold off` rows were measured while polytope-feature could still skip the fold of the spatial rows; the
tool now measures the folded tree only, which is the `on` row of each pair.

| request | fold | sub-trees | points | tree MB | tree B/point | RSS after slice | RSS after prepare | peak |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| climate-dt HEALPix-1024 Europe box x 24 hourly | off | 19,128 rows | 11,516,760 | 108.0 | 9.4 | 339 MB | 441 MB | 1,707 MB |
| | **on** | **24 nodes** | 11,516,760 | **276.7** | **24.0** | 339 MB | **658 MB** | **672 MB** |
| climate-dt 2027 polygon, 30 days x 24 hourly | off | 90 rows | 2,520 | 0.1 | 43.7 | 182 MB | 183 MB | 183 MB |
| | **on** | **1 node** | 2,520 | 0.1 | **30.9** | 182 MB | 183 MB | 183 MB |
| the same rectangle as a box, 30 days x 24 hourly | off | 36,000 rows | 1,378,080 | 44.4 | 32.2 | 1,414 MB | 1,442 MB | 1,566 MB |
| | **on** | **720 nodes** | 1,378,080 | **37.6** | **27.3** | 1,414 MB | 1,447 MB | **1,465 MB** |

- **The 24-hour HEALPix request pays 169 MB more resident tree** (108 -> 277 MB: 24 sub-trees of
  479,865 points at 24 B/point instead of 797 row nodes at 9.4 B/point) **and 1,035 MB less peak**
  (1,707 -> 672 MB): preparing the rows built a Python `int` per point per row, which is exactly what
  the fold replaces. `prepare` is also 2.5x faster (31.6 -> 12.6 s).
- **The 8,760-sub-tree shape of `fe-oom-climate-dt-polygon-2027-hourly-year` does not exist.** A
  climate-dt *polygon* request has its date and time axes unmerged (the fe-worker's
  `unmerge_date_time_options`) and both are compressed, so all 8,760 hourly fields hang off **one**
  branch and therefore one bulk node of 2,520 points: 0.1 MB either way, and the fold *halves* the
  per-point cost (43.7 -> 30.9 B/point) because 90 nearly empty row nodes cost more than one node's
  arrays.  One branch per hour is what a *box* of the same rectangle gives instead, since a box keeps
  the merged date/time axis. Measured over 30 days (720 branches, a year does not
  fit this machine: *slicing* 8,760 branches peaks over 5 GB, which is the slicer's own cost and has
  nothing to do with the fold) the fold again **saves** memory (44.4 -> 37.6 MB), and it is the slice,
  not the tree, that dominates such a request: 1.2 GB of RSS for 720 branches of 1,914 points.
- **Recommendation: leave `coordinates` eager.** The growth is material on exactly one shape -- long
  rows repeated over many sub-trees -- and there it is 169 MB against a 1,035 MB fall in the peak. If
  it ever has to come down, the cheap fix is not laziness but **sharing**: the sub-trees of such a
  request are the same spatial selection repeated per datetime (identical `lat_values`, `row_lengths`
  and `indexes`), so `fold_spatial_rows` could keep one set of arrays per distinct row structure and
  let the other sub-trees reference it -- 277 MB -> ~12 MB for the request above, and the per-call sort
  of the ranges would be shared too. Making `coordinates` itself lazy (keeping `indexes` and asking the
  mapper for the latitudes/longitudes when the coordinate block is emitted) saves only 16 of the
  24 B/point and costs a mapper pass per block.

## 5. End to end: `extract_stream` on the fake, output discarded

`python tools/measure_memory.py stream`, one subprocess per run, peak = `max_rss_bytes` of the run
(`ru_maxrss`, the whole process: imports, the sliced and prepared tree, the call, the encoder).

| request | budget | values | calls (fields each) | estimated unit | peak RSS | growth | output | wall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| climate-dt HEALPix-1024 Europe box x 24 hourly | 1.5 GiB | 11,516,760 | **1** (24) | 177 MB | **803 MB** | 616 MB | 601.6 MiB | 49 s |
| HEALPix-1024 whole world, one field | 1.5 GiB | 12,582,912 | **1** (1) | 573 MB | **1,242 MB** | 1,055 MB | 655.5 MiB | 39 s |
| EFAS whole domain, one field | 1.5 GiB | 13,439,104 | **1** (1) | 611 MB | **1,192 MB** | 1,005 MB | 704.7 MiB | 81 s |
| EFAS Danube box x 40 steps | 1 GiB | 25,382,000 | **1** (40) | 349 MB | 466 MB | 279 MB | 1,347.7 MiB | 8 s |
| EFAS Danube box x 10 steps | 200 MB | 6,345,500 | 1 (10) | 115 MB | 311 MB | 124 MB | 337.2 MiB | 5 s |
| EFAS Danube box x 10 steps | none | 6,345,500 | 10 (1) | 45 MB | 273 MB | 86 MB | 337.2 MiB | 5 s |
| EFAS Danube box x 10 steps | 20 MB | - | **refused** | 45 MB | - | - | - | - |

(The peak RSS, growth, output and wall columns are as measured; the estimates are the planner's and
are recomputed here without the request-side term, which is what the measurements above showed to be
zero. The call pattern of every row is unchanged by that: the shapes that fit one call still do.)

- **The LUMI request that was OOM-killed runs in one call at 803 MB** against 1,790 MB and 511 s
  with per-row ranges and a per-call request side (2 calls of 14 and 10 fields), in a 3 GiB pod with
  a 1.5 GiB budget. Most of the wall time
  is the slice (33 s) and `prepare` (13 s); the `get` of all 24 fields is 2.1 s against 237 s.
- **The two largest single fields of the corpus are served whole**, 1,242 MB and 1,192 MB of peak
  against a 1.5 GiB budget in a 3 GiB pod -- which is what lets a field be extracted whole. Both are
  one gribjump call of one field (1 and 2,968 index ranges).
- **A budget that cannot hold one field refuses the request** instead of banding it: 40 MB against the
  634,550-point Danube field raises `One field of this request covers 634550 grid points and needs
  about 45 MB to extract, more than the memory budget of 40000000 bytes` before any call (with
  `--tree-bytes 30000000`, because at that budget the tree guard would answer first: the tree of that
  field is 15 MB measured, 25 MB estimated, against half of 40 MB). At 20 MB the tree guard is the one
  that answers.
- **Output bytes do not depend on the call pattern**: 337.2 MiB for the Danube x 10 request at one
  call per group, at one call for all ten, and 337 MiB when the same request was served in latitude
  bands. Byte identity itself is pinned by the golden corpus (28 cases, both missing-field reporting
  modes).

# Separate date/time axes, and the tree guard

## 1. What a merged date/time axis costs: the HEALPix Europe x 24 hourly request

polytope-feature never compresses a merged axis (`datacube.py`: "do not compress merged axes"), so a
climate-dt request whose `date`/`time` axis is merged gets one branch, one spatial sub-tree and one
slice per datetime, while the same request with `date` and `time` as separate compressed axes gets
one of each in total. The same request measured both ways, `python tools/measure_memory.py --run
tree_healpix1024_europe_24h_fold_on` and `--run stream_healpix1024_europe_24fields_1_5GiB`
(climate-dt HEALPix-1024, Europe box, 24 hourly fields of 479,865 points; the fe-worker un-merges the
axes for every feature type of these datasets):

| date/time axes | sub-trees | points in the tree | `slice` | `prepare` | prepared tree | peak RSS |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| merged | **24** | 11,516,760 | **35.5 s** | 14.1 s | **276.7 MB** | **672 MB** |
| separate | **1** | 479,865 | **1.5 s** | 0.6 s | **11.5 MB** | **219 MB** |

End to end through `extract_stream` at a 1.5 GiB budget, output discarded (identical bytes, 601.6 MiB
either way):

| date/time axes | calls (fields) | estimated unit | peak RSS | `slice` | `prepare` | `get` | wall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| merged | 1 (24) | 546 MB | **803 MB** | 35.5 s | 14.1 s | 2.2 s | **52 s** |
| separate | 1 (24) | 193 MB | **346 MB** | 1.5 s | 0.6 s | 2.2 s | **4.2 s** |

- **24x the tree for the same data**: 24 copies of the same spatial selection at 24 B/point. The
  extraction itself is unchanged (one call, 24 fields, the same 1,388 index ranges, `get` 2.2 s both
  ways): everything saved is slice time and resident tree.
- **The slice is the cost that scales**, not the fetch: 35.5 s for 24 branches against 1.5 s for one,
  and it is linear in the branches. "Europe hourly for a month" (720 branches) is ~18 min of slicing
  and an 8.1 GB tree; a year is 8,760 branches.
- Wall time is not the goal of this work, but 52 s -> 4.2 s on a request the BOBS writer times out
  of at 300 s is worth recording.

## 2. What the tree guard refuses

`limits.max_tree_bytes` (default: half of `memory_budget_bytes`, so 800 MB in a 3 GiB pod) against
`limits.estimate_tree_bytes` = branches x points per field x `bytes_per_point_tree` (40):

| request (healpix_1024) | branches | points/field | estimated tree | 24 B/point | verdict at 800 MB |
| --- | ---: | ---: | ---: | ---: | --- |
| Europe box, 1 datetime | 1 | 466,409 | 19 MB | 11 MB | served |
| Europe box x 24 hourly | 24 | 466,409 | 448 MB | 269 MB | served (803 MB peak, above) |
| Europe box, hourly month | **720** | 466,409 | **13 GB** | 8.1 GB | **refused before slicing** |
| 2027 polygon, hourly year | 1 | 2,520 | 101 kB | 60 kB | served (date/time un-merged) |
| HEALPix whole world, 1 field | 1 | NaN | unknown | 302 MB | served (exact check: 302 MB) |

- The estimate is **1.7x the 24 B/point the prepared tree actually holds** (40 B/point against 24):
  the slicer's row leaves are built before the fold and are resident with it (9.4 B/point measured on
  this shape above, 27-44 B/point on shapes with short rows), so the constant covers the peak
  the tree walks through, not its steady state. The exact post-prepare check (`timings["tree_bytes"]`,
  `coordinates.nbytes + indexes.nbytes` over the bulk nodes) is what bounds the steady state.
- **A pole-to-pole box has no estimate at all**: `get_boundingbox_area` returns NaN for
  `[[90, -180], [-90, 180]]`, so the pre-slice guard opts out and the exact check does the work (the
  whole-world HEALPix field's tree is 12,582,912 x 24 B = 302 MB, under the 800 MB limit, and the
  request is served, at the 1,242 MB of peak measured above).

# Serving the result as tensogram

`python tools/measure_memory.py stream`, one subprocess per run, the same two requests through
`format: covjson` and `format: tensogram`. Peak = `max_rss_bytes` of the run (`ru_maxrss`, the whole
process); "fragments" is what `extract_stream` yielded, which for tensogram is one complete message
each; "largest" is the largest of them.

| request | budget | format | fragments | largest | peak RSS | growth | output |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| climate-dt HEALPix-1024 Europe box x 24 hourly | 1.5 GiB | covjson | 242 | 5.43 MiB | 346.1 MB | 158.9 MB | 601.6 MiB |
| climate-dt HEALPix-1024 Europe box x 24 hourly | 1.5 GiB | **tensogram** | 50 | 2.20 MiB | **352.5 MB** | 165.4 MB | **78.4 MiB** |
| EFAS Danube box x 10 steps | 200 MB | covjson | 112 | 5.45 MiB | 311.2 MB | 123.9 MB | 337.2 MiB |
| EFAS Danube box x 10 steps | 200 MB | **tensogram** | 32 | 1.22 MiB | **302.2 MB** | 115.2 MB | **11.2 MiB** |

- **The peak is bounded the same way**: within 2% of the CovJSON run either way (+1.8% on the HEALPix
  request, -2.9% on the Danube one). Both encoders are charged the same `fragment_bytes` term of the
  unit sizing (2 x 8 MiB), the extraction plans the same units (`estimated_unit_mb` 192.6 and 135.4,
  1 call each), and neither encoder holds more than one fragment: for tensogram that is the message
  being assembled, whose raw payload `max_fragment_bytes` bounds.
- **A coverage becomes two or three messages at the deployed field sizes.** The HEALPix coverage is
  479,865 points: `latitude` and `longitude` fit one message (7.7 MB of the 8 MiB bound) and the
  values follow in a second, so 24 coverages give 48 messages plus the header and the trailer. The
  Danube coverage is 634,550 points, where each tensor is 5.1 MB and no two fit together: three
  messages per coverage, 32 for the request. Smaller coverages -- everything up to ~350,000 points
  for a single-parameter request -- are one message each.
- **Output is 7.7x and 30x smaller than CovJSON**, which is the format doing its job: float64 values
  as 8 bytes under zstd instead of ~17 characters of JSON text, and the coordinates once per
  coverage instead of once per composite tuple. The Danube ratio is the larger one because its
  values repeat more (one parameter over ten steps on the same grid points).
- **Encoding is cheaper**: `encode_ms` 902 against 1,497 on the HEALPix request and 218 against 833
  on the Danube one. Not a target -- wall time is not what these limits are for -- but it means
  tensogram costs nothing to adopt on the producer side.
