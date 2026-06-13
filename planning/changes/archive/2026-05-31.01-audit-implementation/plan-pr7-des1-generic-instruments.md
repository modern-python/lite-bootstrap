# PR7: Make `BaseInstrument` Generic; Delete Pure-Annotation Subclasses

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the audit's DES-1 finding by deleting the four pure type-annotation framework subclasses that exist solely to narrow `bootstrap_config`. Make `BaseInstrument` generic in its config type so the base instruments can be parameterized (`LoggingInstrument(BaseInstrument[LoggingConfig])`); framework subclasses with real behavior keep their existing structure.

**Architecture revision from the sequencing spec:** The locked decision in the sequencing spec called for "dropping redundant `bootstrap_config:` annotations on kept subclasses." Working through the Python typing implications, this would require a **two-level generic** pattern (each base instrument carries its own bounded `TypeVar` so framework subclasses can re-parameterize). The complexity isn't worth it — the annotations on framework subclasses with real `bootstrap()` overrides are **not** redundant under a single-level-generic design; they provide essential type narrowing for framework-specific field access (e.g., `self.bootstrap_config.application` inside `FastAPICorsInstrument.bootstrap()`).

This plan implements the **simpler single-level-generic approach**: `BaseInstrument` is generic; each base instrument is concretely parameterized; framework subclasses with real bootstrap code keep their `bootstrap_config: FrameworkConfig` annotations. The deletion target remains the same — only the four pure-annotation subclasses go. This delivers the audit's stated goal (eliminating boilerplate) without the two-level-generic complexity.

**Tech Stack:** Python 3.10+ generics (`typing.TypeVar`, `typing.Generic`), frozen dataclasses with `slots=True`.

**Parent spec:** `docs/superpowers/specs/2026-05-31-audit-implementation-sequencing.md` (PR7 section).
**Parent audit:** `docs/superpowers/specs/2026-05-31-bug-refactor-audit.md` (DES-1).

---

## File Structure

12 files modified.

**Instruments (9 files — make each base instrument concretely parameterize the new generic `BaseInstrument`):**
- Modify: `lite_bootstrap/instruments/base.py` — `BaseInstrument` becomes generic `[ConfigT]`.
- Modify: `lite_bootstrap/instruments/cors_instrument.py` — `CorsInstrument(BaseInstrument[CorsConfig])`.
- Modify: `lite_bootstrap/instruments/healthchecks_instrument.py` — `HealthChecksInstrument(BaseInstrument[HealthChecksConfig])`.
- Modify: `lite_bootstrap/instruments/logging_instrument.py` — `LoggingInstrument(BaseInstrument[LoggingConfig])`.
- Modify: `lite_bootstrap/instruments/opentelemetry_instrument.py` — `OpenTelemetryInstrument(BaseInstrument[OpentelemetryConfig])`.
- Modify: `lite_bootstrap/instruments/prometheus_instrument.py` — `PrometheusInstrument(BaseInstrument[PrometheusConfig])`.
- Modify: `lite_bootstrap/instruments/pyroscope_instrument.py` — `PyroscopeInstrument(BaseInstrument[PyroscopeConfig])`.
- Modify: `lite_bootstrap/instruments/sentry_instrument.py` — `SentryInstrument(BaseInstrument[SentryConfig])`.
- Modify: `lite_bootstrap/instruments/swagger_instrument.py` — `SwaggerInstrument(BaseInstrument[SwaggerConfig])`.

In each of the above, the existing `bootstrap_config: <ConfigClass>` field declaration is **removed** — it's now provided by the generic parent.

**Bootstrappers (3 files — delete the 4 pure-annotation subclasses, update `instruments_types` lists to reference base names):**
- Modify: `lite_bootstrap/bootstrappers/fastapi_bootstrapper.py` — delete `FastAPILoggingInstrument` and `FastAPISentryInstrument`; replace their entries in `instruments_types` with `LoggingInstrument` / `SentryInstrument`.
- Modify: `lite_bootstrap/bootstrappers/litestar_bootstrapper.py` — delete `LitestarSentryInstrument`; replace entry with `SentryInstrument`.
- Modify: `lite_bootstrap/bootstrappers/faststream_bootstrapper.py` — delete `FastStreamSentryInstrument`; replace entry with `SentryInstrument`.

