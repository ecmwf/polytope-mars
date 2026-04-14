# Improve Edge Case Handling

Perform a systematic edge case audit across the codebase.

## What to Look For

### Request Edge Cases
- Empty or missing request fields: no `param`, no `date`, no `step`
- Single-value vs range vs list: `"1"` vs `"1/to/10"` vs `"1/2/3"`
- Range with `by` equal to 0 or negative values
- The `ALL` keyword for various axes
- Parameter names vs numeric IDs — mixed in the same request
- Negative date offsets (e.g. `"-1"` for yesterday)

### Feature Geometry Edge Cases
- Empty points list: `"points": []`
- Single-point polygons or two-point polygons (degenerate shapes)
- Polygons crossing the antimeridian (180° longitude)
- Bounding box with inverted corners (min > max)
- Circle with zero radius
- Trajectory with only one point
- Shapefile with no geometries, or multi-polygon features
- Points at exactly the poles (lat=90, lat=-90) or dateline (lon=180)

### Data Edge Cases
- All-None leaf results from polytope (no data available)
- Very large number of points (N > 100000)
- Very many ensemble members (number = 1/to/50)
- Very many steps (step = 0/to/360 with hourly data)
- Mixed levtype requests

### Configuration Edge Cases
- Missing config file — Conflator fallback behavior
- Empty config dict
- `max_area = inf` (default) vs very small limits
- `max_points = 0`

## Process

1. Scan each module and identify unhandled or under-tested edge cases
2. For ambiguous behavior, ask the user to clarify the intended semantics
3. Add handling code for each edge case (fail gracefully with clear errors, not silently)
4. Write tests for each new edge case
5. Document all edge case behavior in docs/
6. Run full test suite to verify no regressions:
   ```bash
   python -m pytest -m "not data" tests/ -v
   ```
7. Summarize findings and changes
