# Instrument Skip Rework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `InstrumentNotReadyWarning` with a pre-instantiation `is_configured` classmethod check. Skipped-due-to-config becomes silent at the warning level; structured `bootstrapper.skipped_instruments` introspection + one INFO summary log provide diagnostic visibility. `InstrumentDependencyMissingWarning` continues to fire for the genuine "configured but dependency missing" deployment-surprise case.

**Architecture:** `BaseInstrument.is_ready(self) -> bool` (instance method) is removed and replaced with `BaseInstrument.is_configured(cls, bootstrap_config) -> bool` (classmethod). The bootstrapper's `_register_or_skip` helper is inlined; the new flow checks `is_configured(config)` BEFORE `check_dependencies()` BEFORE instantiation. Silent skip on is_configured False; warning on check_dependencies False; otherwise instantiate. After the loop, emit one INFO log summarizing configured + skipped instruments. Bootstrapper-level `is_ready` methods (framework availability checks like "fastapi is not installed") are unchanged.

**Tech Stack:** Python 3.10+, dataclasses, stdlib `warnings` + `logging`, pytest (caplog), structlog (transitive).

**Parent spec:** `docs/superpowers/specs/2026-06-01-instrument-skip-rework-design.md`

---

## File Structure

15 production files modified, 6 test files modified, 2 docs modified, 0 new files.

**Production (12 instrument-side + 3 bootstrapper-side files):**

| File | Change |
|------|--------|
| `lite_bootstrap/instruments/base.py` | `BaseInstrument.is_ready` → `is_configured` classmethod |
| `lite_bootstrap/instruments/cors_instrument.py` | `CorsInstrument.is_ready` → `is_configured` |
| `lite_bootstrap/instruments/healthchecks_instrument.py` | `HealthChecksInstrument.is_ready` → `is_configured` |
| `lite_bootstrap/instruments/logging_instrument.py` | `LoggingInstrument.is_ready` → `is_configured` |
| `lite_bootstrap/instruments/opentelemetry_instrument.py` | `OpenTelemetryInstrument.is_ready` → `is_configured` |
| `lite_bootstrap/instruments/prometheus_instrument.py` | `PrometheusInstrument.is_ready` → `is_configured` |
| `lite_bootstrap/instruments/pyroscope_instrument.py` | `PyroscopeInstrument.is_ready` → `is_configured` |
| `lite_bootstrap/instruments/sentry_instrument.py` | `SentryInstrument.is_ready` → `is_configured` |
| `lite_bootstrap/instruments/swagger_instrument.py` | (none — uses default) |
| `lite_bootstrap/bootstrappers/faststream_bootstrapper.py` | `FastStreamOpenTelemetryInstrument.is_ready` and `FastStreamPrometheusInstrument.is_ready` → `is_configured`. `FastStreamBootstrapper.is_ready` (bootstrapper-level) **unchanged**. |
| `lite_bootstrap/bootstrappers/litestar_bootstrapper.py` | `LitestarSwaggerInstrument.is_ready` → `is_configured`. `LitestarBootstrapper.is_ready` **unchanged**. |
| `lite_bootstrap/bootstrappers/base.py` | Replace `_register_or_skip` with inline flow; add `skipped_instruments`; emit summary log; remove `InstrumentNotReadyWarning` import. |
| `lite_bootstrap/exceptions.py` | Remove `InstrumentNotReadyWarning` class. |
| `lite_bootstrap/__init__.py` | Remove `InstrumentNotReadyWarning` import + `__all__` entry. |

**Tests (6 files):**

| File | Change |
|------|--------|
| `tests/test_free_bootstrap.py` | `test_free_bootstrap_logging_disabled` rewritten. New `test_bootstrap_emits_summary_log`. |
| `tests/instruments/test_cors_instrument.py` | `is_ready()` → `is_configured(config)` |
| `tests/instruments/test_healthchecks_instrument.py` | same |
| `tests/instruments/test_prometheus_instrument.py` | same |
| `tests/instruments/test_pyroscope_instrument.py` | same |
| `tests/instruments/test_swagger_instrument.py` | same |

**Docs:**

| File | Change |
|------|--------|
| `docs/introduction/configuration.md` | Revise the PR #86 warning subclasses section (introduced ~31 lines; updated to reflect single dep-missing warning + `skipped_instruments` + summary log). |
| `CLAUDE.md` | Update "Optional dependencies" key design decision to mention `is_configured` ordering. |

---

## Pre-flight grep verification

Before starting, confirm scope matches reality:

```bash
grep -rn "def is_ready\|\.is_ready(" lite_bootstrap/ tests/ --include="*.py"
```