The `FreeBootstrapper` already uses the base instrument names directly — no changes needed there.

**Framework subclasses with real bootstrap code stay AS-IS** (their `bootstrap_config: <FrameworkConfig>` annotations are still useful for type narrowing). The list (15 subclasses kept):

- FastAPI: `FastAPICorsInstrument`, `FastAPIHealthChecksInstrument`, `FastAPIOpenTelemetryInstrument`, `FastAPIPrometheusInstrument`, `FastAPISwaggerInstrument`.
- Litestar: `LitestarCorsInstrument`, `LitestarHealthChecksInstrument`, `LitestarLoggingInstrument`, `LitestarOpenTelemetryInstrument`, `LitestarPrometheusInstrument`, `LitestarSwaggerInstrument`.
- FastStream: `FastStreamHealthChecksInstrument`, `FastStreamLoggingInstrument`, `FastStreamOpenTelemetryInstrument`, `FastStreamPrometheusInstrument`.

---

## Locked decisions (revised from sequencing spec)

- **Single-level generic:** `BaseInstrument` is generic; base instruments concretely parameterize. **Revised** from the sequencing spec's two-level approach.
- **Kept framework subclasses retain `bootstrap_config: <FrameworkConfig>` annotations.** **Revised** from "drop redundant annotations." Under single-level-generic, these are not redundant — they provide essential type narrowing for framework field access.
- **Deletions unchanged:** the four pure-annotation subclasses (`FastAPILoggingInstrument`, `FastAPISentryInstrument`, `LitestarSentryInstrument`, `FastStreamSentryInstrument`) still get deleted.
- **Pyroscope handling:** `PyroscopeInstrument` is used as-is across all bootstrappers (no framework subclass). It still gets parameterized as `PyroscopeInstrument(BaseInstrument[PyroscopeConfig])` for symmetry.
- **No new tests.** This is a behavior-preserving refactor; existing tests verify correctness.

---

## Cross-cutting concerns to verify during implementation

1. **Generic + slots + frozen dataclass interaction.** Python 3.10 has historically had subtle issues with `@dataclasses.dataclass(slots=True)` combined with `typing.Generic`. If `just test` or `just lint` (ty check) surfaces errors related to slot conflicts or generic metaclass issues on `BaseInstrument`, fall back to dropping `slots=True` from `BaseInstrument` only. Document the change.

2. **Field declaration removal.** When we remove `bootstrap_config: <ConfigClass>` from each base instrument's body, the dataclass machinery should inherit the parent's `bootstrap_config: ConfigT` declaration. Verify by running `just test` after each instrument file change — any broken instantiation will surface immediately.

3. **`instruments_types` ClassVar typing.** `BaseBootstrapper.instruments_types: typing.ClassVar[list[type[BaseInstrument]]]` — after `BaseInstrument` becomes generic, this becomes `list[type[BaseInstrument[Any]]]` semantically. Should still work because `type[BaseInstrument]` accepts subclasses regardless of parameterization. If `ty check` complains, may need to adjust the annotation.

4. **`abc.ABC` + `typing.Generic`.** `BaseInstrument(abc.ABC, typing.Generic[ConfigT])` requires the MRO to be: BaseInstrument → ABC → Generic → object. Both `abc.ABC` and `typing.Generic` are designed to work together, but verify the order doesn't break dataclass machinery.

---

## Task 1: Create branch

**Files:** (no files; git only)

- [ ] **Step 1: Branch off `main`**

```bash
git checkout main
git pull --ff-only origin main
git checkout -b refactor/des-1-generic-instruments
```

