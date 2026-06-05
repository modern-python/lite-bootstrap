# PR3 — Hygiene & CI Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the four remaining hygiene/CI findings from the 2026-06-05 audit (UX-4, UX-5, TEST-NEW-7, SEC-5) in one small PR.

**Architecture:** Pure chore PR. No production code paths change. Three of the four tasks touch config/docs (CLAUDE.md, pyproject.toml, a new GitHub Actions workflow); only UX-4 adds a single `logger.warning(...)` call alongside the existing `warnings.warn(...)` in `BaseBootstrapper.__init__`. Tasks are independent — order is by reviewer-fatigue (docs first, then code, then config, then CI).

**Tech Stack:** Python 3.10+, `uv` workspace, `pytest`, `ty` type checker, `ruff` formatter, GitHub Actions (existing `.github/workflows/ci.yml`).

**Branch:** `fix/bug-audit-v2-pr3-hygiene-ci` (off the merged-PR2 main, currently at `c4f1d00`).

---

## File Structure

| File | What changes |
|------|-------------|
| `CLAUDE.md` | Append paragraph documenting `from_dict` vs `from_object` asymmetry (Task 1) |
| `lite_bootstrap/bootstrappers/base.py` | Add `logger.warning(...)` after existing `warnings.warn(...)` in `__init__` (Task 2) |
| `tests/test_free_bootstrap.py` | New test asserts both warning + log channels fire (Task 2) |
| `pyproject.toml` | Add `filterwarnings` under `[tool.pytest.ini_options]` (Task 3) |
| `.github/workflows/security-audit.yml` | New file — `pip-audit` job on PR + weekly cron (Task 4) |

---

## Task 1: UX-5 — Document `from_object` asymmetry in CLAUDE.md

**Files:**
- Modify: `CLAUDE.md` (append a paragraph under existing "Conventions" section)

**Context:** `BaseConfig.from_dict` includes any key present in the dict (including explicit `None` — overrides defaults). `BaseConfig.from_object` filters with `value is not None`, so an attribute explicitly set to `None` falls back to the default. Both methods are documented in their docstrings (per DES-3 fix), but a contributor reading the codebase may not encounter the docstrings. A note in CLAUDE.md under "Conventions" surfaces the asymmetry.

- [ ] **Step 1: Read the current CLAUDE.md and locate the "Conventions" section**

```bash
grep -n "^### Conventions" /Users/kevinsmith/src/pypi/lite-bootstrap/CLAUDE.md
```