Expected count:
- 8 `def is_ready(self)` in `lite_bootstrap/instruments/` (one per base instrument file).
- 3 `def is_ready(self)` instrument-level overrides in `lite_bootstrap/bootstrappers/` (FastStream OTel, FastStream Prometheus, Litestar Swagger).
- 5 `def is_ready(self)` BOOTSTRAPPER-LEVEL methods (FastAPI, Litestar, FastStream, Free, FastMcp Bootstrappers) — these are NOT migrated.
- 1 `def is_ready(self)` abstract on `BaseBootstrapper` — NOT migrated.
- 2 `self.is_ready()` calls in `bootstrappers/base.py` (one in `__init__` bootstrapper check at line 34, one in `_register_or_skip` instrument check at line 57) — only the line 57 call migrates.
- ~14 `instrument.is_ready()` calls in test files — all migrate.

```bash
grep -rn "not_ready_message" lite_bootstrap/ tests/ --include="*.py"
```

Expected: `not_ready_message` is preserved as a class attribute (used in `skipped_instruments` tuples and bootstrapper-level `BootstrapperNotReadyError`). Only its emission in the deleted `InstrumentNotReadyWarning` goes away.

```bash
grep -rn "InstrumentNotReadyWarning" lite_bootstrap/ tests/ --include="*.py"
```

Expected: 5 matches (declaration in `exceptions.py`, import + emission in `bootstrappers/base.py`, import + export in `__init__.py`, import + usage in `tests/test_free_bootstrap.py`). All are removed by this plan.

---

## Task 1: Create branch

**Files:** (no files; git only)

- [ ] **Step 1: Branch off `main`** (NOT the current feat/fastmcp-bootstrapper branch — this refactor is independent)

```bash
git checkout main
git pull --ff-only origin main
git checkout -b refactor/instrument-skip-rework
```

Expected: `Switched to a new branch 'refactor/instrument-skip-rework'`.

Note: the design spec (`docs/superpowers/specs/2026-06-01-instrument-skip-rework-design.md`) was committed to `feat/fastmcp-bootstrapper`. This plan does not depend on it being on main; the plan is self-contained.

---

## Task 2: Migrate `BaseInstrument` to `is_configured` classmethod

**File:** `lite_bootstrap/instruments/base.py`

- [ ] **Step 1: Replace the `BaseInstrument` body**

Current (lines 32-47):

```python
@dataclasses.dataclass(kw_only=True, slots=True)
class BaseInstrument(typing.Generic[ConfigT]):
    bootstrap_config: ConfigT
    not_ready_message = ""
    missing_dependency_message = ""

    def bootstrap(self) -> None: ...

    def teardown(self) -> None: ...

    def is_ready(self) -> bool:
        return True

    @staticmethod
    def check_dependencies() -> bool:
        return True
```

Replace with:

```python
@dataclasses.dataclass(kw_only=True, slots=True)
class BaseInstrument(typing.Generic[ConfigT]):
    bootstrap_config: ConfigT
    not_ready_message = ""
    missing_dependency_message = ""

    def bootstrap(self) -> None: ...

    def teardown(self) -> None: ...

    @classmethod
    def is_configured(cls, bootstrap_config: ConfigT) -> bool:
        """Return True if config indicates this instrument should be active. Default: always active."""
        return True

    @staticmethod
    def check_dependencies() -> bool:
        return True
```

Two changes:
1. Remove the `is_ready` instance method.
2. Add `is_configured` classmethod with default `return True`.

The class attribute `not_ready_message` stays.

---

## Task 3: Migrate each base instrument's `is_ready` to `is_configured`

Eight instrument files, mechanical migration. Each step is one file.

- [ ] **Step 1: `lite_bootstrap/instruments/cors_instrument.py`**

Find:

```python
    def is_ready(self) -> bool:
        return bool(self.bootstrap_config.cors_allowed_origins) or bool(
            self.bootstrap_config.cors_allowed_origin_regex,
        )
```

Replace with:

```python
    @classmethod
    def is_configured(cls, bootstrap_config: "CorsConfig") -> bool:
        return bool(bootstrap_config.cors_allowed_origins) or bool(bootstrap_config.cors_allowed_origin_regex)
```

- [ ] **Step 2: `lite_bootstrap/instruments/healthchecks_instrument.py`**

Find:

```python
    def is_ready(self) -> bool:
        return self.bootstrap_config.health_checks_enabled
```

Replace with:

```python
    @classmethod
    def is_configured(cls, bootstrap_config: "HealthChecksConfig") -> bool:
        return bootstrap_config.health_checks_enabled
```

- [ ] **Step 3: `lite_bootstrap/instruments/logging_instrument.py`**

Find:

```python
    def is_ready(self) -> bool:
        return self.bootstrap_config.logging_enabled
```

Replace with:

```python
    @classmethod
    def is_configured(cls, bootstrap_config: "LoggingConfig") -> bool:
        return bootstrap_config.logging_enabled
```

- [ ] **Step 4: `lite_bootstrap/instruments/opentelemetry_instrument.py`**

Find:

