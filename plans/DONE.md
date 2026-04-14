# Polytope-Mars — Current Implementation Status (v0.3.9)

> For planned features, see `TODO.md`.

## Summary

- **Version:** 0.3.9
- **Language:** Python
- **Package:** `polytope_mars` (PyPI: `polytope-mars`)
- **Features:** 9 feature types implemented
- **Output format:** CoverageJSON via covjsonkit
- **Datacube backend:** GribJump (GRIB data in ECMWF FDB)
- **CI:** GitHub Actions (QA + tests + PyPI deploy on release)

## API (api.py)

- `PolytopeMars(config, log_context)` — main entry point
- `extract(request)` — full pipeline: parse, validate, build shapes, retrieve, encode CoverageJSON
- `retrieve_data(request, feature_type, feature)` — datacube retrieval and encoding
- `_create_base_shapes(request, feature_type)` — MARS field to polytope shape translation
- `_feature_factory(feature_name, feature_config, config)` — factory dispatch
- Request splitting for large polygon/bounding box requests (by date and ensemble number)
- Support for both standard forecasts and Climate-DT / class "ng" datasets
- Parameter shortname to numeric ID resolution via covjsonkit param_db

## Feature Implementations (features/)

| Feature | File | Geometry | Shapes Used | CoverageJSON Type |
|---------|------|----------|-------------|-------------------|
| Time Series | `timeseries.py` | Point(s) + time axis | Union of Points | PointSeries |
| Vertical Profile | `verticalprofile.py` | Point(s) + level axis | Union of Points | VerticalProfile |
| Bounding Box | `boundingbox.py` | Two corners (2D or 3D) | Union of Boxes | MultiPoint |
| Polygon | `polygon.py` | Closed polygon shape(s) | Union of Polygons | MultiPoint |
| Circle | `circle.py` | Center + radius | Disk | MultiPoint |
| Frame | `frame.py` | Outer box minus inner box | Union of 4 Boxes | MultiPoint |
| Trajectory | `path.py` | Path of 2D/3D/4D points | Path with Disk/Ellipsoid/Box inflation | Trajectory |
| Position | `position.py` | Point(s), no time axis | Union of Points | PointSeries |
| Shapefile | `shpfile.py` | Polygons from .shp file | Union of Polygons | MultiPoint |

## Feature Abstraction (feature.py)

- Abstract `Feature` base class with `get_shapes()`, `parse()`, `validate()`, `split_request()`
- Validation framework: `required_keys()`, `required_axes()`, `incompatible_keys()`
- Split logic for large spatial requests (polygon, bounding box) based on area limits

## Configuration (config.py)

- `PolytopeMarsConfig` — top-level config with 4 sub-models:
  - `DatacubeConfig` — backend type, config file, URI
  - `Config` (from polytope_feature) — axis transformations, grid mappings, compressed axes
  - `CovjsonKitConfig` — parameter database selection
  - `PolygonRulesConfig` — max_points, max_area limits
- Conflator-based config hierarchy (system, user, runtime)

## Utilities

### Area Calculations (utils/areas.py)
- `haversine_distance()` — great-circle distance between two points
- `get_circle_area()` / `get_circle_area_from_coords()` — circle area on Earth's surface
- `get_polygon_area()` — geodesic polygon area via WGS84 with meridian splitting
- `get_boundingbox_area()` — bounding box area via polygon area
- `split_polygon()` — splits polygons at 90 degree meridians for accurate area calculation
- `field_area()` — multiplicative cost estimate (params * steps * numbers * dates * ... * shape_area)
- `request_cost()` — full request cost estimation

### Datetime Utilities (utils/datetimes.py)
- `days_between_dates()` / `hours_between_times()` — duration calculations
- `convert_timestamp()` — normalise time strings to HH:MM:SS
- `find_step_intervals()` — expand sub-hourly step ranges (e.g., `1h/to/6h/by/30m`)
- `from_range_to_list_date()` / `from_range_to_list_num()` — MARS range expansion
- `count_steps()` — count steps in MARS step strings (lists, ranges, sub-hourly)

## Tests

- `tests/test_time_series.py` — time series feature (parsing, validation, integration)
- `tests/test_vertical_profile.py` — vertical profile feature
- `tests/test_bounding_box.py` / `test_bounding_box_3d.py` — bounding box feature
- `tests/test_polygon.py` — polygon feature
- `tests/test_circle.py` — circle feature
- `tests/test_frame.py` — frame feature
- `tests/test_path.py` / `test_trajectory.py` — trajectory feature
- `tests/test_position.py` — position feature
- `tests/test_shapefile.py` / `test_wkt.py` — shapefile feature
- `tests/test_costing.py` — cost estimation
- `tests/test_datetimes.py` — datetime utilities
- `tests/test_step_counter.py` — step counting logic
- `tests/test_pass.py` — placeholder (passes trivially)
- `tests/climate-dt/` — climate-dt specific tests
- `tests/extremes-dt/` — extremes-dt specific tests
- `tests/performance/` — performance tests

## CI / Build

- GitHub Actions: QA (black, isort, flake8) then pytest then coverage then PyPI deploy on release
- Pre-commit hooks: trailing whitespace, EOF fixer, YAML check, large files, isort, black, flake8
- Code style: black (120 char lines), isort (black profile), flake8 (E501 ignored)

## Examples

- `examples/time_series_example.ipynb` — time series feature demo
- `examples/vertical_profile_example.ipynb` — vertical profile feature demo
- `examples/bounding_box_example.ipynb` — bounding box feature demo

## Documentation

- `docs/user_guide/timeseries.md` — time series user guide
- `docs/user_guide/vertical_profile.md` — vertical profile user guide
- `docs/user_guide/boundingbox.md` — bounding box user guide
- `docs/user_guide/trajectory.md` — trajectory user guide
- `docs/user_guide/polygon.md` — polygon user guide
- `docs/user_guide/guide.md` — user guide index
- `docs/design/feature_docs.md` — feature keyword design documentation