Expected: `Switched to a new branch 'refactor/des-1-generic-instruments'`.

This is the only PR in the sequence that uses the `refactor/` branch prefix (not `fix/`), because it's the only one that's a pure refactor with no fix component.

---

## Task 2: Make `BaseInstrument` generic

**File:** `lite_bootstrap/instruments/base.py`

- [ ] **Step 1: Add the `ConfigT` TypeVar and parameterize `BaseInstrument`**

Current (lines 1-46):

```python
import abc
import dataclasses
import typing

import typing_extensions


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class BaseConfig:
    ...


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class BaseInstrument(abc.ABC):
    bootstrap_config: BaseConfig
    not_ready_message = ""
    missing_dependency_message = ""

    def bootstrap(self) -> None: ...  # noqa: B027

    def teardown(self) -> None: ...  # noqa: B027

    def is_ready(self) -> bool:
        return True

    @staticmethod
    def check_dependencies() -> bool:
        return True
```

Replace the `BaseInstrument` block (lines 30-45) with:

```python
ConfigT = typing.TypeVar("ConfigT", bound=BaseConfig)


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class BaseInstrument(abc.ABC, typing.Generic[ConfigT]):
    bootstrap_config: ConfigT
    not_ready_message = ""
    missing_dependency_message = ""

    def bootstrap(self) -> None: ...  # noqa: B027

    def teardown(self) -> None: ...  # noqa: B027

    def is_ready(self) -> bool:
        return True

    @staticmethod
    def check_dependencies() -> bool:
        return True
```

Two changes:
1. Add `ConfigT = typing.TypeVar("ConfigT", bound=BaseConfig)` between the two dataclasses.
2. `BaseInstrument` now inherits from `abc.ABC, typing.Generic[ConfigT]`; the `bootstrap_config` field type changes from `BaseConfig` to `ConfigT`.

- [ ] **Step 2: Quick smoke check**

```bash
just test -- tests/test_free_bootstrap.py -v
```

Expected: PASS. The `FreeBootstrapper` uses the base instruments directly with `FreeBootstrapperConfig`; if generic+slots+frozen has an issue, this test surfaces it first.

If this test fails with a slots/generic-related error, fall back to dropping `slots=True` from `BaseInstrument`:

```python
@dataclasses.dataclass(kw_only=True, frozen=True)
class BaseInstrument(abc.ABC, typing.Generic[ConfigT]):
    ...
```

Re-run the test. Note the change in the eventual commit message if so.

---

## Task 3: Parameterize each base instrument

For each instrument file, change the class signature from `class XInstrument(BaseInstrument):` to `class XInstrument(BaseInstrument[XConfig]):` and remove the redundant `bootstrap_config: XConfig` field declaration from the class body.

### Step 1: `lite_bootstrap/instruments/cors_instrument.py`

Current (around lines 17-25):

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class CorsInstrument(BaseInstrument):
    bootstrap_config: CorsConfig
    not_ready_message = "cors_allowed_origins or cors_allowed_origin_regex must be provided"

    def is_ready(self) -> bool:
        return bool(self.bootstrap_config.cors_allowed_origins) or bool(
            self.bootstrap_config.cors_allowed_origin_regex,
        )
```

Replace with:

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class CorsInstrument(BaseInstrument[CorsConfig]):
    not_ready_message = "cors_allowed_origins or cors_allowed_origin_regex must be provided"

    def is_ready(self) -> bool:
        return bool(self.bootstrap_config.cors_allowed_origins) or bool(
            self.bootstrap_config.cors_allowed_origin_regex,
        )
```

Single change: parameterize the base, drop the redundant `bootstrap_config: CorsConfig` field.

### Step 2: `lite_bootstrap/instruments/healthchecks_instrument.py`

Current (around lines 29-38):

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class HealthChecksInstrument(BaseInstrument):
    bootstrap_config: HealthChecksConfig
    not_ready_message = "health_checks_enabled is False"

    def is_ready(self) -> bool:
        return self.bootstrap_config.health_checks_enabled

    def render_health_check_data(self) -> HealthCheckTypedDict:
        return self.bootstrap_config.health_check_data
