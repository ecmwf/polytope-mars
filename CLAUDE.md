# Claude and Other Agents

# Guidelines

- NOTE: When the user's request matches an available skill:
    - ALWAYS invoke it using the Skill tool as your FIRST action.
    - Do NOT answer directly, do NOT use other tools first.
    - The skill has specialized workflows that produce better results than ad-hoc answers.

- IMPORTANT: when planning and before you do any work:
  - ALWAYS mention how you would verify and validate that work is correct
  - include TDD tests in your plan
  - take a behaviour driven approach
  - you are very much ENCOURAGED to ask questions to get the design correct
  - ALWAYS seek clarifications to sort out ambiguities
  - ALWAYS provide a summary of the Design and implementation Plan

- IMPORTANT: when you build code and new features:
  - ALWAYS document those features in docs/user_guide/
  - Remember to add examples in examples/ (Jupyter notebooks)

# Slash Commands

The following slash commands are available in `.claude/commands/`:

| Command | Trigger | Description |
|---------|---------|-------------|
| `/make-further-pass N` | "second pass", "third pass", "Nth pass" | Quality review with increasing strictness per pass number |
| `/improve-error-handling` | "error handling" | Audit bare excepts, error messages, error paths |
| `/improve-edge-cases` | "edge cases" | Systematic edge case audit and hardening |
| `/improve-code-coverage` | "code coverage" | Measure coverage, fill gaps to 95%+ |
| `/prepare-make-pr` | "final prep" | Pre-flight checks, commit, push, create PR |
| `/address-pr-comments N` | "pr reply", "pull request reply" | Fetch and address all PR review comments |
| `/make-release X.Y.Z` | "make release" | Full release workflow with checks, tag, GitHub release |

# Design & Purpose

- README.md -- entry level generic information
- plans/MOTIVATION.md -- why polytope-mars exists and what we're building
- plans/DESIGN.md -- design rationale and key architectural decisions
- plans/DONE.md -- current implementation status (keep updated)
- plans/TODO.md -- features decided to implement (accepted backlog)

Follow plans/DESIGN.md principles in all code.

# Build / lint / test (required before marking done)

## Language
This project is Python only.

## Python
- Install: `pip install -e .`
- Install dev deps: `pip install pytest pytest-cov black flake8 isort`
- Format: `black --line-length 120 .`
- Import sort: `isort --profile black .`
- Lint: `flake8 .`
- Test (no data): `python -m pytest -m "not data" tests/ -v`
- Test (all, requires FDB/GribJump): `python -m pytest tests/ -v --log-cli-level=DEBUG`
- Test single: `python -m pytest tests/ -k "test_name" -v`
- IMPORTANT: ALWAYS run `black`, `isort`, and `flake8` before committing. CI enforces this.

## Data dependency
- Integration tests marked `@pytest.mark.data` require either:
  - A local FDB with test data and `GRIBJUMP_CONFIG_FILE` set, or
  - Environment variables pointing to a GribJump server.
- Unit tests (parsing, validation, area calculations) should NOT require data.

# Version control
- Git project at github.com/ecmwf/polytope-mars
- IMPORTANT:
    - versions are tagged using Semantic Versioning 'MAJOR.MINOR.MICRO'
    - NEVER update MAJOR unless user says so.
    - Increment MINOR for new features. MICRO for bugfixes and documentation updates.
- NEVER prepend git tag or releases with 'v'
- REMEMBER on releases:
    - check all is committed and pushed upstream, otherwise STOP and warn user
    - update polytope_mars/version.py
    - git tag with version
    - push and create release in github

- NOTE: SINGLE SOURCE OF TRUTH FOR VERSION — `polytope_mars/version.py` is the
  canonical version for the project. `setup.py` reads it via regex at build time.
  When bumping the version, you MUST update `polytope_mars/version.py`.

# Tracking Work Done

Keep track of implementations in plans/DONE.md for all code changes.

# Documentation

Create and maintain documentation under docs/.
- User guides for each feature type in docs/user_guide/
- Design documentation in docs/design/
- Use mkdocs for building
- Add examples when it becomes hard to follow
- Especially note the edge cases

# Examples

Create and maintain examples in examples/
- Use Jupyter notebooks for interactive demonstrations
- Cover the most common use cases per feature type
- Show how to use the PolytopeMars API with different configurations