```python
    def is_ready(self) -> bool:
        return bool(self.bootstrap_config.opentelemetry_endpoint or self.bootstrap_config.opentelemetry_log_traces)
```

Replace with:

```python
    @classmethod
    def is_configured(cls, bootstrap_config: "OpenTelemetryConfig") -> bool:
        return bool(bootstrap_config.opentelemetry_endpoint or bootstrap_config.opentelemetry_log_traces)
```

- [ ] **Step 5: `lite_bootstrap/instruments/prometheus_instrument.py`**

Find:

```python
    def is_ready(self) -> bool:
        return bool(self.bootstrap_config.prometheus_metrics_path) and is_valid_path(
            self.bootstrap_config.prometheus_metrics_path
        )
```

Replace with:

```python
    @classmethod
    def is_configured(cls, bootstrap_config: "PrometheusConfig") -> bool:
        return bool(bootstrap_config.prometheus_metrics_path) and is_valid_path(bootstrap_config.prometheus_metrics_path)
```

- [ ] **Step 6: `lite_bootstrap/instruments/pyroscope_instrument.py`**

Find:

```python
    def is_ready(self) -> bool:
        return bool(self.bootstrap_config.pyroscope_endpoint)
```

Replace with:

```python
    @classmethod
    def is_configured(cls, bootstrap_config: "PyroscopeConfig") -> bool:
        return bool(bootstrap_config.pyroscope_endpoint)
```

- [ ] **Step 7: `lite_bootstrap/instruments/sentry_instrument.py`**

Find:

```python
    def is_ready(self) -> bool:
        return bool(self.bootstrap_config.sentry_dsn)
```

Replace with:

```python
    @classmethod
    def is_configured(cls, bootstrap_config: "SentryConfig") -> bool:
        return bool(bootstrap_config.sentry_dsn)
```

- [ ] **Step 8: `lite_bootstrap/instruments/swagger_instrument.py`**

`SwaggerInstrument` doesn't override `is_ready` (uses the default `return True` from the base). No change needed in this file.

- [ ] **Step 9: Smoke check — instruments module imports cleanly**

```bash
uv run python -c "from lite_bootstrap.instruments.cors_instrument import CorsInstrument, CorsConfig; assert CorsInstrument.is_configured(CorsConfig()) is False; print('ok')"
```

Expected: `ok`. If `AttributeError: type object 'CorsInstrument' has no attribute 'is_configured'` — Task 3 has a missed file.

---

## Task 4: Migrate framework instrument-level overrides

Three instrument-level `is_ready` overrides live in bootstrapper files. Migrate them.

- [ ] **Step 1: `lite_bootstrap/bootstrappers/faststream_bootstrapper.py` — FastStreamOpenTelemetryInstrument**

Find (around line 128-129):

```python
    def is_ready(self) -> bool:
        return super().is_ready() and bool(self.bootstrap_config.opentelemetry_middleware_cls)
```

Replace with:

```python
    @classmethod
    def is_configured(cls, bootstrap_config: "FastStreamConfig") -> bool:
        return super().is_configured(bootstrap_config) and bool(bootstrap_config.opentelemetry_middleware_cls)
```

- [ ] **Step 2: `lite_bootstrap/bootstrappers/faststream_bootstrapper.py` — FastStreamPrometheusInstrument**

Find (around line 151-155):

```python
    def is_ready(self) -> bool:
        return (
            super().is_ready()
            and import_checker.is_prometheus_client_installed
            and bool(self.bootstrap_config.prometheus_middleware_cls)
        )
```

Replace with (dropping the dead `import_checker.is_prometheus_client_installed` conjunct per DES-5):

```python
    @classmethod
    def is_configured(cls, bootstrap_config: "FastStreamConfig") -> bool:
        return super().is_configured(bootstrap_config) and bool(bootstrap_config.prometheus_middleware_cls)
```

The `import_checker.is_prometheus_client_installed` check is dead because `_register_or_skip` will call `check_dependencies()` AFTER `is_configured()` returns True, and `check_dependencies()` already checks `import_checker.is_prometheus_client_installed`.

- [ ] **Step 3: `lite_bootstrap/bootstrappers/litestar_bootstrapper.py` — LitestarSwaggerInstrument**

Find (around line 221, the instrument-level — NOT the bootstrapper-level at line 276):

```python
    def is_ready(self) -> bool:
        return bool(self.bootstrap_config.swagger_path) and is_valid_path(self.bootstrap_config.swagger_path)
```

Replace with:

```python
    @classmethod
    def is_configured(cls, bootstrap_config: "LitestarConfig") -> bool:
        return bool(bootstrap_config.swagger_path) and is_valid_path(bootstrap_config.swagger_path)
```

- [ ] **Step 4: Sanity grep — no leftover instrument-level is_ready**

```bash
grep -n "def is_ready" lite_bootstrap/instruments/ lite_bootstrap/bootstrappers/
```

