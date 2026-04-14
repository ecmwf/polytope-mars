# Plan: Tensogram Output Format for polytope-mars

## Overview

Extend `polytope_mars` so that when a request contains `format=tensogram`, the result is returned as tensogram messages instead of CoverageJSON. The integration follows the same tree-walking pattern as covjsonkit but builds tensogram binary messages with columnar data objects and MARS metadata.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Dependency | **Optional** — lazy `import tensogram` with clear error if missing | Don't force all users to install tensogram |
| Return type | **`TensogramResult` wrapper** — `.messages` list, `.to_bytes()`, `.to_file(path)` | Flexible: iterate messages, write to file, or get raw bytes |
| Message grouping | **One message per coverage** — matches CovJSON semantics | Each message is self-contained with its own MARS metadata |
| Param DB | **Import from covjsonkit** (existing dep) | Reuse existing param name/unit/description resolution |
| Time representation | **Steps as numeric data objects + ISO 8601 strings in `_extra_["time_values"]`** | Numeric data for computation, human-readable strings for reference |

## Tensogram Message Structure

Each message (= one coverage) contains coordinate data objects and parameter data objects in a columnar layout, with MARS metadata in the message-level `_extra_` and per-object metadata in `base` entries.

### Metadata Layout

```python
{
    "version": 2,
    "_extra_": {
        "source": "polytope-mars",
        "feature_type": "timeseries",         # original feature type
        "domain_type": "PointSeries",          # CovJSON domain type equivalent
        "mars": {                              # shared MARS keys (= mars:metadata in CovJSON)
            "class": "od", "stream": "enfo", "type": "pf",
            "expver": "0001", "levtype": "sfc", "domain": "g",
            "number": 1,
            "Forecast date": "20240101T000000Z",
            "levelist": 0,
        },
        "time_values": [                       # ISO strings for human readability
            "2024-01-01T00:00:00Z",
            "2024-01-01T01:00:00Z",
        ],
    },
    "base": [
        {"name": "latitude",  "role": "coordinate", "units": "degrees_north"},
        {"name": "longitude", "role": "coordinate", "units": "degrees_east"},
        {"name": "step",      "role": "coordinate"},
        {"name": "2t",  "role": "data", "mars": {"param": "167"}, "units": "K",
         "description": "2 metre temperature"},
        {"name": "10u", "role": "data", "mars": {"param": "165"}, "units": "m s**-1",
         "description": "10 metre U wind component"},
    ],
}
```

### Data Objects (columnar, one per coordinate axis + one per parameter)

| Object index | Name | Shape | dtype | Content |
|---|---|---|---|---|
| 0 | `latitude` | `[1]` or `[N]` | float64 | Latitude coordinate(s) |
| 1 | `longitude` | `[1]` or `[N]` | float64 | Longitude coordinate(s) |
| 2 | *axis* | `[T]`, `[L]`, or `[N]` | float64/int32 | Time steps, levels, or per-point axis |
| 3..P+2 | *param shortname* | same shape as axis | float64 | One data object per parameter |

### Per Feature Type

| Feature | Domain Type | Coverage = | Coord objects | Data shape |
|---------|------------|------------|---------------|------------|
| **TimeSeries** | PointSeries | (point, date, level, number) | lat[1], lon[1], step[T] | [T] per param |
| **Position** | PointSeries | (point, date, level, number) | lat[1], lon[1] | [1] per param |
| **VerticalProfile** | VerticalProfile | (point, date, number, step) | lat[1], lon[1], levelist[L] | [L] per param |
| **BoundingBox** | MultiPoint | (date, number, step) | lat[N], lon[N], levelist[N] | [N] per param |
| **Polygon** | MultiPoint | (date, number, step) | lat[N], lon[N], levelist[N] | [N] per param |
| **Circle** | MultiPoint | (date, number, step) | lat[N], lon[N], levelist[N] | [N] per param |
| **Frame** | MultiPoint | (date, number, step) | lat[N], lon[N], levelist[N] | [N] per param |
| **Trajectory** | Trajectory | (date, number) | lat[N], lon[N], step[N], levelist[N] | [N] per param |

## Files to Create / Modify

### New Files

| File | Purpose | Est. lines |
|------|---------|-----------|
| `polytope_mars/encoders/__init__.py` | Encoder package init | ~5 |
| `polytope_mars/encoders/tensogram_encoder.py` | `TensogramResult` + `TensogramEncoder` classes | ~450-550 |
| `tests/test_tensogram_encoder.py` | Unit tests (no FDB/data dependency) | ~250-350 |

### Modified Files

| File | Changes |
|------|---------|
| `polytope_mars/api.py` | Accept `format=tensogram`, branch `retrieve_data()`, handle tensogram merging |
| `plans/TODO.md` | Add tensogram backlog item |
| `plans/DONE.md` | Update when complete |

## Implementation Details

### `TensogramResult` class

