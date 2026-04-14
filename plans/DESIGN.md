# Design: Polytope-Mars — High-Level Meteorological Feature Extraction API

Repo: ecmwf/polytope-mars

> For **why** polytope-mars exists and what problem it solves, see `MOTIVATION.md`.
> For the **current implementation status**, see `DONE.md`.
> For **planned features**, see `TODO.md`.

## Design Premises

1. **MARS-like request syntax** — requests use the same key/value structure as ECMWF MARS requests (class, stream, type, date, time, param, step, number, levelist, etc.) with slash-separated values and range syntax (`a/to/b/by/c`). This minimises the learning curve for existing MARS users.

2. **Feature as a first-class concept** — each request contains a `feature` dictionary that declares extraction type and geometry. The feature keyword is the only addition to the standard MARS vocabulary. Feature type determines what shapes are built, what axes are required, and what CoverageJSON output type is produced.

3. **Separation of concerns** — three independent layers collaborate:
   - **polytope-mars** (this library): request parsing, feature logic, shape composition, validation
   - **polytope-python**: low-level geometric feature extraction from datacubes
   - **covjsonkit**: encoding extraction results into CoverageJSON

4. **Factory pattern for features** — each feature type is a concrete class implementing the abstract `Feature` interface. The API dispatches via a name-to-class registry. Adding a new feature type means adding one file in `features/` and one entry in the registry.

5. **Configuration hierarchy** — system-wide (`/etc/polytope_mars/config.json`), user-level (`~/.polytope_mars.json`), and runtime dictionary configs are merged via [Conflator](https://github.com/ecmwf/conflator). Configuration covers datacube backend, polytope options (axis transformations, grid mappings), CoverageJSON settings, and polygon size rules.

## Architecture

```
User Request (dict or JSON)
|
+-- request["feature"] --> Feature Factory --> concrete Feature instance
|                          +-- TimeSeries
|                          +-- VerticalProfile
|                          +-- BoundingBox
|                          +-- Polygon
|                          +-- Circle
|                          +-- Frame
|                          +-- Path (Trajectory)
|                          +-- Position
|                          +-- Shapefile
|
+-- feature.validate(request, feature_config)
|     +-- checks required_keys, required_axes, incompatible_keys
|
+-- feature.parse(request, feature_config)
|     +-- merges range into request, validates axes, checks area limits
|
+-- _create_base_shapes(request)
|     +-- translates MARS fields --> polytope shapes (Select, Span, All)
|
+-- feature.get_shapes()
|     +-- translates geometry --> polytope shapes (Point, Box, Polygon, Disk, Path)
|
+-- Polytope(datacube=GribJump, options=config).retrieve(Request(*shapes))
|     +-- executes geometric extraction against the datacube
|
+-- Covjsonkit(config).encode("CoverageCollection", feature_type).from_polytope(result)
      +-- encodes result into CoverageJSON
```

### Module Structure

| Module | Purpose |
|--------|---------|
| `polytope_mars/api.py` | `PolytopeMars` class — entry point, orchestrates the full pipeline |
| `polytope_mars/config.py` | Pydantic configuration models (datacube, options, coverage, polygon rules) |
| `polytope_mars/feature.py` | Abstract `Feature` base class with validation and split logic |
| `polytope_mars/features/*.py` | 9 concrete feature implementations |
| `polytope_mars/utils/areas.py` | Geodesic area calculations, request cost estimation |
| `polytope_mars/utils/datetimes.py` | Date/time parsing, MARS range expansion, step counting |

### Feature Interface

Every feature implements:

| Method | Purpose |
|--------|---------|
| `__init__(feature_config, client_config)` | Parse feature-specific config, store geometry |
| `get_shapes() -> List[Shape]` | Translate geometry into polytope shapes |
| `parse(request, feature_config) -> request` | Validate and transform the request |
| `validate(request, feature_config)` | Check required/incompatible keys (inherited) |
| `split_request() -> bool` | Whether the request should be split for cost control |
| `name() -> str` | Human-readable feature name |
| `coverage_type() -> str` | CoverageJSON coverage type |
| `required_keys() -> List[str]` | Keys that must be present |
| `required_axes() -> List[str]` | Axes that must be present |
| `incompatible_keys() -> List[str]` | Keys that must NOT be present |

## Key Design Decisions

### MARS Range Syntax to Polytope Shapes

MARS uses slash-separated values with keywords:

| MARS Syntax | Polytope Shape |
|-------------|---------------|
| `"167"` (single value) | `Select("param", ["167"])` |
| `"1/2/3"` (list) | `Select("number", ["1", "2", "3"])` |
| `"0/to/360"` (range) | `Span("step", lower="0", upper="360")` |
| `"0/to/360/by/6"` (range with step) | `Select("step", [0, 6, 12, ...])` |
| `"ALL"` | `All(axis_name)` |

Date and time values receive special treatment — dates are converted to `pd.Timestamp`, times merged with dates where needed.

### Climate-DT / Class "ng" Branching

The `_create_base_shapes` method has two code paths:
- **Climate-DT / class "ng"**: Date and time axes are handled independently (no date+time merging), because the polytope options for these datasets use different axis configurations.
- **Standard forecasts**: Date and time are merged (e.g., `20231205T0000`), matching the `merge` transformation in polytope options.

### Request Splitting

For large spatial requests (polygons, bounding boxes) that exceed configured area limits, the request is automatically split by date and optionally by ensemble number. Results from sub-requests are merged via `covjsonkit.merge_coverage_collections()`.

### Cost Estimation

`field_area(request, shape_area)` computes a heuristic cost:

```
cost = params * steps * numbers * dates * times * months * years * levels * shape_area
```

This multiplicative estimate is compared against `polygonrules.max_area` to reject excessively large requests before they reach the datacube.

### Parameter ID Resolution

When parameter values are given as shortnames (e.g., `"tp"`, `"2t"`) instead of numeric IDs, they are resolved to numeric IDs via `covjsonkit.param_db.get_param_ids()` using the configured parameter database (default: ECMWF).

## Dependencies

| Package | Purpose |
|---------|---------|
| `polytope-python` | Low-level feature extraction engine (shapes, datacube interface) |
| `covjsonkit` | CoverageJSON encoding and parameter database |
| `pygribjump` | GribJump datacube backend for GRIB data in FDB |
| `conflator` | Configuration management (system/user/runtime merging) |
| `shapely` | Geometric operations (polygon splitting at meridians) |
| `geopandas` | Shapefile reading |
| `geographiclib` | Geodesic area calculations (WGS84 ellipsoid) |
| `pyproj` | Coordinate system operations |
| `xarray` | Data array support |
| `pandas` | Timestamp handling, date range generation |

## Testing Strategy

- **Unit tests**: Feature validation, parsing, area calculations, datetime utilities — no data dependency
- **Integration tests** (marked `data`): Full pipeline tests requiring a local FDB or GribJump server
- **CI**: QA (black, isort, flake8) then unit tests then coverage upload to Codecov
- **Pytest markers**: `data` marker for tests requiring external data infrastructure
