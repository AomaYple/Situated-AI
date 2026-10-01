# Repository Structure Reorganization Implementation Plan

> **For agentic workers:** Execute this plan task by task with verification after each migration.

**Goal:** Separate the Python package, tests, development helpers, and historical reports without changing the Victoria 3 mod delivery path.

**Architecture:** Move the installable package to `src/pdx/`, tests to `tests/`, and reports to `docs/reports/`; keep `mod/`, `research/`, and evidence paths stable. Update packaging, CI, tests, documentation, and path-sensitive code, then verify imports, offline gates, lint, encoding, and the test suite.

**Tech Stack:** Python 3.11+, setuptools, pytest, Ruff, mypy, Git path-aware migration.

**Global Constraints**

- Preserve all existing uncommitted changes and recoverable evidence.
- Keep repository text UTF-8 without BOM and LF; game delivery BOM remains a packaging concern.
- Do not alter game-facing `mod/` or probe directory semantics.
- Use the repository `.venv` Python for commands.

### Task 1: Move package, tests, and reports

- [x] Move `tools/pdx/` to `src/pdx/`.
- [x] Move `tools/tests/` to `tests/`.
- [x] Move `tools/reports/` to `docs/reports/`.
- [x] Keep `tools/out/`, `tools/probe/`, `tools/benchmarks/`, `tools/ci/`, and `tools/prof/` in place.

### Task 2: Update project configuration and path-sensitive code

- [x] Update setuptools package discovery, pytest testpaths, mypy paths, mutmut paths, coverage source, CI commands, and `.gitignore` path rules.
- [x] Update repository-root calculations and all exact textual references to the moved paths.
- [x] Preserve game paths such as `tools/probe/` and `tools/scripted_tests/`.

### Task 3: Verify and document the final tree

- [x] Run import and collection checks, offline gates, lint/format/type checks, encoding checks, and targeted tests.
- [x] Regenerate the final inventory/audit artifacts after the tree settles.
- [x] Report remaining limitations, including the lack of native macOS/Linux execution in this workspace.
