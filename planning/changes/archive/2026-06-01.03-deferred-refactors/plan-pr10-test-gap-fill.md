# PR10: Test Gap Fill (TEST-4 + TEST-7)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add standalone test files for the four instruments that today are only covered transitively via bootstrapper integration tests (`CorsInstrument`, `HealthChecksInstrument`, `PrometheusInstrument`, `SwaggerInstrument`) and add negative tests for `helpers.path.is_valid_path`. Pure additions; zero production code changes.

**Architecture:** 5 new test files, no production changes.

**Tech Stack:** Python 3.10+, pytest, parametrized tests.

**Parent spec:** `docs/superpowers/specs/2026-06-01-deferred-refactors-sequencing.md` (PR10 section).
**Parent audit:** `docs/superpowers/specs/2026-05-31-bug-refactor-audit.md` (TEST-4, TEST-7).

---

## File Structure

5 new test files. No existing files modified.

- Create: `tests/instruments/test_cors_instrument.py`
- Create: `tests/instruments/test_healthchecks_instrument.py`
- Create: `tests/instruments/test_prometheus_instrument.py`
- Create: `tests/instruments/test_swagger_instrument.py`
- Create: `tests/test_path.py`

---

## Locked decisions

- **Pure additions:** No production code changes. The existing transitive coverage via bootstrapper integration tests is fine; standalone tests just localize regression diagnosis.
- **Test style:** Match the existing simple-function test style in `tests/instruments/test_pyroscope_instrument.py` and `test_opentelemetry_instrument.py` (no fixtures, no shared setup, one function per behavior).

---

## Task 1: Create branch

**Files:** (no files; git only)

- [ ] **Step 1: Branch off `main`**

```bash
git checkout main
git pull --ff-only origin main
git checkout -b fix/test-4-7-gaps
```

Expected: `Switched to a new branch 'fix/test-4-7-gaps'`.

---

## Task 2: Create the five test files, verify, commit

### Step 1: Create `tests/instruments/test_cors_instrument.py`

```python
from lite_bootstrap.instruments.cors_instrument import CorsConfig, CorsInstrument


def test_cors_instrument_not_ready_without_origins_or_regex() -> None:
    instrument = CorsInstrument(bootstrap_config=CorsConfig())
    assert not instrument.is_ready()
    assert instrument.not_ready_message == "cors_allowed_origins or cors_allowed_origin_regex must be provided"


def test_cors_instrument_ready_with_origins() -> None:
    instrument = CorsInstrument(bootstrap_config=CorsConfig(cors_allowed_origins=["http://test"]))
    assert instrument.is_ready()


def test_cors_instrument_ready_with_regex() -> None:
    instrument = CorsInstrument(bootstrap_config=CorsConfig(cors_allowed_origin_regex=r"https?://.*"))
    assert instrument.is_ready()


def test_cors_instrument_ready_with_both() -> None:
    instrument = CorsInstrument(
        bootstrap_config=CorsConfig(
            cors_allowed_origins=["http://test"],
            cors_allowed_origin_regex=r"https?://.*",
        ),
    )
    assert instrument.is_ready()


def test_cors_instrument_config_defaults() -> None:
    config = CorsConfig()
    assert config.cors_allowed_origins == []
    assert config.cors_allowed_methods == []
    assert config.cors_allowed_headers == []
    assert config.cors_exposed_headers == []
    assert config.cors_allowed_credentials is False
    assert config.cors_allowed_origin_regex is None
    assert config.cors_max_age == 600


def test_cors_check_dependencies() -> None:
    assert CorsInstrument.check_dependencies() is True
```

### Step 2: Create `tests/instruments/test_healthchecks_instrument.py`

```python
from lite_bootstrap.instruments.healthchecks_instrument import HealthChecksConfig, HealthChecksInstrument


def test_healthchecks_instrument_ready_by_default() -> None:
    instrument = HealthChecksInstrument(bootstrap_config=HealthChecksConfig())
    assert instrument.is_ready()


def test_healthchecks_instrument_not_ready_when_disabled() -> None:
    instrument = HealthChecksInstrument(bootstrap_config=HealthChecksConfig(health_checks_enabled=False))
    assert not instrument.is_ready()
    assert instrument.not_ready_message == "health_checks_enabled is False"


def test_healthchecks_render_data_default() -> None:
    instrument = HealthChecksInstrument(bootstrap_config=HealthChecksConfig())
    data = instrument.render_health_check_data()
    assert data == {
        "service_version": "1.0.0",
        "service_name": "micro-service",
        "health_status": True,
    }


def test_healthchecks_render_data_custom() -> None:
    instrument = HealthChecksInstrument(
        bootstrap_config=HealthChecksConfig(service_name="my-svc", service_version="2.0.0"),
    )
    data = instrument.render_health_check_data()
    assert data == {
        "service_version": "2.0.0",
        "service_name": "my-svc",
        "health_status": True,
    }


def test_healthchecks_config_defaults() -> None:
    config = HealthChecksConfig()
    assert config.health_checks_enabled is True
    assert config.health_checks_path == "/health/"
    assert config.health_checks_include_in_schema is False


def test_healthchecks_check_dependencies() -> None:
    assert HealthChecksInstrument.check_dependencies() is True
```

