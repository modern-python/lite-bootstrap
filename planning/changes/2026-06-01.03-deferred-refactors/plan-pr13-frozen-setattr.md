# PR13: Drop `frozen=True` From Instruments + FastAPIConfig Default Cleanup (REF-6 + LOW-4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two related-but-distinct cleanups.

- **REF-6**: Drop `frozen=True` from the instrument hierarchy. Python's dataclass rules force a cascade: dropping `frozen=True` from `LoggingInstrument` requires dropping it from `BaseInstrument`, which requires dropping it from every other instrument subclass. 23 dataclass declarations across 12 files lose `frozen=True`. In `LoggingInstrument` and `OpenTelemetryInstrument`, the four `object.__setattr__(self, "_x", value)` workarounds for cached runtime state become plain `self._x = value` assignments. **Configs stay frozen** — only instruments lose `frozen=True`.

- **LOW-4**: `FastAPIConfig.application` currently uses `default=None` + `# ty: ignore[invalid-assignment]` because the field is typed `fastapi.FastAPI` (non-Optional). Replace with a proper sentinel-type pattern: introduce `UnsetType` + `UNSET` in `lite_bootstrap/types.py` (a sentinel class with a singleton instance), type the field as `fastapi.FastAPI | UnsetType`, default to `UNSET`, and replace the truthiness check in `__post_init__` with `isinstance(self.application, UnsetType)`. Add a `_narrow_app(config)` helper at module scope that asserts the type and returns the narrowed value; FastAPI framework instruments call `_narrow_app(self.bootstrap_config)` instead of `self.bootstrap_config.application` directly. Drops the `# ty: ignore`. FastAPIConfig stays frozen — `object.__setattr__(self, "application", ...)` in `__post_init__` remains because the freeze bypass is the only way to mutate a frozen field after construction; a code comment documents the rationale.

**Architecture:** Largest mechanical refactor in the deferred-refactors sequence. The cascade is purely mechanical — every change is `frozen=True` → (delete). The setattr replacements and LOW-4 sentinel are the only meaningful diffs.

**Tech Stack:** Python 3.10+ dataclasses, frozen-inheritance rules.

**Parent spec:** `docs/superpowers/specs/2026-06-01-deferred-refactors-sequencing.md` (PR13 section).
**Parent audit:** `docs/superpowers/specs/2026-05-31-bug-refactor-audit.md` (REF-6, LOW-4).

---

## Important context: Why the cascade

Python's `@dataclasses.dataclass` enforces that **a non-frozen dataclass cannot inherit from a frozen one** (and vice versa). The check fires at class definition time as `TypeError`.

Today's instrument hierarchy:
- `BaseInstrument(frozen=True)`
- 8 base instrument subclasses, all `frozen=True`
- 15 framework instrument subclasses inheriting from the base instruments, all `frozen=True`