```

Replace with:

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class HealthChecksInstrument(BaseInstrument[HealthChecksConfig]):
    not_ready_message = "health_checks_enabled is False"

    def is_ready(self) -> bool:
        return self.bootstrap_config.health_checks_enabled

    def render_health_check_data(self) -> HealthCheckTypedDict:
        return self.bootstrap_config.health_check_data
```

### Step 3: `lite_bootstrap/instruments/logging_instrument.py`

Current (around lines 117-145):

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class LoggingInstrument(BaseInstrument):
    bootstrap_config: LoggingConfig
    not_ready_message = "logging_enabled is False"
    missing_dependency_message = "structlog is not installed"
    _logger_factory: "MemoryLoggerFactory | None" = dataclasses.field(
        default_factory=lambda: None, init=False, repr=False, compare=False
    )
    ...
```

Change only the class signature and remove the `bootstrap_config: LoggingConfig` line:

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class LoggingInstrument(BaseInstrument[LoggingConfig]):
    not_ready_message = "logging_enabled is False"
    missing_dependency_message = "structlog is not installed"
    _logger_factory: "MemoryLoggerFactory | None" = dataclasses.field(
        default_factory=lambda: None, init=False, repr=False, compare=False
    )
    ...
```

Everything below the field declarations stays unchanged.

### Step 4: `lite_bootstrap/instruments/opentelemetry_instrument.py`

Current (around lines 80-90):

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class OpenTelemetryInstrument(BaseInstrument):
    bootstrap_config: OpentelemetryConfig
    not_ready_message = "opentelemetry_endpoint is empty and opentelemetry_log_traces is False"
    missing_dependency_message = "opentelemetry is not installed"
    _tracer_provider: "TracerProvider | None" = dataclasses.field(
        default_factory=lambda: None, init=False, repr=False, compare=False
    )
    ...
```

Replace the class signature and drop `bootstrap_config: OpentelemetryConfig`:

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class OpenTelemetryInstrument(BaseInstrument[OpentelemetryConfig]):
    not_ready_message = "opentelemetry_endpoint is empty and opentelemetry_log_traces is False"
    missing_dependency_message = "opentelemetry is not installed"
    _tracer_provider: "TracerProvider | None" = dataclasses.field(
        default_factory=lambda: None, init=False, repr=False, compare=False
    )
    ...
```

Rest of the class unchanged.

### Step 5: `lite_bootstrap/instruments/prometheus_instrument.py`

Current (around lines 13-21):

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class PrometheusInstrument(BaseInstrument):
    bootstrap_config: PrometheusConfig
    not_ready_message = "prometheus_metrics_path is empty or not valid"

    def is_ready(self) -> bool:
        return bool(self.bootstrap_config.prometheus_metrics_path) and is_valid_path(
            self.bootstrap_config.prometheus_metrics_path
        )
```

Replace with:

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class PrometheusInstrument(BaseInstrument[PrometheusConfig]):
    not_ready_message = "prometheus_metrics_path is empty or not valid"

    def is_ready(self) -> bool:
        return bool(self.bootstrap_config.prometheus_metrics_path) and is_valid_path(
            self.bootstrap_config.prometheus_metrics_path
        )
```

### Step 6: `lite_bootstrap/instruments/pyroscope_instrument.py`

