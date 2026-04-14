# Further Pass Review

Perform a quality review pass over the codebase or the specified area.

**This is pass number $ARGUMENTS (default: 2 if not specified).**

Track the pass number and increase strictness with each successive pass:

## Pass 1-2 (Foundation)
- Simplification opportunities — reduce complexity, remove redundancy
- Naming quality — variables, functions, types, modules
- Comments and doc quality — accurate, helpful, not redundant
- Running required formatter/lint/tests:
  ```bash
  black --line-length 120 .
  isort --profile black .
  flake8 .
  python -m pytest -m "not data" tests/ -v
  ```

## Pass 3-4 (Hardening)
Everything from Pass 1-2, PLUS:
- Scan for edge-cases and logical regressions
- No bare `except:` clauses in Python code — always catch specific exceptions
- All documentation up-to-date with changes
- Error messages are clear and actionable
- Public API surface is minimal and clean
- No dead code, no unused imports, no stale TODOs

## Pass 5+ (Polish)
Everything from Pass 3-4, PLUS with ZERO TOLERANCE:
- Every public function has a docstring
- Every error path is tested
- Every edge case has a test
- Code reads like well-written prose — a newcomer could understand it
- Performance: no unnecessary copies or conversions
- Consistency: similar patterns handled the same way everywhere
- All docs in docs/user_guide/ are complete and current
- Examples in examples/ all work

## Process

1. State which pass number this is and what strictness level applies
2. Scan the codebase (or specified files/area)
3. List all findings grouped by category
4. Fix each finding, verifying the fix and tests pass
5. Run all formatters and linters: `black`, `isort`, `flake8`
6. Run tests: `python -m pytest -m "not data" tests/ -v`
7. Summarize what was changed and what the next pass should focus on