Expected: returns a line number (the section is documented in PR1's instructions and exists).

- [ ] **Step 2: Append the asymmetry paragraph**

Add the following at the end of the `### Conventions` section in `CLAUDE.md`:

```markdown
- **`from_dict` vs `from_object` accept different shapes for `None`**: `BaseConfig.from_dict({"service_name": None})` succeeds and explicitly overrides the default with `None`. `BaseConfig.from_object(obj)` where `obj.service_name is None` filters the attribute out and the dataclass default takes over. The asymmetry is documented in both methods' docstrings (`instruments/base.py:17, 23`) and pinned by tests in `tests/test_config.py:54-94`. Pick `from_dict` if explicit-None override is the load-bearing semantic.
```

Place it as the last bullet in the existing Conventions list (typically after the existing bullets about no `# noqa: PLR2004`, backward-compat aliases, frozen-config bypass, and optional-import guard pattern).

- [ ] **Step 3: Verify no other docs need updating**

```bash
grep -rn "from_object\|from_dict" /Users/kevinsmith/src/pypi/lite-bootstrap/docs 2>/dev/null | head -5
```

If the mkdocs site has API reference docs for these methods, they already inherit from the docstrings — no action needed.

- [ ] **Step 4: Run lint (CLAUDE.md isn't covered by ruff/ty, but eof-fixer might reformat it)**

```bash
just lint-ci
```

Expected: green.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "$(cat <<'EOF'
docs: document from_object/from_dict None asymmetry in CLAUDE.md (UX-5)

The two BaseConfig constructors behave differently on explicit None: from_dict
accepts None as an explicit override of the default, while from_object filters
None attributes and lets the default take over. Documented in method docstrings;
add a CLAUDE.md note for contributor visibility.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: UX-4 — Dual `warnings.warn` + `logger.warning` on missing dependency

**Files:**
- Modify: `lite_bootstrap/bootstrappers/base.py:61-68`
- Test: `tests/test_free_bootstrap.py`

**Context:** `BaseBootstrapper.__init__` emits `warnings.warn(..., InstrumentDependencyMissingWarning, stacklevel=3)` when a configured instrument's optional dependency is missing. Python processes launched with `-W ignore` or `PYTHONWARNINGS=ignore` swallow that signal entirely. Add a parallel `logger.warning(...)` so users who suppress one channel still see the other.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_free_bootstrap.py`:

```python
def test_missing_dependency_warning_logs_via_logger_too(
    free_bootstrapper_config: FreeConfig, caplog: pytest.LogCaptureFixture
) -> None:
    with (
        emulate_package_missing("sentry_sdk"),
        caplog.at_level(logging.WARNING, logger="lite_bootstrap.bootstrappers.base"),
        pytest.warns(UserWarning, match="sentry_sdk"),
    ):
        FreeBootstrapper(bootstrap_config=free_bootstrapper_config)

    matching = [r for r in caplog.records if "sentry_sdk" in r.message and r.levelname == "WARNING"]
    assert matching, [r.message for r in caplog.records]
```

`logging`, `pytest`, `emulate_package_missing`, `FreeBootstrapper`, `FreeConfig`, `free_bootstrapper_config` are all already in scope in this file.

- [ ] **Step 2: Run test to verify it fails**

```bash
just test -- tests/test_free_bootstrap.py::test_missing_dependency_warning_logs_via_logger_too
```

Expected: FAIL — no `logger.warning` call exists in the dependency-missing path; the assertion `matching` is empty.

- [ ] **Step 3: Add the parallel `logger.warning` call**

In `lite_bootstrap/bootstrappers/base.py`, the current `__init__` body (around lines 61-68) reads:

```python
            # Dep-missing for a CONFIGURED instrument is a genuine deployment surprise.
            if not instrument_type.check_dependencies():
                warnings.warn(
                    instrument_type.missing_dependency_message,
                    category=InstrumentDependencyMissingWarning,
                    stacklevel=3,
                )
                continue
```

Replace with:

```python
            # Dep-missing for a CONFIGURED instrument is a genuine deployment surprise.
            if not instrument_type.check_dependencies():
                warnings.warn(
                    instrument_type.missing_dependency_message,
                    category=InstrumentDependencyMissingWarning,
                    stacklevel=3,
                )
                logger.warning(
                    "instrument %s skipped: %s",
                    instrument_type.__name__,
                    instrument_type.missing_dependency_message,
                )
                continue
```

Both signals fire side-by-side — `warnings.warn` for the structured-warning channel; `logger.warning` for the stdlib-logging channel. Users who suppress one still see the other.

- [ ] **Step 4: Run the new test to verify it passes**

```bash
just test -- tests/test_free_bootstrap.py::test_missing_dependency_warning_logs_via_logger_too
```

Expected: PASS.

- [ ] **Step 5: Verify the rest of the suite**

```bash
just test
```

Expected: all green, 100% coverage. The existing
`test_free_bootstrapper_with_missing_instrument_dependency` (and the parallel
tests for FastAPI/Litestar/FastStream/FastMcp) still pass — they use
`pytest.warns(...)`, which captures only the warning channel, and the new log
line doesn't interfere.

- [ ] **Step 6: Lint**

```bash
just lint-ci
```

Expected: green.

- [ ] **Step 7: Commit**

```bash
git add lite_bootstrap/bootstrappers/base.py tests/test_free_bootstrap.py
git commit -m "$(cat <<'EOF'
feat: emit logger.warning alongside warnings.warn on missing dep (UX-4)

BaseBootstrapper.__init__ now logs the missing-dependency event via stdlib
logging in addition to the existing warnings.warn. Users who suppress one
channel (python -W ignore, PYTHONWARNINGS=ignore) still see the other.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: TEST-NEW-7 — Escalate `InstrumentSkippedWarning` in pytest

**Files:**
- Modify: `pyproject.toml` (`[tool.pytest.ini_options]` section)

**Context:** Adds a `filterwarnings` entry that promotes any unexpected
`InstrumentSkippedWarning` (or its subclass `InstrumentDependencyMissingWarning`)
to an error during tests. Tests that intentionally trigger the warning use
`pytest.warns(...)`, which still passes. The escalation catches future regressions
where an unrelated code path emits the warning silently.

- [ ] **Step 1: Add `filterwarnings`**

In `pyproject.toml`, the current `[tool.pytest.ini_options]` block (around line 177-180) reads:

```toml
[tool.pytest.ini_options]
addopts = "--cov=. --cov-report term-missing --cov-fail-under=100"
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
```

Add a `filterwarnings` key:

```toml
[tool.pytest.ini_options]
addopts = "--cov=. --cov-report term-missing --cov-fail-under=100"
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
filterwarnings = [
    "error::lite_bootstrap.exceptions.InstrumentSkippedWarning",
]
```

`InstrumentSkippedWarning` is the base class; `InstrumentDependencyMissingWarning`
is its subclass. The `error::ClassName` form matches the class and all subclasses,
so a single entry covers both.

- [ ] **Step 2: Run the full suite**

```bash
just test
```

Expected: all green. Two pre-existing tests intentionally allow `InstrumentSkippedWarning`
without `pytest.warns`:

- `test_config_from_dict` and `test_config_from_object` in `tests/test_config.py` pass `opentelemetry_endpoint="otl"` which fires `UserWarning` (not `InstrumentSkippedWarning`) — should still pass.
- All `test_*_bootstrapper_with_missing_instrument_dependency` tests use `pytest.warns(UserWarning, match=...)` — `pytest.warns` consumes the warning before the filterwarnings escalation can fire. Should still pass.

If any test fails because of an unexpected warning escalation, fix the test (wrap with `pytest.warns` or scope the filter narrower). Don't relax the filter to make it pass.

- [ ] **Step 3: Lint**

```bash
just lint-ci
```

Expected: green.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "$(cat <<'EOF'
test: escalate InstrumentSkippedWarning to error in pytest (TEST-NEW-7)

Add filterwarnings entry under [tool.pytest.ini_options] so any unexpected
InstrumentSkippedWarning (or subclass) fails the test. Tests that intentionally
trigger the warning use pytest.warns(...) and continue to pass; future
regressions that emit the warning silently from unrelated code paths now fail.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: SEC-5 — CI pip-audit gate

**Files:**
- Create: `.github/workflows/security-audit.yml`

**Context:** The project has no CI gate on dependency vulnerabilities today. `pip-audit` (OSV-backed, uv-native via `uv tool install`) runs against the exported lockfile on every PR and weekly via cron. A new CVE in any of the 133 locked packages fails the workflow, blocking the PR until resolved or whitelisted.

- [ ] **Step 1: Verify no existing security workflow**

```bash
ls /Users/kevinsmith/src/pypi/lite-bootstrap/.github/workflows/
```

Expected: `ci.yml` and `publish.yml` only — no `security-audit.yml`.

- [ ] **Step 2: Create the workflow**

Write `.github/workflows/security-audit.yml`:

```yaml
name: security-audit

on:
  pull_request: {}
  schedule:
    - cron: "0 6 * * 1"  # weekly Monday 06:00 UTC

concurrency:
  group: security-audit-${{ github.head_ref || github.run_id }}
  cancel-in-progress: true

jobs:
  pip-audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
        with:
          enable-cache: true
          cache-dependency-glob: "**/pyproject.toml"
      - run: uv python install 3.10
      - name: Export locked dependencies
        run: uv export --all-extras --no-hashes > /tmp/requirements.txt
      - name: Install pip-audit
        run: uv tool install pip-audit
      - name: Audit dependencies
        run: pip-audit --no-deps --disable-pip -r /tmp/requirements.txt
```

Mirrors the conventions used in the existing `ci.yml`: `astral-sh/setup-uv@v3` with cache, Python 3.10 install, concurrency group. `--no-deps --disable-pip` skips pip's resolver (`pip-audit` would otherwise try to create a fresh venv and `ensurepip`, which has known issues on cpython 3.14 via the uv-managed Python).

- [ ] **Step 3: Validate the YAML syntax**

```bash
python -c "import yaml; yaml.safe_load(open('/Users/kevinsmith/src/pypi/lite-bootstrap/.github/workflows/security-audit.yml'))"
```

Expected: no output (silent success). If the loader raises, fix the indentation.

- [ ] **Step 4: Lint (CI workflows aren't covered by ruff/ty, but check passes anyway)**

```bash
just lint-ci
```

Expected: green.

- [ ] **Step 5: Smoke-test pip-audit locally**

```bash
uv export --all-extras --no-hashes > /tmp/req-local.txt
pip-audit --no-deps --disable-pip -r /tmp/req-local.txt 2>&1 | tail -5
```

Expected: `No known vulnerabilities found` (matches the audit's earlier run on 2026-06-05). If new CVEs landed since then, surface them — fixing CVEs is out of scope for this PR (track in a separate issue), but the workflow file should still land so future regressions are caught.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/security-audit.yml
git commit -m "$(cat <<'EOF'
ci: add pip-audit security gate workflow (SEC-5)

New workflow runs pip-audit against the locked dependency set on every PR and
weekly via cron. Mirrors the conventions of the existing ci.yml (setup-uv with
cache, Python 3.10, concurrency group). --no-deps --disable-pip avoids pip's
ensurepip path which has known issues on uv-managed cpython 3.14.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Final verification

- [ ] **Step 1: Full test suite**

```bash
just test
```

Expected: 187 passed (186 baseline + 1 new from Task 2), 100% coverage.

- [ ] **Step 2: Lint**

```bash
just lint-ci
```

Expected: green.

- [ ] **Step 3: Confirm the commit log shape**

```bash
git log --oneline origin/main..HEAD
```

Expected: 5 commits (1 plan + 4 task commits), each with the right prefix:

- Plan — `docs: add PR3 TDD plan ...`
- Task 1 (UX-5) — `docs:`
- Task 2 (UX-4) — `feat:`
- Task 3 (TEST-NEW-7) — `test:`
- Task 4 (SEC-5) — `ci:`

---

## Self-Review

1. **Spec coverage:** UX-4 (Task 2) · UX-5 (Task 1) · TEST-NEW-7 (Task 3) · SEC-5 (Task 4). All four PR3 findings mapped.
2. **Placeholder scan:** every step has full code blocks, exact commands, and expected outcomes.
3. **No cross-task structural conflicts:** the four tasks touch disjoint files (CLAUDE.md / base.py + test / pyproject.toml / new workflow file). Task ordering doesn't matter for correctness; the chosen order is by review-fatigue.
4. **Commit isolation:** each task ends with a single commit scoped to its finding ID.
5. **No new files in `lite_bootstrap/` or `tests/`:** PR3 is pure config/docs/CI. The only new file is the workflow.