Expected matches: only bootstrapper-level overrides (`FastAPIBootstrapper.is_ready` in `fastapi_bootstrapper.py`, `LitestarBootstrapper.is_ready` at `litestar_bootstrapper.py:276`, `FastStreamBootstrapper.is_ready` at `faststream_bootstrapper.py:186`, `FreeBootstrapper.is_ready` in `free_bootstrapper.py`, `FastMcpBootstrapper.is_ready` in `fastmcp_bootstrapper.py`, and the abstract `BaseBootstrapper.is_ready`). No instrument-level matches.

---

## Task 5: Rewrite `BaseBootstrapper` flow

**File:** `lite_bootstrap/bootstrappers/base.py`

- [ ] **Step 1: Remove `InstrumentNotReadyWarning` import**

Find (lines 6-11):

```python
from lite_bootstrap.exceptions import (
    BootstrapperNotReadyError,
    InstrumentDependencyMissingWarning,
    InstrumentNotReadyWarning,
    TeardownError,
)
```

Replace with:

```python
from lite_bootstrap.exceptions import (
    BootstrapperNotReadyError,
    InstrumentDependencyMissingWarning,
    TeardownError,
)
```

- [ ] **Step 2: Inline the new flow in `__init__` and add `skipped_instruments` attribute**

Find the existing class header + `__init__` + `_register_or_skip` (lines 27-64):

```python
class BaseBootstrapper(abc.ABC, typing.Generic[ApplicationT]):
    instruments_types: typing.ClassVar[list[type[BaseInstrument]]]
    instruments: list[BaseInstrument]
    bootstrap_config: BaseConfig

    def __init__(self, bootstrap_config: BaseConfig) -> None:
        self.is_bootstrapped = False
        if not self.is_ready():
            msg = f"{type(self).__name__} is not ready: {self.not_ready_message}"
            raise BootstrapperNotReadyError(msg)

        self.bootstrap_config = bootstrap_config
        self.instruments = []
        for instrument_type in self.instruments_types:
            if (instrument := self._register_or_skip(instrument_type)) is not None:
                self.instruments.append(instrument)

    def _register_or_skip(self, instrument_type: type[BaseInstrument]) -> BaseInstrument | None:
        # Check dependencies before instantiation: an instrument's __init__
        # may reference symbols gated behind an optional import (e.g. a
        # default_factory that calls into the missing package), which would
        # raise NameError before the check_dependencies skip could run.
        if not instrument_type.check_dependencies():
            warnings.warn(
                instrument_type.missing_dependency_message,
                category=InstrumentDependencyMissingWarning,
                stacklevel=4,
            )
            return None
        instrument = instrument_type(bootstrap_config=self.bootstrap_config)
        if not instrument.is_ready():
            warnings.warn(
                f"{instrument_type.__name__} is not ready: {instrument.not_ready_message}",
                category=InstrumentNotReadyWarning,
                stacklevel=4,
            )
            return None
        return instrument
```

Replace with:

```python
class BaseBootstrapper(abc.ABC, typing.Generic[ApplicationT]):
    instruments_types: typing.ClassVar[list[type[BaseInstrument]]]
    instruments: list[BaseInstrument]
    skipped_instruments: list[tuple[type[BaseInstrument], str]]
    bootstrap_config: BaseConfig

    def __init__(self, bootstrap_config: BaseConfig) -> None:
        self.is_bootstrapped = False
        if not self.is_ready():
            msg = f"{type(self).__name__} is not ready: {self.not_ready_message}"
            raise BootstrapperNotReadyError(msg)

        self.bootstrap_config = bootstrap_config
        self.instruments = []
        self.skipped_instruments = []
        for instrument_type in self.instruments_types:
            # Config-level skip first: silent (no warning). Runs before instantiation so a
            # missing-optional-dep doesn't fail in a dataclass default_factory before we
            # can decide the user opted out.
            if not instrument_type.is_configured(self.bootstrap_config):
                self.skipped_instruments.append((instrument_type, instrument_type.not_ready_message))
                continue
            # Dep-missing for a CONFIGURED instrument is a genuine deployment surprise.
            if not instrument_type.check_dependencies():
                warnings.warn(
                    instrument_type.missing_dependency_message,
                    category=InstrumentDependencyMissingWarning,
                    stacklevel=3,
                )
                continue
            self.instruments.append(instrument_type(bootstrap_config=self.bootstrap_config))

        logger.info(
            f"{type(self).__name__}: "
            f"configured={[type(i).__name__ for i in self.instruments]}, "
            f"skipped={[(cls.__name__, reason) for cls, reason in self.skipped_instruments]}"
        )
```

Five changes:
1. Add `skipped_instruments: list[tuple[type[BaseInstrument], str]]` class-level annotation.
2. Initialize `self.skipped_instruments = []` in `__init__`.
3. Inline the new flow: `is_configured` first (silent skip + append to skipped_instruments), then `check_dependencies` (warning, no skipped_instruments entry), then instantiate.
4. Delete the `_register_or_skip` helper method entirely.
5. Emit one `logger.info(...)` summary after the loop.