### Step 3: Create `tests/instruments/test_prometheus_instrument.py`

```python
from lite_bootstrap.instruments.prometheus_instrument import PrometheusConfig, PrometheusInstrument


def test_prometheus_instrument_ready_with_default_path() -> None:
    instrument = PrometheusInstrument(bootstrap_config=PrometheusConfig())
    assert instrument.is_ready()


def test_prometheus_instrument_not_ready_with_empty_path() -> None:
    instrument = PrometheusInstrument(bootstrap_config=PrometheusConfig(prometheus_metrics_path=""))
    assert not instrument.is_ready()
    assert instrument.not_ready_message == "prometheus_metrics_path is empty or not valid"


def test_prometheus_instrument_not_ready_with_invalid_path() -> None:
    # No leading slash → invalid per is_valid_path regex.
    instrument = PrometheusInstrument(bootstrap_config=PrometheusConfig(prometheus_metrics_path="metrics"))
    assert not instrument.is_ready()


def test_prometheus_instrument_ready_with_custom_valid_path() -> None:
    instrument = PrometheusInstrument(
        bootstrap_config=PrometheusConfig(prometheus_metrics_path="/custom-metrics/"),
    )
    assert instrument.is_ready()


def test_prometheus_config_defaults() -> None:
    config = PrometheusConfig()
    assert config.prometheus_metrics_path == "/metrics"
    assert config.prometheus_metrics_include_in_schema is False


def test_prometheus_check_dependencies() -> None:
    assert PrometheusInstrument.check_dependencies() is True
```

### Step 4: Create `tests/instruments/test_swagger_instrument.py`

```python
from lite_bootstrap.instruments.swagger_instrument import SwaggerConfig, SwaggerInstrument


def test_swagger_instrument_ready_by_default() -> None:
    instrument = SwaggerInstrument(bootstrap_config=SwaggerConfig())
    assert instrument.is_ready()


def test_swagger_config_defaults() -> None:
    config = SwaggerConfig()
    assert config.swagger_static_path == "/static"
    assert config.swagger_path == "/docs"
    assert config.swagger_offline_docs is False


def test_swagger_check_dependencies() -> None:
    assert SwaggerInstrument.check_dependencies() is True
```

### Step 5: Create `tests/test_path.py`

```python
import pytest

from lite_bootstrap.helpers.path import is_valid_path


@pytest.mark.parametrize(
    "path",
    [
        "/metrics",
        "/health/",
        "/api/v1/users",
        "/foo.bar",
        "/foo_bar",
        "/foo-bar",
        "/a",
        "/a/",
    ],
)
def test_is_valid_path_accepts_valid(path: str) -> None:
    assert is_valid_path(path) is True


@pytest.mark.parametrize(
    "path",
    [
        "",
        "foo",
        "foo/",
        "/foo bar",
        "/foo?bar",
        "/foo#bar",
        "/",
        "//foo",
        "/foo//bar",
    ],
)
def test_is_valid_path_rejects_invalid(path: str) -> None:
    assert is_valid_path(path) is False
```

Notes on the rejected cases:
- `""` — empty string fails the `^(/...)+/?$` pattern.
- `"foo"`, `"foo/"` — no leading `/`.
- `"/foo bar"` — space is not in `[a-zA-Z0-9._-]`.
- `"/foo?bar"`, `"/foo#bar"` — `?` and `#` are not in the charset.
- `"/"` — no segment after the slash; the regex requires `[a-zA-Z0-9._-]+`.
- `"//foo"`, `"/foo//bar"` — empty segments not allowed by the `+` quantifier.

The regex DOES accept `/..` and `/../foo` because `.` is in the charset; the `is_valid_path` function does not block path traversal. That's a pre-existing design decision (out of scope here).

### Step 6: Run the new test files

```bash
just test -- tests/instruments/test_cors_instrument.py tests/instruments/test_healthchecks_instrument.py tests/instruments/test_prometheus_instrument.py tests/instruments/test_swagger_instrument.py tests/test_path.py -v
```

