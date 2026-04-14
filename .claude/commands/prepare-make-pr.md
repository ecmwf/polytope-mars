# Prepare and Create Pull Request

Final preparation check and PR creation workflow.

## Pre-flight Checks

Run ALL of the following. If ANY step fails, STOP and report the failure.

### 1. Code Quality
```bash
black --check --line-length 120 .
isort --check --profile black .
flake8 .
```

### 2. Tests
```bash
python -m pytest -m "not data" tests/ -v
```

### 3. Examples
Verify Jupyter notebooks in `examples/` are current with any API changes.

### 4. Documentation
```bash
# Verify docs build if mkdocs is available
which mkdocs && mkdocs build || echo "mkdocs not installed, skip"
```

### 5. plans/DONE.md
Ensure `plans/DONE.md` is up-to-date with any changes being committed.

## PR Creation

If all checks pass:

1. Review what files to include — stage only source, test, doc, and config files
2. Do NOT stage: build artifacts, hidden directories (except `.claude/`, `.github/`),
   `*.egg-info/`, `.venv/`, `__pycache__/`, `.pytest_cache/`
3. If not already on a feature branch, create one with a descriptive name
4. Commit with a clear, conventional-commit-style message
5. Push to origin
6. Create a pull request with:
   - Title: concise summary of the change
   - Body: structured summary with Added/Changed/Fixed sections
   - Link to any related issues
7. Report the PR URL