The `stacklevel=3` is reduced from `stacklevel=4` because the warning call is now in `__init__` directly (one fewer frame than via `_register_or_skip`).

The `logger` reference is the existing module-level logger declared at line 16-21 (structlog if available, stdlib otherwise) — no new import needed.

The `not_ready_message` is accessed on the **class** (not an instance), since `is_configured` runs without instantiation.

- [ ] **Step 3: Smoke check — bootstrapper module imports cleanly**

```bash
uv run python -c "from lite_bootstrap.bootstrappers.base import BaseBootstrapper; print('ok')"
```

Expected: `ok`. If `ImportError: cannot import name 'InstrumentNotReadyWarning'` — Task 5 Step 1 wasn't applied.

---

## Task 6: Migrate tests to new API

Six test files. Mechanical `is_ready()` → `is_configured(config)` migration plus the `test_free_bootstrap_logging_disabled` rewrite.

- [ ] **Step 1: `tests/instruments/test_cors_instrument.py`**

The file has several `instrument.is_ready()` calls. Find each `assert instrument.is_ready()` and `assert not instrument.is_ready()` pattern and rewrite to use the classmethod on the config used.

Concretely, the pattern:

```python
def test_cors_instrument_not_ready_without_origins_or_regex() -> None:
    instrument = CorsInstrument(bootstrap_config=CorsConfig())
    assert not instrument.is_ready()
    assert instrument.not_ready_message == "cors_allowed_origins or cors_allowed_origin_regex must be provided"
```

becomes:

```python
def test_cors_instrument_not_configured_without_origins_or_regex() -> None:
    config = CorsConfig()
    assert not CorsInstrument.is_configured(config)
    assert CorsInstrument.not_ready_message == "cors_allowed_origins or cors_allowed_origin_regex must be provided"
```

Apply the same pattern to all `is_ready()` calls in the file. Rename the test function from `*_not_ready_*` to `*_not_configured_*` (and `*_ready_*` to `*_configured_*` for positive cases) to match the new semantics.

- [ ] **Step 2: `tests/instruments/test_healthchecks_instrument.py`**

Same pattern. Rename `*_ready_*` → `*_configured_*`. Construct config, pass to `HealthChecksInstrument.is_configured(config)`.

- [ ] **Step 3: `tests/instruments/test_prometheus_instrument.py`**

Same pattern. Use `PrometheusInstrument.is_configured(config)`.

- [ ] **Step 4: `tests/instruments/test_pyroscope_instrument.py`**

Same pattern. Use `PyroscopeInstrument.is_configured(config)`.

- [ ] **Step 5: `tests/instruments/test_swagger_instrument.py`**

Same pattern. Use `SwaggerInstrument.is_configured(config)`. (The default returns True, so positive cases simply assert True.)

- [ ] **Step 6: `tests/test_free_bootstrap.py::test_free_bootstrap_logging_disabled`**

Find the current test:

```python
def test_free_bootstrap_logging_disabled() -> None:
    with pytest.warns(InstrumentNotReadyWarning) as records:
        FreeBootstrapper(
            bootstrap_config=FreeBootstrapperConfig(
                logging_enabled=False,
                opentelemetry_instrumentors=[CustomInstrumentor()],
                opentelemetry_log_traces=True,
                sentry_dsn="https://testdsn@localhost/1",
                sentry_additional_params={"transport": SentryTestTransport()},
                logging_buffer_capacity=0,
            ),
        )
    messages = [str(r.message) for r in records]
    assert "LoggingInstrument is not ready: logging_enabled is False" in messages
    assert "PyroscopeInstrument is not ready: pyroscope_endpoint is empty" in messages
```

Replace with:

```python
def test_free_bootstrap_logging_disabled() -> None:
    bootstrapper = FreeBootstrapper(
        bootstrap_config=FreeBootstrapperConfig(
            logging_enabled=False,
            opentelemetry_instrumentors=[CustomInstrumentor()],
            opentelemetry_log_traces=True,
            sentry_dsn="https://testdsn@localhost/1",
            sentry_additional_params={"transport": SentryTestTransport()},
            logging_buffer_capacity=0,
        ),
    )
    skipped_classes = {cls for cls, _ in bootstrapper.skipped_instruments}
    assert LoggingInstrument in skipped_classes
    assert PyroscopeInstrument in skipped_classes
```

Also at the top of the file:
- Add `from lite_bootstrap.instruments.logging_instrument import LoggingInstrument`
- Add `from lite_bootstrap.instruments.pyroscope_instrument import PyroscopeInstrument`
- Remove `InstrumentNotReadyWarning` from the `from lite_bootstrap import (...)` import block

- [ ] **Step 7: Verify all instrument tests pass**