Current (around lines 21-46, after PR6's mixin landed):

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class PyroscopeInstrument(BaseInstrument):
    bootstrap_config: PyroscopeConfig
    not_ready_message = "pyroscope_endpoint is empty"
    missing_dependency_message = "pyroscope is not installed"

    def is_ready(self) -> bool:
        return bool(self.bootstrap_config.pyroscope_endpoint)
    ...
```

Replace class signature and drop the field:

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class PyroscopeInstrument(BaseInstrument[PyroscopeConfig]):
    not_ready_message = "pyroscope_endpoint is empty"
    missing_dependency_message = "pyroscope is not installed"

    def is_ready(self) -> bool:
        return bool(self.bootstrap_config.pyroscope_endpoint)
    ...
```

Rest unchanged.

### Step 7: `lite_bootstrap/instruments/sentry_instrument.py`

Current (around lines 94-105):

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class SentryInstrument(BaseInstrument):
    bootstrap_config: SentryConfig
    not_ready_message = "sentry_dsn is empty"
    missing_dependency_message = "sentry_sdk is not installed"

    def is_ready(self) -> bool:
        return bool(self.bootstrap_config.sentry_dsn)
    ...
```

Replace:

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class SentryInstrument(BaseInstrument[SentryConfig]):
    not_ready_message = "sentry_dsn is empty"
    missing_dependency_message = "sentry_sdk is not installed"

    def is_ready(self) -> bool:
        return bool(self.bootstrap_config.sentry_dsn)
    ...
```

### Step 8: `lite_bootstrap/instruments/swagger_instrument.py`

Current (around lines 13-16):

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class SwaggerInstrument(BaseInstrument):
    bootstrap_config: SwaggerConfig
```

Replace with:

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class SwaggerInstrument(BaseInstrument[SwaggerConfig]):
    pass
```

The body becomes empty — replace with `pass`. This is the smallest instrument class.

### Step 9: Intermediate verification

After all nine instrument files are updated:

```bash
just test -- tests/instruments/ -v
just test -- tests/test_free_bootstrap.py -v
```

Expected: all pass. The instrument-level tests + the free-bootstrapper test exercise every base instrument directly. If any fail, debug before moving to Task 4.

---

## Task 4: Delete the four pure-annotation framework subclasses

### Step 1: `lite_bootstrap/bootstrappers/fastapi_bootstrapper.py`

Locate `FastAPILoggingInstrument` (around lines 111-113):

```python
@dataclasses.dataclass(kw_only=True, frozen=True)
class FastAPILoggingInstrument(LoggingInstrument):
    bootstrap_config: FastAPIConfig
```

Delete the entire block.

Locate `FastAPISentryInstrument` (around lines 141-143):

```python
@dataclasses.dataclass(kw_only=True, frozen=True)
class FastAPISentryInstrument(SentryInstrument):
    bootstrap_config: FastAPIConfig
```

Delete the entire block.

In `FastAPIBootstrapper.instruments_types`:

```python
    instruments_types: typing.ClassVar = [
        FastAPICorsInstrument,
        FastAPIOpenTelemetryInstrument,
        PyroscopeInstrument,
        FastAPISentryInstrument,         # ← replace with SentryInstrument
        FastAPIHealthChecksInstrument,
        FastAPILoggingInstrument,        # ← replace with LoggingInstrument
        FastAPIPrometheusInstrument,
        FastAPISwaggerInstrument,
    ]
```

Replace `FastAPISentryInstrument` with `SentryInstrument` and `FastAPILoggingInstrument` with `LoggingInstrument`.

### Step 2: `lite_bootstrap/bootstrappers/litestar_bootstrapper.py`

Locate `LitestarSentryInstrument` (around lines 199-201):

```python
@dataclasses.dataclass(kw_only=True, frozen=True)
class LitestarSentryInstrument(SentryInstrument):
    bootstrap_config: LitestarConfig
```

Delete the entire block.

In `LitestarBootstrapper.instruments_types`, replace `LitestarSentryInstrument` with `SentryInstrument`.

### Step 3: `lite_bootstrap/bootstrappers/faststream_bootstrapper.py`

Locate `FastStreamSentryInstrument` (around lines 135-137):

```python
@dataclasses.dataclass(kw_only=True, frozen=True)
class FastStreamSentryInstrument(SentryInstrument):
    bootstrap_config: FastStreamConfig
```

Delete the entire block.

In `FastStreamBootstrapper.instruments_types`, replace `FastStreamSentryInstrument` with `SentryInstrument`.

### Step 4: Verify imports

After the deletions, the framework bootstrappers no longer reference the deleted classes by name. Any imports of `FastAPILoggingInstrument` / `FastAPISentryInstrument` / `LitestarSentryInstrument` / `FastStreamSentryInstrument` from other test files or modules would break.

Run a sanity grep:

```bash
grep -rn "FastAPILoggingInstrument\|FastAPISentryInstrument\|LitestarSentryInstrument\|FastStreamSentryInstrument" .
```

Expected: only matches in the plan/spec docs (which describe the deletion). Zero matches in `lite_bootstrap/` or `tests/`. If any test file imports a deleted class, update it to use the base class name.

---

## Task 5: Verify and commit

- [ ] **Step 1: Run the full test suite**

```bash
just test
```

Expected: 89/89 pass. No behavior change should result from this refactor.

If any framework integration test (`test_fastapi_bootstrap`, `test_litestar_bootstrap`, `test_faststream_bootstrap`) fails, the most likely cause is type-narrowing surprise on a framework subclass that needs to access framework-specific config fields. Verify the kept framework subclasses still declare `bootstrap_config: <FrameworkConfig>` where they override `bootstrap()`.

- [ ] **Step 2: Run lint**

```bash
just lint
```

Expected: clean. Watch for:

- F401 unused-import warnings — possible if a bootstrapper imports something it no longer uses after the deletions.
- `ty check` complaints about the new generic parameterization — should be silent, but if not, narrow the issue and address.

- [ ] **Step 3: Sanity-check the diff**

```bash
git diff --stat
```

Expected: 12 files changed. Approximate line counts (rough):
- `base.py`: +4 / -1 (TypeVar + Generic + bootstrap_config type)
- 8 instrument files: roughly -1 line each (drop the redundant field declaration)
- 3 bootstrapper files: ~-3 lines per deleted subclass + 1-2 line changes in `instruments_types`

Total net: roughly -10 to -20 lines.

- [ ] **Step 4: Commit**

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
refactor: make BaseInstrument generic; delete pure-annotation subclasses

Closes DES-1: the four pure type-annotation framework subclasses
(FastAPILoggingInstrument, FastAPISentryInstrument, LitestarSentryInstrument,
FastStreamSentryInstrument) existed only to narrow bootstrap_config. They
contributed no behavior.

Make BaseInstrument generic in ConfigT (TypeVar bound to BaseConfig).
Each base instrument concretely parameterizes the generic
(LoggingInstrument(BaseInstrument[LoggingConfig]), etc.) and drops its
own redundant bootstrap_config field declaration — the type is now
provided by the parent's generic parameter.

Delete the four pure-annotation framework subclasses. In the three
affected bootstrappers' instruments_types lists, replace the deleted
class references with the base names (SentryInstrument, LoggingInstrument).

Framework subclasses that override bootstrap() with real framework-specific
logic (FastAPICorsInstrument, LitestarLoggingInstrument, etc. — 15 in
total) keep their existing structure including the bootstrap_config:
<FrameworkConfig> annotation. These annotations are NOT redundant under
the single-level-generic design adopted here — they provide essential
type narrowing for framework field access (e.g.,
self.bootstrap_config.application inside FastAPICorsInstrument.bootstrap).

This deviates from the sequencing spec's "drop redundant annotations
on kept subclasses" decision: a two-level-generic design would be needed
to make those annotations truly redundant, and the complexity isn't
worth it. The audit's stated goal (eliminate the pure-annotation
boilerplate) is fully addressed regardless.

