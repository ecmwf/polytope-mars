# Phase 0 measurements (legacy pipeline)

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

## 2. `bytes_per_point` of a bare `datacube.get` (DESIGN §2.7)

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