```bash
just test -- tests/instruments/ tests/test_free_bootstrap.py -v
```

Expected: all pass. If any test references `is_ready()` it's a missed migration — fix and re-run.

---

## Task 7: Add summary-log test

- [ ] **Step 1: Append to `tests/test_free_bootstrap.py`**

Add:

```python
def test_free_bootstrap_emits_summary_log(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="lite_bootstrap.bootstrappers.base"):
        FreeBootstrapper(
            bootstrap_config=FreeBootstrapperConfig(
                sentry_dsn="https://testdsn@localhost/1",
                sentry_additional_params={"transport": SentryTestTransport()},
            ),
        )
    summary_records = [r for r in caplog.records if "FreeBootstrapper" in r.getMessage()]
    assert summary_records, "expected a summary log line mentioning FreeBootstrapper"
    summary = summary_records[-1].getMessage()
    assert "configured=" in summary
    assert "skipped=" in summary
```

Also add `import logging` at the top if not already present, and add `pytest` to imports if needed (already in test_free_bootstrap.py as `import pytest`).

- [ ] **Step 2: Run the new test**

```bash
just test -- tests/test_free_bootstrap.py::test_free_bootstrap_emits_summary_log -v
```

Expected: PASS.

---

## Task 8: Remove `InstrumentNotReadyWarning` class

- [ ] **Step 1: `lite_bootstrap/exceptions.py`**

Find (lines 30-31 approx):

```python
class InstrumentNotReadyWarning(InstrumentSkippedWarning):
    """Emitted when an instrument is skipped because its config indicates it should not run."""
```

Delete those two lines and the blank line immediately before/after as appropriate. Make sure `InstrumentSkippedWarning` and `InstrumentDependencyMissingWarning` definitions remain.

- [ ] **Step 2: `lite_bootstrap/__init__.py`**

Find and update the import block (lines 6-14 approx):

```python
from lite_bootstrap.exceptions import (
    BootstrapperNotReadyError,
    ConfigurationError,
    InstrumentDependencyMissingWarning,
    InstrumentNotReadyWarning,
    InstrumentSkippedWarning,
    LiteBootstrapError,
    TeardownError,
)
```

Remove the `InstrumentNotReadyWarning,` line so it becomes:

```python
from lite_bootstrap.exceptions import (
    BootstrapperNotReadyError,
    ConfigurationError,
    InstrumentDependencyMissingWarning,
    InstrumentSkippedWarning,
    LiteBootstrapError,
    TeardownError,
)
```

Find the `__all__` list and remove `"InstrumentNotReadyWarning",` (alphabetically between `InstrumentDependencyMissingWarning` and `InstrumentSkippedWarning`).

- [ ] **Step 3: Sanity grep — no leftover references**

```bash
grep -rn "InstrumentNotReadyWarning" lite_bootstrap/ tests/ --include="*.py"
```

Expected: zero matches. If any remain, they're missed migrations.

- [ ] **Step 4: Full test suite**

```bash
just test
```

Expected: all tests pass. Existing dep-missing tests (e.g., `test_fastapi_bootstrapper_with_missing_instrument_dependency`) still fire `InstrumentDependencyMissingWarning` and continue to pass.

```bash
just lint
```

Expected: clean. The `_register_or_skip` removal also removes any reference to its name; no orphan symbols.

---

## Task 9: Update docs

- [ ] **Step 1: `CLAUDE.md` — update Optional dependencies design-decision bullet**

Find the "Key design decisions" section, the bullet starting with `**Optional dependencies**:`. Append after the existing sentence about Pyright (or replace the trailing static-analyzer note):

Add a new bullet immediately after the "Optional dependencies" one:

```markdown
- **Instrument skip ordering**: `BaseBootstrapper.__init__` runs `instrument_type.is_configured(config)` first (silent skip if the user's config indicates the instrument shouldn't run — populates `bootstrapper.skipped_instruments`); then `check_dependencies()` (emits `InstrumentDependencyMissingWarning` only for configured-but-dep-missing — the genuine deployment surprise); then instantiates. One `logger.info` summary line at the end lists configured + skipped instruments.
```

- [ ] **Step 2: `docs/introduction/configuration.md` — revise the warning-subclasses section**

Open the file and locate the section that PR #86 introduced (search for `InstrumentNotReadyWarning` or `InstrumentSkippedWarning`). This section documents how users can filter / capture the warning subclasses.

Replace the section content with text reflecting the new behavior:
- Only `InstrumentDependencyMissingWarning` is emitted by the bootstrapper.
- It fires only when the instrument is configured AND its optional dependency is missing.
- Instruments skipped due to config (`is_configured` False) appear in `bootstrapper.skipped_instruments: list[tuple[type, str]]` and in the INFO-level summary log.

Keep `InstrumentSkippedWarning` as the documented base for forward-compatibility (if additional skip categories arise in future).