Expected: all new tests PASS on first run. They're pure additions verifying current behavior.

If any test fails, investigate before continuing. The most likely cause is a wrong assertion (e.g., default value), not a real bug.

### Step 7: Run the full test suite

```bash
just test
```

Expected: total count goes from 89 to roughly 89 + (6+6+6+3+17) = ~127. All pass.

Approximate breakdown of new tests:
- `test_cors_instrument.py`: 6 tests
- `test_healthchecks_instrument.py`: 6 tests
- `test_prometheus_instrument.py`: 6 tests
- `test_swagger_instrument.py`: 3 tests
- `test_path.py`: 17 parametrized cases across 2 functions

### Step 8: Run lint

```bash
just lint
```

Expected: clean. No production changes mean no lint-rule complications.

### Step 9: Commit

Stage exactly the five new files:

```bash
git add \
  tests/instruments/test_cors_instrument.py \
  tests/instruments/test_healthchecks_instrument.py \
  tests/instruments/test_prometheus_instrument.py \
  tests/instruments/test_swagger_instrument.py \
  tests/test_path.py
git commit -m "$(cat <<'EOF'
test: add standalone instrument tests and is_valid_path negative tests

TEST-4: Add tests/instruments/test_{cors,healthchecks,prometheus,swagger}_instrument.py
covering is_ready() across valid/invalid configurations,
not_ready_message content, render_health_check_data output shape,
config defaults, and check_dependencies. These instruments were
previously only covered transitively via bootstrapper integration
tests, which made regressions noisier to diagnose.

TEST-7: Add tests/test_path.py with parametrized cases for
helpers.path.is_valid_path — both valid forms (default paths used by
the prometheus/swagger/healthchecks instruments) and invalid forms
(empty, no leading slash, spaces, special chars, empty segments).

Closes TEST-4 and TEST-7 from the audit. Pure additions; no production
code changed.
EOF
)"
```

---

## Task 3: Push and open PR

- [ ] **Step 1: Push the branch**

```bash
git push -u origin fix/test-4-7-gaps
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --title "test: add standalone instrument tests and is_valid_path negative tests" --body "$(cat <<'EOF'
## Summary
Pure test additions; no production changes.

- **TEST-4:** Standalone test files for the four instruments previously only covered transitively via bootstrapper integration tests:
  - \`tests/instruments/test_cors_instrument.py\` — \`is_ready\` matrix (origins-only, regex-only, both, neither), \`not_ready_message\`, config defaults, \`check_dependencies\`.
  - \`tests/instruments/test_healthchecks_instrument.py\` — enabled/disabled, \`render_health_check_data\` output shape, defaults.
  - \`tests/instruments/test_prometheus_instrument.py\` — valid/invalid/empty paths, defaults.
  - \`tests/instruments/test_swagger_instrument.py\` — instantiation, defaults.
- **TEST-7:** \`tests/test_path.py\` — parametrized cases for \`is_valid_path\` covering valid forms (\`/metrics\`, \`/health/\`, multi-segment, special chars in the allowed set) and invalid forms (empty, no leading slash, spaces, \`?\`/\`#\`, empty segments).

Closes TEST-4 and TEST-7 from an internal audit.

## Test plan
- [x] \`just test\` — full suite passes (89 prior + ~37 new ≈ 126).
- [x] \`just lint\` — clean.
- [ ] Reviewer: confirm the rejected-path list in \`test_path.py\` matches the intended contract. (The regex DOES accept \`/..\` because \`.\` is in the allowed charset — pre-existing design decision; not tested as a "valid" or "invalid" case.)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review

**Spec coverage check** against the sequencing spec (PR10 section) and audit (TEST-4, TEST-7):

| Spec item | Task |
|-----------|------|
| `tests/instruments/test_cors_instrument.py` | Task 2, Step 1 |
| `tests/instruments/test_healthchecks_instrument.py` | Task 2, Step 2 |
| `tests/instruments/test_prometheus_instrument.py` | Task 2, Step 3 |
| `tests/instruments/test_swagger_instrument.py` | Task 2, Step 4 |
| `tests/test_path.py` with negative cases | Task 2, Step 5 |
| Branch name `fix/test-4-7-gaps` | Task 1, Step 1 |
| Verification: `just test` + `just lint` clean | Task 2, Steps 6-8 |

All spec items covered. No placeholders. Test code matches the existing simple-function style in the codebase. The Prometheus test uses both the default `/metrics` path (valid) and `"metrics"` (invalid — no leading slash) to exercise both branches of `is_valid_path`'s logic without depending on `tests/test_path.py`.
