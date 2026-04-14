# Improve Error Handling

Perform a comprehensive error handling audit across the entire codebase.

## Checks

### Python Code (`polytope_mars/`)
- Verify NO bare `except:` clauses — always catch specific exception types
- All exceptions carry enough context for users to diagnose problems (parameter names, values, expected vs actual)
- No silent exception swallowing — `except: pass` patterns must log or re-raise
- `ValueError` for invalid user input, `KeyError` for missing request keys, `NotImplementedError` for unsupported features
- Error messages reference the correct feature name (audit for copy-paste errors)

### API Surface (`api.py`)
- `extract()` raises clear errors for: missing `feature`, invalid `format`, missing `type`
- `retrieve_data()` handles datacube connection failures gracefully
- Feature validation errors are surfaced before expensive retrieval operations

### Feature Implementations (`features/*.py`)
- Each `parse()` method validates all required inputs before returning
- Range overspecification and underspecification caught with clear messages
- Area/size limit violations explain what the limit is and how to reduce

### Utilities (`utils/`)
- Date/time parsing handles malformed input without crashing
- Area calculations handle degenerate geometries (zero-area, self-intersecting polygons)

### Documentation
- All error conditions documented in docs/
- Error handling patterns shown in examples where relevant

## Process

1. Scan all source files for bare excepts, silent failures, and poor error messages
2. For each finding: classify severity (crash, silent failure, poor message, undocumented)
3. Fix each issue — catch specific exceptions, improve messages, add context
4. Run all tests to verify no regressions:
   ```bash
   python -m pytest -m "not data" tests/ -v
   ```
5. Update documentation in docs/ if error behavior changes
6. Summarize all changes made