Remove any code samples referencing `InstrumentNotReadyWarning`.

- [ ] **Step 3: Verify docs build**

```bash
uv run --with mkdocs --with mkdocs-material mkdocs build --strict > /dev/null 2>&1; echo "exit: $?"
```

Expected: `exit: 0`. (The audit's earlier docs/superpowers/ exclusion remains in mkdocs.yml.)

---

## Task 10: Final verification and commit

- [ ] **Step 1: Run the full test suite once more**

```bash
just test
```

Expected: all pass (count = 129 prior + 1 new summary-log test = 130).

- [ ] **Step 2: Run lint**

```bash
just lint
```

Expected: clean.

- [ ] **Step 3: Pre-flight grep for any leftover old-API references**

```bash
grep -rn "def is_ready\|\.is_ready(" lite_bootstrap/ tests/ --include="*.py" | grep -v "Bootstrapper\b"
```

Expected: only the abstract `def is_ready(self) -> bool: ...` on `BaseBootstrapper` (line 74) and the bootstrapper-level overrides in framework files. Any instrument-level match is a missed migration.

```bash
grep -rn "InstrumentNotReadyWarning" .
```

Expected: only matches in `docs/superpowers/specs/` and `docs/superpowers/plans/` (this plan and the spec). Production code and tests should have zero matches.

- [ ] **Step 4: Commit**

Stage all touched files explicitly:

```bash
git add \
  lite_bootstrap/instruments/base.py \
  lite_bootstrap/instruments/cors_instrument.py \
  lite_bootstrap/instruments/healthchecks_instrument.py \
  lite_bootstrap/instruments/logging_instrument.py \
  lite_bootstrap/instruments/opentelemetry_instrument.py \
  lite_bootstrap/instruments/prometheus_instrument.py \
  lite_bootstrap/instruments/pyroscope_instrument.py \
  lite_bootstrap/instruments/sentry_instrument.py \
  lite_bootstrap/bootstrappers/base.py \
  lite_bootstrap/bootstrappers/faststream_bootstrapper.py \
  lite_bootstrap/bootstrappers/litestar_bootstrapper.py \
  lite_bootstrap/exceptions.py \
  lite_bootstrap/__init__.py \
  tests/test_free_bootstrap.py \
  tests/instruments/test_cors_instrument.py \
  tests/instruments/test_healthchecks_instrument.py \
  tests/instruments/test_prometheus_instrument.py \
  tests/instruments/test_pyroscope_instrument.py \
  tests/instruments/test_swagger_instrument.py \
  CLAUDE.md \
  docs/introduction/configuration.md
git commit -m "$(cat <<'EOF'
refactor: replace InstrumentNotReadyWarning with is_configured classmethod + summary log

PR #86 introduced InstrumentNotReadyWarning, escalating the not-ready
skip path from a (silently dropped) logger.info call to a real
warnings.warn. The escalation surfaced expected-path events as
warnings: every service using a subset of available instruments emits
N warnings on bootstrap, and lite-bootstrap's own tests can't suppress
without breaking the warning assertions.

Replace is_ready (instance method, ran after instantiation) with
is_configured (classmethod taking config, runs before instantiation).
The bootstrapper now:

1. is_configured(config) False → silent skip; append to new
   bootstrapper.skipped_instruments: list[tuple[type, str]].
2. check_dependencies() False → InstrumentDependencyMissingWarning
   (kept; this is the genuine "configured but dep missing" deployment
   surprise).
3. Otherwise instantiate and register.

After the loop, emit one INFO-level summary log listing configured +
skipped instruments. Default Python logging suppresses INFO, so silent
by default with an opt-in path via logging.basicConfig.

PR #88's constraint (check_dependencies before instantiation, because
some instruments have default_factory that NameErrors when optional
extras aren't installed) is preserved: is_configured is a classmethod,
so it runs without instantiation.

Removed:
- InstrumentNotReadyWarning class (hard removal; 4 weeks old; exports
  go too)
- BaseInstrument.is_ready instance method (replaced by is_configured)
- The _register_or_skip helper (flow inlined)
- The dead `import_checker.is_prometheus_client_installed` conjunct in
  FastStreamPrometheusInstrument.is_configured (covered by
  check_dependencies()).

Kept:
- InstrumentSkippedWarning (base for forward-compat)
- InstrumentDependencyMissingWarning (still useful for the genuine
  deployment surprise)
- not_ready_message class attribute (used in skipped_instruments
  tuples and the summary log)
- Bootstrapper-level is_ready methods (framework availability checks;
  unrelated)

Tests migrated to call XInstrument.is_configured(config) instead of
instrument.is_ready(). test_free_bootstrap_logging_disabled rewritten
to assert on bootstrapper.skipped_instruments. New
test_free_bootstrap_emits_summary_log pins the summary log behavior
via caplog.

Closes design doc 2026-06-01-instrument-skip-rework-design.md.
EOF
)"
```

---

## Task 11: Push + open PR

- [ ] **Step 1: Push**

```bash
git push -u origin refactor/instrument-skip-rework
```

- [ ] **Step 2: Open PR**

```bash
gh pr create --title "refactor: replace InstrumentNotReadyWarning with is_configured classmethod + summary log" --body "$(cat <<'EOF'
## Summary
Replaces the post-PR-#86 `InstrumentNotReadyWarning` (which fired on every config-opt-out path, generating noise in every service) with a pre-instantiation `is_configured` classmethod check, structured `bootstrapper.skipped_instruments` introspection, and one INFO-level summary log.

- `is_ready` (instance method) → `is_configured` (classmethod taking config). Runs **before** `check_dependencies()`, before instantiation — preserves PR #88's no-instantiation-on-missing-dep constraint.
- `InstrumentNotReadyWarning` removed. Skipped-due-to-config is silent; appears in `bootstrapper.skipped_instruments: list[tuple[type, str]]`.
- `InstrumentDependencyMissingWarning` retained and now fires ONLY for genuine deployment surprises (instrument is configured but its optional package is missing).
- One `logger.info(...)` summary at the end of `__init__` lists `configured=[...]` and `skipped=[...]`. Default Python logging suppresses INFO so silent by default.

15 production files modified, 6 test files migrated, 2 docs updated. Bootstrapper-level `is_ready` methods (framework availability checks like "fastapi is not installed") are unchanged.

Closes design `docs/superpowers/specs/2026-06-01-instrument-skip-rework-design.md`.

## Backward compatibility
- `InstrumentNotReadyWarning` is publicly exported and is **hard-removed**. Users importing the name will get `ImportError`. 4 weeks old (PR #86); acceptable churn.
- `is_ready` instance method on instruments is removed. User code calling `instrument.is_ready()` migrates to `type(instrument).is_configured(config)`. Library-internal lifecycle; rare in user code.

## Test plan
- [x] `just test` — full suite (130 expected; 129 prior + 1 new summary-log test).
- [x] `just lint` — clean.
- [x] Existing dep-missing tests (`test_*_bootstrapper_with_missing_instrument_dependency`) still pass: `InstrumentDependencyMissingWarning` continues to fire for the configured + dep-missing case.
- [ ] Reviewer: confirm the inline `__init__` flow correctly populates `skipped_instruments` only for `is_configured`-False instruments (not for dep-missing ones, which only get the warning).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review

Spec coverage check against `docs/superpowers/specs/2026-06-01-instrument-skip-rework-design.md`:

| Spec section | Task |
|--------------|------|
| API change: `is_configured` classmethod replaces `is_ready` | Task 2 (base) + Task 3 (8 instruments) + Task 4 (3 framework overrides) |
| Bootstrapper flow reorder (is_configured → check_dependencies → instantiate) | Task 5, Step 2 |
| `skipped_instruments` attribute | Task 5, Step 2 |
| Summary log | Task 5, Step 2 |
| `is_ready` instance method removed | Task 2, Task 3, Task 4 |
| `not_ready_message` retained as class attribute | (preserved by inaction — no edits to this field across the migration) |
| `InstrumentNotReadyWarning` class removed | Task 8, Step 1 |
| `__init__.py` export removed | Task 8, Step 2 |
| Existing dep-missing tests continue to work | Task 10, Step 1 (verified by full test run) |
| New test: summary log via caplog | Task 7 |
| `test_free_bootstrap_logging_disabled` rewritten | Task 6, Step 6 |
| Instrument tests migrated (5 files from PR10) | Task 6, Steps 1-5 |
| Docs: `docs/introduction/configuration.md` | Task 9, Step 2 |
| Docs: `CLAUDE.md` | Task 9, Step 1 |
| Pre-flight grep | "Pre-flight grep verification" section + Task 4 Step 4 + Task 8 Step 3 + Task 10 Step 3 |

All spec items have a corresponding task. No placeholders.

Type consistency check: `is_configured(cls, bootstrap_config: ConfigT) -> bool` is the signature used throughout (Task 2 introduces, Task 3/4 apply). `skipped_instruments: list[tuple[type[BaseInstrument], str]]` is the type used in Task 5's class annotation and the test reads it as `{cls for cls, _ in bootstrapper.skipped_instruments}` (Task 6 Step 6).

Cross-PR awareness: the `import_checker.is_prometheus_client_installed` conjunct dropped in Task 4 Step 2 is documented in the audit as DES-5; this PR opportunistically completes that cleanup since the migration is touching the same method body.

Risk assessment: medium. The change is mechanical but cross-cutting (~20 files). The full test suite is the safety net. If a single instrument's `is_configured` migration is wrong (e.g., typo in field name), only that instrument's tests fail — no cascade. The bootstrapper flow change is the highest-risk single point; Task 5's smoke test catches the import case, full-suite run catches the behavioral case.
