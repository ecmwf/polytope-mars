# Features Decided to Implement

Accepted features that are planned but not yet implemented.
Code agents are encouraged to ask questions to get the design correct, seeking clarifications and sorting out ambiguities.

## Code Quality

- [ ] **remove-debug-print**: Remove `print(result.pprint())` from `api.py:retrieve_data()` — this is debug output left in production code. Replace with `logging.debug()`.

- [ ] **fix-bare-excepts**: Replace bare `except:` clauses in `api.py:_create_base_shapes()` (param ID resolution) with specific exception types (e.g., `except ValueError`).

- [ ] **deduplicate-base-shapes**: The `_create_base_shapes()` method has two near-identical code paths for climate-dt/class "ng" vs standard forecasts. Refactor to extract shared logic and reduce duplication.

- [ ] **complete-feature-interfaces**: `Frame` and `Shapefile` features are missing `required_keys()` and `required_axes()` methods. Add proper implementations.

## Validation

- [ ] **enable-area-validation**: Several area validation checks in `polygon.py` and `boundingbox.py` are commented out. Decide on area limits and re-enable with proper error messages, or remove the dead code.

- [ ] **shapefile-validation**: The `Shapefile` feature has no validation in `parse()` — it returns the request unchanged. Add validation for file existence, geometry types, and size limits.

- [ ] **circle-3d-validation**: The `Circle` feature accepts 3D centers but the area calculation only uses 2D coordinates. Validate or reject 3D circle requests properly.

## Testing

- [ ] **unit-test-coverage**: Most tests require a live FDB/GribJump server (integration tests). Add pure unit tests for:
  - Feature validation logic (required keys, incompatible keys, axes)
  - Request parsing (range expansion, axis handling)
  - Area calculations (polygon, bounding box, circle, field_area)
  - Datetime utilities (all functions in utils/datetimes.py)
  - Error paths (invalid feature type, missing keys, overspecified axes)

- [ ] **mark-data-tests**: Ensure all integration tests that require data infrastructure are consistently marked with `@pytest.mark.data`.

- [ ] **test-pass-cleanup**: `test_pass.py` is a placeholder test that asserts True. Replace with meaningful basic tests or remove.

## Documentation

- [ ] **frame-user-guide**: The Frame feature is listed in README but has no user guide in docs/user_guide/. Create `docs/user_guide/frame.md`.

- [ ] **circle-user-guide**: The Circle feature has no user guide. Create `docs/user_guide/circle.md`.

- [ ] **position-user-guide**: The Position feature has no user guide. Create `docs/user_guide/position.md`.

- [ ] **shapefile-user-guide**: The Shapefile feature has no user guide. Create `docs/user_guide/shapefile.md`.

- [ ] **update-feature-docs**: `docs/design/feature_docs.md` references `axis` keyword which has been replaced by `time_axis` and `axes` in the current code. Update to match current API.

## Features

- [ ] **additional-datacube-backends**: Currently only GribJump is supported. The config allows `datacube.type` to be set but anything other than "gribjump" raises NotImplementedError. Consider adding support for other backends.

- [ ] **request-cost-api**: Expose `request_cost()` from `utils/areas.py` as a public API method so users can estimate cost before submitting a request.

- [ ] **better-error-messages**: Several error messages reference the wrong feature name (e.g., Position's error says "timeseries"). Audit all error messages for accuracy.