No behavior change. Existing tests verify correctness.

Closes DES-1 from the audit.
EOF
)"
```

---

## Task 6: Push and open PR

- [ ] **Step 1: Push the branch**

```bash
git push -u origin refactor/des-1-generic-instruments
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --title "refactor: make BaseInstrument generic; delete pure-annotation subclasses" --body "$(cat <<'EOF'
## Summary
Closes DES-1 from an internal audit: the four pure type-annotation framework subclasses (`FastAPILoggingInstrument`, `FastAPISentryInstrument`, `LitestarSentryInstrument`, `FastStreamSentryInstrument`) existed only to narrow `bootstrap_config`. They contributed no behavior.

- `BaseInstrument` is now generic in `ConfigT` (`TypeVar` bound to `BaseConfig`).
- Each base instrument concretely parameterizes the generic (`LoggingInstrument(BaseInstrument[LoggingConfig])`, etc.) and drops its redundant `bootstrap_config` field declaration — the type is provided by the parent.
- The four pure-annotation framework subclasses are deleted. The three affected bootstrappers' `instruments_types` lists now reference the base names directly (`SentryInstrument`, `LoggingInstrument`).
- Framework subclasses that override `bootstrap()` with framework-specific logic (15 in total) keep their existing structure.

No behavior change. Existing tests verify correctness.

