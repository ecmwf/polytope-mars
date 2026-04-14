# Make Release

Create a new release of polytope-mars.

## Arguments

Provide the version as argument, e.g. `/make-release 0.4.0`
If no version given, auto-increment MICRO from the current version in
`polytope_mars/version.py`.

## Pre-release Checks

Run ALL of the following. If ANY step fails, STOP and prompt the user.

### 1. Clean Working Tree
```bash
git status  # must be clean — all changes committed and pushed
git diff --stat origin/develop  # must be empty
```

### 2. Code Quality
```bash
black --check --line-length 120 .
isort --check --profile black .
flake8 .
```

### 3. Tests
```bash
python -m pytest -m "not data" tests/ -v
```

### 4. Documentation
```bash
which mkdocs && mkdocs build || echo "mkdocs not installed, skip"
```

If ANY of the above fails, STOP and report the failure to the user.

## Release Process

### 1. Version Bump

Read the current version from `polytope_mars/version.py`. Bump to the target version.

**SINGLE SOURCE OF TRUTH:** `polytope_mars/version.py` is the canonical version.
`setup.py` reads it via regex at build time. Only this file needs updating.

```python
# polytope_mars/version.py
__version__ = "X.Y.Z"
```

Verify no stale version strings remain:
```bash
grep -r '__version__' polytope_mars/
```

### 2. Commit, Tag, Push
```bash
git add polytope_mars/version.py
git commit -m "chore: release X.Y.Z"
git tag X.Y.Z
git push && git push --tags
```

### 3. Create GitHub Release
```bash
gh release create X.Y.Z --title "X.Y.Z" --notes "..."
```

Release notes should summarize changes since the last release using:
```bash
git log <last-tag>..HEAD --oneline
```

**IMPORTANT:** Version tags are bare semver (e.g. `0.4.0`), NEVER prefixed with `v`.
**IMPORTANT:** NEVER bump MAJOR unless the user explicitly says so.
**IMPORTANT:** Increment MINOR for new features. MICRO for bugfixes and documentation.
