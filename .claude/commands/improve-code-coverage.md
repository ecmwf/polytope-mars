# Improve Code Coverage

Perform a comprehensive code coverage analysis and fill gaps to reach 95%+ coverage.

## Process

### 1. Measure Current Coverage

```bash
python -m pytest -m "not data" tests/ --cov=polytope_mars --cov-report=term-missing -v
```

Note: tests marked `data` require a local FDB or GribJump server and are excluded.
Focus coverage on code paths testable WITHOUT external data infrastructure.

### 2. Identify Gaps

For each file below 95% coverage:
- Read the source file to understand what code paths are untested
- Categorize each gap as:
  - **(a) Needs new tests** — testable code paths with no coverage
  - **(b) Error handling** — defensive paths that can be triggered with mock inputs
  - **(c) Dead code** — unreachable code that should be removed
  - **(d) Data-dependent** — code only reachable with a live FDB/GribJump

### 3. Prioritize by Impact

Focus on the files with the largest absolute gaps first:
- `polytope_mars/api.py` — request parsing, format routing, shape building
- `polytope_mars/features/*.py` — feature validation and parsing logic
- `polytope_mars/utils/areas.py` — area calculations, cost estimation
- `polytope_mars/utils/datetimes.py` — date/time parsing utilities
- `polytope_mars/encoders/tensogram_encoder.py` — tensogram encoding

### 4. Write Tests

- Add tests to EXISTING test files, matching the existing patterns and style
- Each test should target a specific uncovered code path
- Use mock `TensorIndexTree` objects for code that normally needs polytope results
- Test error paths, not just happy paths
- Use adversarial inputs for validation code

### 5. Remove Dead Code

If coverage analysis reveals unreachable code:
- Verify it's truly unreachable (not just untested)
- Remove it rather than adding `# pragma: no cover`

### 6. Verify

- Run full test suite to confirm all tests pass
- Re-measure coverage to confirm improvement
- Report before/after comparison by file

## Target

Aim for at least **95% line coverage** for code testable without external data.
Acceptable exceptions:
- GribJump/FDB integration paths (require live infrastructure)
- `api.py` datacube setup code (requires `pygribjump`)