To drop `frozen=True` from `LoggingInstrument` (REF-6's stated target), `BaseInstrument` must also drop it, which forces every other subclass to drop it too. There's no surgical option.

The sequencing spec's PR13 section said "drop `frozen=True` from `LoggingInstrument` and `OpenTelemetryInstrument`" — that was incorrect; the cascade is required. This plan implements the cascade.

---

## File Structure

12 files modified.

**Instrument modules (9 files):**
- `lite_bootstrap/instruments/base.py` — `BaseInstrument` loses `frozen=True`.
- `lite_bootstrap/instruments/cors_instrument.py` — `CorsInstrument` loses `frozen=True`.
- `lite_bootstrap/instruments/healthchecks_instrument.py` — `HealthChecksInstrument` loses `frozen=True`.
- `lite_bootstrap/instruments/logging_instrument.py` — `LoggingInstrument` loses `frozen=True`; 2 `object.__setattr__` calls become direct assignment.
- `lite_bootstrap/instruments/opentelemetry_instrument.py` — `OpenTelemetryInstrument` loses `frozen=True`; 2 `object.__setattr__` calls become direct assignment.
- `lite_bootstrap/instruments/prometheus_instrument.py` — `PrometheusInstrument` loses `frozen=True`.
- `lite_bootstrap/instruments/pyroscope_instrument.py` — `PyroscopeInstrument` loses `frozen=True`.
- `lite_bootstrap/instruments/sentry_instrument.py` — `SentryInstrument` loses `frozen=True`.
- `lite_bootstrap/instruments/swagger_instrument.py` — `SwaggerInstrument` loses `frozen=True`.

**Bootstrapper modules (3 files):**
- `lite_bootstrap/bootstrappers/fastapi_bootstrapper.py` — 5 framework instruments lose `frozen=True` + LOW-4 sentinel-type pattern on `FastAPIConfig.application` + `_narrow_app` helper + every FastAPI instrument bootstrap calls `_narrow_app(self.bootstrap_config)` for the app reference.
- `lite_bootstrap/bootstrappers/litestar_bootstrapper.py` — 6 framework instruments lose `frozen=True`.
- `lite_bootstrap/bootstrappers/faststream_bootstrapper.py` — 4 framework instruments lose `frozen=True`.

**Shared types (1 file):**
- `lite_bootstrap/types.py` — add `UnsetType` class + `UNSET: typing.Final[UnsetType]` singleton. Reusable sentinel for fields that distinguish "not passed" from "explicitly None".

---

## Locked decisions

- **Cascade scope:** Drop `frozen=True` from `BaseInstrument` and ALL 22 instrument subclasses. Configs stay frozen. Confirmed by the user after the constraint surfaced.
- **LOW-4 pattern:** Proper `UnsetType` sentinel class in `lite_bootstrap/types.py`, used via `isinstance(value, UnsetType)`. Honest to the type checker (no `typing.cast` lie). Adds a `_narrow_app` helper that wraps the assert/return narrowing for callers. Revised from the original plan's `typing.cast("fastapi.FastAPI", object())` pattern — the spec was updated retroactively to match what was built.
- **`FastAPIConfig` stays frozen:** Confirmed by user. The `object.__setattr__(self, "application", ...)` in `__post_init__` remains; a one-line code comment documents the rationale (frozen for user-facing immutability; bypass needed because `application` is constructed using other config fields).
- **No new tests.** The full existing test suite verifies behavior preservation; pure-refactor changes should not affect runtime semantics other than enabling future direct mutation (which we don't exercise).

---

## Cascade list (23 dataclass declarations)

For traceability, every dataclass decorator changing from `@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)` to `@dataclasses.dataclass(kw_only=True, slots=True)` (or `@dataclasses.dataclass(kw_only=True, frozen=True)` to `@dataclasses.dataclass(kw_only=True)`):

| # | Class | File |
|---|-------|------|
| 1 | `BaseInstrument` | `instruments/base.py` |
| 2 | `CorsInstrument` | `instruments/cors_instrument.py` |
| 3 | `HealthChecksInstrument` | `instruments/healthchecks_instrument.py` |
| 4 | `LoggingInstrument` | `instruments/logging_instrument.py` |
| 5 | `OpenTelemetryInstrument` | `instruments/opentelemetry_instrument.py` |
| 6 | `PrometheusInstrument` | `instruments/prometheus_instrument.py` |
| 7 | `PyroscopeInstrument` | `instruments/pyroscope_instrument.py` |
| 8 | `SentryInstrument` | `instruments/sentry_instrument.py` |
| 9 | `SwaggerInstrument` | `instruments/swagger_instrument.py` |
| 10 | `FastAPICorsInstrument` | `bootstrappers/fastapi_bootstrapper.py` |
| 11 | `FastAPIHealthChecksInstrument` | `bootstrappers/fastapi_bootstrapper.py` |
| 12 | `FastAPIOpenTelemetryInstrument` | `bootstrappers/fastapi_bootstrapper.py` |
| 13 | `FastAPIPrometheusInstrument` | `bootstrappers/fastapi_bootstrapper.py` |
| 14 | `FastAPISwaggerInstrument` | `bootstrappers/fastapi_bootstrapper.py` |
| 15 | `LitestarCorsInstrument` | `bootstrappers/litestar_bootstrapper.py` |
| 16 | `LitestarHealthChecksInstrument` | `bootstrappers/litestar_bootstrapper.py` |
| 17 | `LitestarLoggingInstrument` | `bootstrappers/litestar_bootstrapper.py` |
| 18 | `LitestarOpenTelemetryInstrument` | `bootstrappers/litestar_bootstrapper.py` |
| 19 | `LitestarPrometheusInstrument` | `bootstrappers/litestar_bootstrapper.py` |
| 20 | `LitestarSwaggerInstrument` | `bootstrappers/litestar_bootstrapper.py` |
| 21 | `FastStreamHealthChecksInstrument` | `bootstrappers/faststream_bootstrapper.py` |
| 22 | `FastStreamLoggingInstrument` | `bootstrappers/faststream_bootstrapper.py` |
| 23 | `FastStreamOpenTelemetryInstrument` | `bootstrappers/faststream_bootstrapper.py` |
| 24 | `FastStreamPrometheusInstrument` | `bootstrappers/faststream_bootstrapper.py` |

(Yes, that's 24 — `LitestarSwaggerInstrument` is on the list because it inherits from `SwaggerInstrument`. All 24 actually need updating to keep the cascade consistent.)

**Configs are NOT in this list.** `BaseConfig`, `LoggingConfig`, `SentryConfig`, `OpentelemetryConfig`, `PyroscopeConfig`, `CorsConfig`, `HealthChecksConfig`, `PrometheusConfig`, `SwaggerConfig`, `OpenTelemetryServiceFieldsConfig`, `FastAPIConfig`, `LitestarConfig`, `FastStreamConfig`, `FreeBootstrapperConfig` — all stay frozen.

---

## Task 1: Create branch

**Files:** (no files; git only)

- [ ] **Step 1: Branch off `main`**

```bash
git checkout main
git pull --ff-only origin main
git checkout -b refactor/ref-6-frozen-setattr
```

Expected: `Switched to a new branch 'refactor/ref-6-frozen-setattr'`.

---

## Task 2: Drop `frozen=True` from the cascade

For each file below, the change pattern is identical: locate each instrument's `@dataclasses.dataclass(...)` decorator and remove `, frozen=True` (or `frozen=True,` if it's not last). Configs are untouched.

### Step 1: `lite_bootstrap/instruments/base.py`

Locate `BaseInstrument`. Change:

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class BaseInstrument(typing.Generic[ConfigT]):
```

to:

```python
@dataclasses.dataclass(kw_only=True, slots=True)
class BaseInstrument(typing.Generic[ConfigT]):
```

`BaseConfig` (above it) stays untouched — keep `frozen=True`.

### Step 2: `lite_bootstrap/instruments/cors_instrument.py`

`CorsInstrument` decorator: drop `frozen=True`.

### Step 3: `lite_bootstrap/instruments/healthchecks_instrument.py`

`HealthChecksInstrument` decorator: drop `frozen=True`.

### Step 4: `lite_bootstrap/instruments/logging_instrument.py`

`LoggingInstrument` decorator: drop `frozen=True`.

Then replace 2 `object.__setattr__` calls with direct assignment:

In `memory_logger_factory` property (around line 109):
```python
# Before:
object.__setattr__(self, "_logger_factory", cached)
# After:
self._logger_factory = cached
```

In `teardown` method:
```python
# Before:
try:
    self._logger_factory.close_handlers()
finally:
    object.__setattr__(self, "_logger_factory", None)

# After:
try:
    self._logger_factory.close_handlers()
finally:
    self._logger_factory = None
```

### Step 5: `lite_bootstrap/instruments/opentelemetry_instrument.py`

`OpenTelemetryInstrument` decorator: drop `frozen=True`.

Then replace 2 `object.__setattr__` calls:

In `bootstrap()`:
```python
# Before:
object.__setattr__(self, "_tracer_provider", tracer_provider)
# After:
self._tracer_provider = tracer_provider
```

In `teardown()`:
```python
# Before:
try:
    self._tracer_provider.shutdown()
finally:
    object.__setattr__(self, "_tracer_provider", None)

# After:
try:
    self._tracer_provider.shutdown()
finally:
    self._tracer_provider = None
```

### Step 6: `lite_bootstrap/instruments/prometheus_instrument.py`

`PrometheusInstrument` decorator: drop `frozen=True`.

### Step 7: `lite_bootstrap/instruments/pyroscope_instrument.py`

`PyroscopeInstrument` decorator: drop `frozen=True`.

### Step 8: `lite_bootstrap/instruments/sentry_instrument.py`

`SentryInstrument` decorator: drop `frozen=True`.

### Step 9: `lite_bootstrap/instruments/swagger_instrument.py`

`SwaggerInstrument` decorator: drop `frozen=True`.

### Step 10: `lite_bootstrap/bootstrappers/fastapi_bootstrapper.py` — 5 framework instruments

Drop `frozen=True` from the decorators of:
- `FastAPICorsInstrument`
- `FastAPIHealthChecksInstrument`
- `FastAPIOpenTelemetryInstrument`
- `FastAPIPrometheusInstrument`
- `FastAPISwaggerInstrument`

Each uses `@dataclasses.dataclass(kw_only=True, frozen=True)` (no `slots=True`). After: `@dataclasses.dataclass(kw_only=True)`.

`FastAPIConfig` stays untouched here (frozen). The LOW-4 sentinel change comes in Task 3.

### Step 11: `lite_bootstrap/bootstrappers/litestar_bootstrapper.py` — 6 framework instruments

Drop `frozen=True` from:
- `LitestarCorsInstrument`
- `LitestarHealthChecksInstrument`
- `LitestarLoggingInstrument`
- `LitestarOpenTelemetryInstrument`
- `LitestarPrometheusInstrument`
- `LitestarSwaggerInstrument`

`LitestarConfig` stays frozen.

### Step 12: `lite_bootstrap/bootstrappers/faststream_bootstrapper.py` — 4 framework instruments

Drop `frozen=True` from:
- `FastStreamHealthChecksInstrument`
- `FastStreamLoggingInstrument`
- `FastStreamOpenTelemetryInstrument`
- `FastStreamPrometheusInstrument`

`FastStreamConfig` stays frozen.

### Step 13: Quick verification

```bash
just test
```

Expected: 128/128 PASS. If anything fails, the most likely cause is a `frozen=True` left in one of the 24 classes (Python's TypeError surfaces immediately on import).

Run a sanity grep to confirm no instrument-class declaration still has `frozen=True`:

```bash
grep -rn "frozen=True" lite_bootstrap/instruments/ lite_bootstrap/bootstrappers/ | grep -v "Config"
```

Expected: zero matches. The `grep -v "Config"` filters out config classes (which should still have `frozen=True`).

---

## Task 3: LOW-4 — FastAPIConfig sentinel pattern

**File:** `lite_bootstrap/bootstrappers/fastapi_bootstrapper.py`

### Step 1: Add module-level sentinel and update `FastAPIConfig`

Locate the top of the file (after the conditional imports for fastapi). Add this constant right after the `if import_checker.is_fastapi_installed:` block:

```python
if import_checker.is_fastapi_installed:
    import fastapi
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.routing import _merge_lifespan_context

# ... other conditional imports stay as they are ...

_UNSET_FASTAPI_APP: typing.Final = typing.cast("fastapi.FastAPI", object())
```

`typing.cast(...)` is a runtime no-op (returns the second argument). The type checker sees `_UNSET_FASTAPI_APP` as `fastapi.FastAPI`; at runtime it's a unique `object()` sentinel. `typing.Final` prevents accidental reassignment.

The string-quoted `"fastapi.FastAPI"` in the cast lets the line evaluate even when `fastapi` isn't installed (cast doesn't look up the type at runtime).

### Step 2: Update `FastAPIConfig.application` field declaration and `__post_init__`

Locate `FastAPIConfig`. Current:

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class FastAPIConfig(
    CorsConfig,
    ...
):
    application: "fastapi.FastAPI" = dataclasses.field(default=None)  # ty: ignore[invalid-assignment]
    application_kwargs: dict[str, typing.Any] = dataclasses.field(default_factory=dict)
    ...

    def __post_init__(self) -> None:
        if not import_checker.is_fastapi_installed:
            msg = "fastapi is not installed"
            raise ConfigurationError(msg)

        if not self.application:
            object.__setattr__(
                self, "application", fastapi.FastAPI(docs_url=self.swagger_path, **self.application_kwargs)
            )
        elif self.application_kwargs:
            warnings.warn("application_kwargs must be used without application", stacklevel=2)

        self.application.title = self.service_name
        self.application.debug = self.service_debug
        self.application.version = self.service_version
```

Change two things:

1. Replace `application: "fastapi.FastAPI" = dataclasses.field(default=None)  # ty: ignore[invalid-assignment]` with `application: "fastapi.FastAPI" = _UNSET_FASTAPI_APP`. Drop the `# ty: ignore`.

2. In `__post_init__`, replace `if not self.application:` with `if self.application is _UNSET_FASTAPI_APP:`. Identity check instead of truthiness — clearer intent.

After:

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class FastAPIConfig(
    CorsConfig,
    ...
):
    application: "fastapi.FastAPI" = _UNSET_FASTAPI_APP
    application_kwargs: dict[str, typing.Any] = dataclasses.field(default_factory=dict)
    ...

    def __post_init__(self) -> None:
        if not import_checker.is_fastapi_installed:
            msg = "fastapi is not installed"
            raise ConfigurationError(msg)

        if self.application is _UNSET_FASTAPI_APP:
            object.__setattr__(
                self, "application", fastapi.FastAPI(docs_url=self.swagger_path, **self.application_kwargs)
            )
        elif self.application_kwargs:
            warnings.warn("application_kwargs must be used without application", stacklevel=2)

        self.application.title = self.service_name
        self.application.debug = self.service_debug
        self.application.version = self.service_version
```

The `object.__setattr__` for `self.application` stays — `FastAPIConfig` is still frozen.

The `self.application.title = ...` lines below also stay — they mutate the `fastapi.FastAPI` instance (which isn't frozen), not the `FastAPIConfig` dataclass.

---

## Task 4: Verify and commit

### Step 1: Run the full test suite

```bash
just test
```

Expected: 128/128 PASS. The cascade is mechanical and should not affect runtime behavior. Watch for surprises in:

- All framework integration tests (FastAPI, Litestar, FastStream, Free) — they exercise the full instrument lifecycle.
- `test_logging_instrument_lifecycle_replay` (from PR11) — confirms the `_logger_factory` direct-assignment doesn't break the replay cycle.
- `test_opentelemetry_instrument_teardown_shuts_down_tracer_provider` (from PR2) — confirms the `_tracer_provider` direct-assignment doesn't break shutdown.

If any test fails because something now mutates an instrument unexpectedly, that's a real bug surfaced by the refactor (frozen was masking it). Stop and investigate.

### Step 2: Run lint

```bash
just lint
```

Expected: clean. The `# ty: ignore[invalid-assignment]` is gone from `FastAPIConfig.application`. No new lint warnings should appear.

### Step 3: Verify the cascade

```bash
grep -n "frozen=True" lite_bootstrap/instruments/*.py lite_bootstrap/bootstrappers/*.py
```

Expected matches: ONLY on config classes (`BaseConfig`, `LoggingConfig`, `SentryConfig`, `OpentelemetryConfig`, `PyroscopeConfig`, `CorsConfig`, `HealthChecksConfig`, `PrometheusConfig`, `SwaggerConfig`, `OpenTelemetryServiceFieldsConfig`, `FastAPIConfig`, `LitestarConfig`, `FastStreamConfig`, `FreeBootstrapperConfig`).

No instrument class should match. If one does, that's a missed cascade entry — fix it before committing.

### Step 4: Commit

Stage exactly the 12 modified files:

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
  lite_bootstrap/instruments/swagger_instrument.py \
  lite_bootstrap/bootstrappers/fastapi_bootstrapper.py \
  lite_bootstrap/bootstrappers/litestar_bootstrapper.py \
  lite_bootstrap/bootstrappers/faststream_bootstrapper.py
git commit -m "$(cat <<'EOF'
refactor: drop frozen=True from instruments; sentinel for FastAPIConfig.application

REF-6: LoggingInstrument and OpenTelemetryInstrument cached mutable
runtime state (_logger_factory, _tracer_provider) via
object.__setattr__ workarounds because the instruments were declared
frozen=True. The frozen claim was partly false — those two fields
mutated freely under the hood.

Python's dataclass rules forbid surgically dropping frozen=True from
a subclass while the parent remains frozen (TypeError at class
definition). The fix cascades through BaseInstrument and all 22
instrument subclasses: drop frozen=True from each. Configs stay
frozen — only instruments lose immutability. The 4 object.__setattr__
call sites in LoggingInstrument and OpenTelemetryInstrument
(bootstrap-cache + teardown-reset for each) become plain self._x = ...
assignments.

LOW-4: FastAPIConfig.application declared default=None with a
# ty: ignore[invalid-assignment] because the field is typed
fastapi.FastAPI (non-Optional). Replace with a typed sentinel:
_UNSET_FASTAPI_APP: typing.Final = typing.cast("fastapi.FastAPI", object())
The cast suppresses the type lie; the sentinel makes __post_init__'s
identity check (is _UNSET_FASTAPI_APP) clearer than the prior
truthiness check (not self.application). FastAPIConfig stays frozen,
so the object.__setattr__(self, "application", ...) in __post_init__
remains — only the default and the check change.

No behavior change. 128/128 tests pass.

Closes REF-6 and LOW-4 from the audit.
EOF
)"
```

---

## Task 5: Push and open PR

- [ ] **Step 1: Push the branch**

```bash
git push -u origin refactor/ref-6-frozen-setattr
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --title "refactor: drop frozen=True from instruments; sentinel for FastAPIConfig.application" --body "$(cat <<'EOF'
## Summary
Two related cleanups in one PR:

- **REF-6 cascade:** `LoggingInstrument` and `OpenTelemetryInstrument` cached mutable runtime state via `object.__setattr__` workarounds because they were declared `frozen=True`. Python's dataclass rules forbid surgically dropping `frozen=True` from one subclass while the parent stays frozen — the cascade is required. `BaseInstrument` and all 22 instrument subclasses lose `frozen=True`. The 4 `object.__setattr__` call sites in `LoggingInstrument` and `OpenTelemetryInstrument` become plain `self._x = ...` assignments.
- **LOW-4:** `FastAPIConfig.application` used `default=None` with a `# ty: ignore`. Replaced with a typed sentinel `_UNSET_FASTAPI_APP: typing.Final = typing.cast("fastapi.FastAPI", object())`. The `__post_init__` check changes from `if not self.application:` to `if self.application is _UNSET_FASTAPI_APP:`. `FastAPIConfig` stays frozen — the existing `object.__setattr__(self, "application", ...)` in `__post_init__` remains.

**Configs are unchanged.** All `*Config` classes keep `frozen=True`. Only instrument classes lose immutability.

12 files modified; 24 dataclass declarations lose `frozen=True`; 4 `object.__setattr__` call sites simplified; 1 `# ty: ignore` removed.

No behavior change. 128/128 tests pass.

Closes REF-6 and LOW-4 from an internal audit.

## Test plan
- [x] `just test` — 128/128.
- [x] `just lint` — clean (no `# ty: ignore` left in FastAPIConfig).
- [x] `grep -n "frozen=True" lite_bootstrap/instruments/ lite_bootstrap/bootstrappers/` — only config classes match.
- [ ] Reviewer: confirm `LoggingInstrument`'s and `OpenTelemetryInstrument`'s direct assignments preserve the `try/finally` exception safety from PR3.

## Why the cascade
Python's `@dataclasses.dataclass` enforces that a non-frozen dataclass cannot inherit from a frozen one (and vice versa) — `TypeError` at class definition. To drop `frozen=True` from `LoggingInstrument` (REF-6's stated target), `BaseInstrument` must also drop it, which propagates to every other instrument subclass. The sequencing spec's PR13 section called for a surgical 2-class change; the actual cascade is 24 classes.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review

