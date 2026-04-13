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

- NOTE: When the user asks for "second pass", "third pass" or "N-th pass" perform:
  - simplification opportunities,
  - naming/comments/docs quality review,
  - scan for edge-cases and logical regression,
  - no bare excepts in Python code,
  - all documentation up-to-date with changes,
  - running required formatter/lint/tests

- NOTE: when user asks for 'error handling' checks:
  - verify no bare except clauses
  - verify how errors are handled across the codebase
  - ensure all errors handled and reported correctly with enough information reaching users
  - document all error paths in docs/

- NOTE: when user asks for 'edge cases':
  - look specifically for edge cases
  - look for undefined behaviour or ambiguities
  - if necessary, ask the user to clarify
  - document all those in docs/

- NOTE: when user asks for 'code coverage':
    - explore all the code base looking for code that isn't yet tested.
    - Look specifically for testing edge cases.
    - Aim to have at least 95% test coverage.
    - Note: tests marked `data` require a local FDB or GribJump server.

- NOTE: When user asks for 'final prep' make:
    - final check everything installs and all tests pass
    - all examples (notebooks) run
    - all docs build
    - if successful, carefully:
        - select files and contributions to git add
        - ignore build files and artifacts, don't add hidden directories
        - if not in a branch, create a new properly named branch
        - git commit
        - make a pull request to upstream github project

- NOTE: when user asks to do 'pr reply' or 'pull request reply':
    - check github pull request reviews
    - consider them with respect to the philosophy and aims of this software
    - if in doubt seek user clarifications
    - fix code and address the raised issues
    - update the docs/
    - make a summary and push your changes to update the PR
    - poll to wait for the CI to finish running
    - continue iterating until all recommendations and issues were addressed

- NOTE: When user asks for 'make release' execute:
    - check all changes are committed and pushed upstream
    - final check everything installs and all tests pass
    - all docs build
    - if any of the above fails STOP and prompt the user for action
    - otherwise, check the latest version upstream and in polytope_mars/version.py
    - if needed, bump version in polytope_mars/version.py, commit and tag then push upstream
    - make a Github release

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