## Deviation from sequencing spec
The sequencing spec called for "dropping redundant `bootstrap_config:` annotations on kept subclasses." Under a single-level-generic design those annotations are NOT redundant — they provide essential type narrowing for framework field access (e.g. `self.bootstrap_config.application` in `FastAPICorsInstrument.bootstrap()`). Making them truly redundant would require a two-level-generic design (each base instrument with its own bounded `TypeVar`); the complexity isn't worth the marginal cleanup. The audit's stated goal — eliminating the pure-annotation boilerplate — is fully addressed regardless.

## Test plan
- [x] `just test` — full suite passes (89/89).
- [x] `just lint` — clean.
- [ ] Reviewer: confirm the generic + slots + frozen dataclass combination works on Python 3.10. If `BaseInstrument`'s `slots=True` had to be dropped during implementation, the commit message will note it.
- [ ] Reviewer: confirm the kept framework subclasses (`FastAPICorsInstrument`, `LitestarLoggingInstrument`, etc.) still access framework-specific config fields correctly.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review

**Spec coverage check** against the sequencing spec (PR7 section) and audit (DES-1):

| Spec item | Task |
|-----------|------|
| `BaseInstrument` becomes generic in `ConfigT` (bound to `BaseConfig`) | Task 2, Step 1 |
| Each base instrument concretely parameterizes | Task 3, Steps 1-8 |
| Each base instrument drops its redundant `bootstrap_config:` field declaration | Task 3, Steps 1-8 |
| Delete `FastAPILoggingInstrument` | Task 4, Step 1 |
| Delete `FastAPISentryInstrument` | Task 4, Step 1 |
| Delete `LitestarSentryInstrument` | Task 4, Step 2 |
| Delete `FastStreamSentryInstrument` | Task 4, Step 3 |
| Update `FastAPIBootstrapper.instruments_types` to reference base names | Task 4, Step 1 |
| Update `LitestarBootstrapper.instruments_types` | Task 4, Step 2 |
| Update `FastStreamBootstrapper.instruments_types` | Task 4, Step 3 |
| Branch name `refactor/des-1-generic-instruments` | Task 1, Step 1 |
| Verification: `just test` + `just lint` clean | Task 5, Steps 1-2 |

**Deviations from sequencing spec (documented in commit and PR body):**
- Single-level generic rather than two-level.
- Kept framework subclasses retain their `bootstrap_config:` annotations.

**Deferred:**
- REF-1 (`_build_excluded_urls` duplication between FastAPI and Litestar OTel instruments) — fold into a quick PR8 if PR7's diff stays manageable; otherwise separate follow-up.
- REF-2 (dead defensive check in `LitestarLoggingInstrument.bootstrap()`) — same.
- REF-5 (collapse near-empty `swagger_instrument.py` and `prometheus_instrument.py` base files) — out of scope.

These three are explicitly noted in the sequencing spec as follow-ups to PR7. Decide once PR7's actual diff lands whether to bundle them or split.