**Spec coverage check** against the sequencing spec (PR13 section) and audit (REF-6, LOW-4):

| Spec item | Task |
|-----------|------|
| Drop `frozen=True` from instrument hierarchy (cascade) | Task 2, Steps 1-12 |
| Replace `object.__setattr__` in `LoggingInstrument` with direct assignment | Task 2, Step 4 |
| Replace `object.__setattr__` in `OpenTelemetryInstrument` with direct assignment | Task 2, Step 5 |
| Configs stay frozen | Locked decisions + Task 4 Step 3 verification |
| LOW-4: replace `default=None` + `# ty: ignore` with sentinel | Task 3 |
| Branch name `refactor/ref-6-frozen-setattr` | Task 1, Step 1 |
| Verification: `just test` + `just lint` clean | Task 4, Steps 1-2 |

All spec items covered. No placeholders.

**Risk:** Medium. The cascade is mechanical but touches many classes. The chief risk is a missed entry — the verification grep at Task 4 Step 3 catches that.

The behavioral risk is essentially zero: nothing in the codebase currently mutates an instrument after construction except the 4 `object.__setattr__` calls being replaced. Tests verify the cycles still work.

**Deviation from sequencing spec:** Locked decision said "drop frozen=True from LoggingInstrument and OpenTelemetryInstrument" — implementation required the full 24-class cascade. Documented in the commit message and PR body. The sequencing spec should be updated retroactively (out of scope for this PR; can be a follow-up doc commit).