```python
class TensogramResult:
    """Wrapper for tensogram-encoded polytope-mars results."""

    def __init__(self):
        self._messages = []

    @property
    def messages(self) -> list:
        return list(self._messages)

    def add_message(self, message: bytes):
        self._messages.append(message)

    def to_bytes(self) -> bytes:
        return b"".join(self._messages)

    def to_file(self, path: str):
        with open(path, "wb") as f:
            for msg in self._messages:
                f.write(msg)

    def merge(self, other: "TensogramResult"):
        self._messages.extend(other._messages)

    def __len__(self):
        return len(self._messages)

    def __iter__(self):
        return iter(self._messages)
```

### `TensogramEncoder` internal structure

```
TensogramEncoder
├── __init__(coverageconfig, feature_type)
├── _import_tensogram()                  # lazy import with clear error
├── _resolve_param(param_id)             # -> (shortname, units, description)
│
├── from_polytope(result)                # standard date+step walker
├── from_polytope_step(result)           # climate-dt step-as-time walker
├── from_polytope_month(result)          # monthly mean walker
│
├── walk_tree(tree, fields, coords,      # adapted from covjsonkit
│             mars_metadata, range_dict)
├── walk_tree_step(...)
├── walk_tree_month(...)
│
├── _build_messages_pointseries(...)     # TimeSeries, Position
├── _build_messages_multipoint(...)      # BoundingBox, Polygon, Circle, Frame
├── _build_messages_verticalprofile(...) # VerticalProfile
├── _build_messages_trajectory(...)      # Trajectory
│
├── _encode_message(mars_meta,           # -> bytes via tensogram.encode()
│                   coord_arrays,
│                   data_arrays,
│                   param_info)
└── _build_metadata_dict(...)            # -> metadata dict for tensogram.encode()
```

### Changes to `api.py`

1. **Format validation** (replace lines ~79-84):
   - Accept `"covjson"` (default) and `"tensogram"`
   - Store as `self.format`

2. **In `extract()`**:
   - Initialise `self.coverage` as `TensogramResult()` when format is tensogram
   - Use `self.coverage.merge(coverage)` instead of `merge_coverage_collections()` for split requests

3. **In `retrieve_data()`**:
   - Branch on `self.format`:
     - `"tensogram"` -> `TensogramEncoder` (lazy import)
     - `"covjson"` -> existing `Covjsonkit` path (unchanged)
   - Same dataset/class routing logic for walker variant selection

## Data Flow

```
User Request {format: "tensogram", feature: {type: "timeseries", ...}, ...}
    |
    v
api.py: extract() -- pops format="tensogram", stores self.format
    |
    v
feature.parse() + feature.get_shapes() -- same as today
    |
    v
Polytope.retrieve(Request(*shapes)) -- same as today
    |
    v
TensorIndexTree result
    |
    +-- format == "covjson"  -> Covjsonkit path (unchanged)
    |
    +-- format == "tensogram" -> TensogramEncoder
          |
          +-- walk_tree(result) -> fields, coords, mars_metadata, range_dict
          |
          +-- resolve param IDs -> shortnames, units via covjsonkit.param_db
          |
          +-- for each coverage grouping:
          |     +-- build numpy coordinate arrays (lat, lon, step/level)
          |     +-- build numpy data arrays (one per param)
          |     +-- build metadata dict (_extra_["mars"], base[i])
          |     +-- tensogram.encode(metadata, descriptors_and_data)
          |     +-- result.add_message(message_bytes)
          |
          +-- return TensogramResult
```

## Test Plan

| Test | Data needed | What it verifies |
|------|-------------|-----------------|
| `test_tensogram_result_basic` | None | TensogramResult: add, len, iter, to_bytes |
| `test_tensogram_result_merge` | None | TensogramResult.merge() |
| `test_tensogram_result_to_file` | None (tmpdir) | TensogramResult.to_file() writes bytes |
| `test_format_validation` | None | api.py rejects invalid format, accepts covjson/tensogram |
| `test_metadata_structure_pointseries` | Mock tree | Correct _extra_, base entries, roles |
| `test_metadata_structure_multipoint` | Mock tree | Correct grouping for BoundingBox |
| `test_coordinate_arrays_shape` | Mock tree | lat/lon/step shapes match expected |
| `test_data_arrays_shape` | Mock tree | param arrays shape matches step/point count |
| `test_mars_metadata_injected` | Mock tree | MARS keys present in _extra_["mars"] |
| `test_param_resolution` | None | Param ID -> shortname/unit/description |
| `test_encode_decode_roundtrip` | Mock tree + tensogram | Encode -> decode -> verify data integrity |
| `test_multipoint_n_points` | Mock tree | N points correctly in lat/lon/data arrays |
| `test_missing_tensogram_import` | None | Clear ImportError when tensogram not installed |

## Verification Strategy

1. **Unit tests** — all the above, runnable without FDB data
2. **Manual integration test** — if FDB available, run a real request with `format=tensogram`, decode with `tensogram.decode()`, verify metadata and data match equivalent CovJSON output
3. **Round-trip check** — encode with polytope-mars, decode with tensogram, compare param values against CovJSON range values (should be identical floats)
