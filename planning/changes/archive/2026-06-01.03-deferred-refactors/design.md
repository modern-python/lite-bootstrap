---
status: shipped
date: 2026-06-01
slug: deferred-refactors
supersedes: null
superseded_by: null
pr: null
outcome: shipped as #96–#103
---
# Deferred Refactors Sequencing

**Date:** 2026-06-01
**Parent audit:** [2026-05-31-bug-refactor-audit.md](../../audits/2026-05-31-bug-refactor-audit.md)
**Sibling spec:** [2026-05-31-audit-implementation-sequencing.md](../2026-05-31.01-audit-implementation/design.md) (criticals + design issues; 7 PRs shipped as #89, #90, #91, #92, #93, #94, #95)
**Scope:** All 20 deferred items — REF-1..7 (refactor opportunities), TEST-4/7/8 (test gaps), LOW-1..9 (cosmetic). Plus one finding surfaced during PR6 review: `Opentelemetry` → `OpenTelemetry` capitalization rename.
**Deliverable:** 8 sequenced PRs. Sequencing rationale, per-PR scope, locked decisions.

This document sequences the cleanup tail of the audit into 8 small-to-medium PRs.
Picks up where the first sequencing spec left off. Per-PR implementation plans are
drafted on demand.

---

## Sequencing rationale

Same principles as the parent sequencing spec:

1. **Small/lowest-risk first.** PR8 is 1 file, 2 LOWs. PR15 is the largest API-surface change (renames) and goes last.
2. **Test additions early.** PR10 is pure additions, zero behavior change — front-loaded so future PRs benefit from the broader coverage.
3. **Naming pass last.** Renames with deprecation aliases land after all other refactors, so the new names are the only thing changing in their final PR.

Order:

| # | PR | Findings | Risk | Files |
|---|-----|----------|------|-------|
| 8 | Sentry micro-fixes | LOW-1, LOW-2 | Very low | 1 |
| 9 | OTel instrument touch-ups | REF-1, LOW-3, LOW-5 | Low | 3 |
| 10 | Test gap fill | TEST-4, TEST-7 | None | 5 new |
| 11 | Logging cleanup + lifecycle test | REF-4, REF-2, LOW-6, LOW-8, LOW-9, TEST-8 | Medium | 4-5 (1 new) |
| 12 | Base layer cleanup | REF-3, REF-5 | Low | 3 |
| 13 | Frozen/setattr pattern + FastAPI default | REF-6, LOW-4 | Medium | 3-4 |
| 14 | FastStream broker timeout | REF-7 | Low | 3 |
| 15 | Naming pass with deprecation aliases | LOW-7, `Opentelemetry`→`OpenTelemetry` | Low–Medium | 4-5 |

Each PR merges (squash) to `main` before the next branches off. Branch naming follows
the established pattern: `fix/<finding-id>-<slug>` for behavior changes,
`refactor/<finding-id>-<slug>` for pure refactors.

---

## PR8: Sentry micro-fixes (LOW-1 + LOW-2)

**Branch:** `fix/low-1-2-sentry-micro`

**Scope:**

- LOW-1: In `instruments/sentry_instrument.py:81-82`, change `if not callback:` to
  `if callback is None:` in `wrap_before_send_callbacks`. Idiom fix — callables are
  always truthy unless they define `__bool__`.
- LOW-2: In `instruments/sentry_instrument.py:36`, change
  `sentry_before_send: Callable[[Any, Any], Any | None] | None` to
  `sentry_before_send: "EventProcessor | None"` (using sentry's `EventProcessor` from
  `_types`, already imported under `TYPE_CHECKING`). The current type
  `Callable[[Any, Any], Any | None] | None` collapses to
  `Callable[..., Any] | None` because `Any | None == Any` — the union adds nothing.

**Files:** 1 — `lite_bootstrap/instruments/sentry_instrument.py`.

**Test impact:** None. Existing Sentry tests cover both behaviors.

---

## PR9: OTel instrument touch-ups (REF-1 + LOW-3 + LOW-5)

**Branch:** `refactor/ref-1-otel-touch-ups`

**Scope:**

- REF-1: `_build_excluded_urls()` is character-for-character identical in
  `FastAPIOpenTelemetryInstrument` and `LitestarOpenTelemetryInstrument`. Hoist to
  the base `OpenTelemetryInstrument` (in `instruments/opentelemetry_instrument.py`)
  and let both framework subclasses inherit it. The base implementation reads
  `self.bootstrap_config.opentelemetry_excluded_urls` and
  `self.bootstrap_config.prometheus_metrics_path` — both fields live on the
  framework configs (not on the bare `OpentelemetryConfig`). Resolve via either:
  (a) reading via `getattr` with defaults, or (b) keeping the method but
  parameterizing it to take the URLs as arguments. **Resolution direction:**
  (a) — `_build_excluded_urls` becomes a method on the base that reads via `getattr`
  with `set()` and `""` defaults. Framework subclasses no longer need their own
  override.
- LOW-3: `_format_span` (line 25-26) uses `os.linesep`. On Windows that produces
  `\r\n`; OTel SDK convention is `\n`. Change to literal `"\n"`.
- LOW-5: Add a one-line comment on
  `LitestarOpenTelemetryInstrumentationMiddleware._otel_apps`
  (`bootstrappers/litestar_bootstrapper.py:79`) explaining the `id(next_app)` key
  assumption (ASGI app instances are stable; theoretical ID reuse is acceptable for
  this cache).

**Files:** 3 — `opentelemetry_instrument.py`, `fastapi_bootstrapper.py`,
`litestar_bootstrapper.py`.

**Test impact:** None expected. The `_build_excluded_urls` hoist is a behavior-preserving
move; existing framework integration tests verify.

---

## PR10: Test gap fill (TEST-4 + TEST-7)

**Branch:** `fix/test-4-7-gaps`

**Scope:**

Pure additions. No production code changes.

- TEST-4: Add 4 standalone instrument test files:
  - `tests/instruments/test_cors_instrument.py` — covers `CorsInstrument.is_ready()`
    in its various configurations (no origins/regex, origins only, regex only,
    both), `not_ready_message` content, `check_dependencies()` returning True.
  - `tests/instruments/test_healthchecks_instrument.py` — covers
    `HealthChecksInstrument.is_ready()` (enabled vs disabled),
    `render_health_check_data()` output shape, default field values.
  - `tests/instruments/test_prometheus_instrument.py` — covers
    `PrometheusInstrument.is_ready()` for valid/invalid paths,
    `not_ready_message`.
  - `tests/instruments/test_swagger_instrument.py` — covers
    `SwaggerInstrument` instantiation and default config values.

- TEST-7: Add `tests/test_path.py` with negative cases for
  `helpers/path.py::is_valid_path`. Cover: empty string, no leading slash
  (`"foo"`), path with space (`"/path with space"`), parent-dir traversal
  (`"../escape"`), double slash (`"//foo"`), trailing slash variations.

**Files:** 5 new test files. Zero production changes.

**Test impact:** +30-50 tests across the new files. Total suite count goes from
89 → ~120+.

---

## PR11: Logging cleanup + lifecycle test (REF-4 + REF-2 + LOW-6 + LOW-8 + LOW-9 + TEST-8)

**Branch:** `refactor/ref-4-logging-cleanup`

**Scope:** Largest of the eight PRs. Bundles all logging-related cleanups into one
review unit.

- REF-4: Split `instruments/logging_instrument.py` (212 lines) into:
  - `instruments/logging_factory.py` — `MemoryLoggerFactory`,
    `_serialize_log_with_orjson_to_string`, `AddressProtocol`,
    `RequestProtocol`, `ScopeType`. The single
    `if import_checker.is_structlog_installed:` gate at module top wraps both
    `MemoryLoggerFactory` and `_serialize_log_with_orjson_to_string`.
  - `instruments/logging_instrument.py` — `LoggingConfig`, `LoggingInstrument`,
    `tracer_injection`. Imports `MemoryLoggerFactory` from `logging_factory`.

- LOW-6: Wrap `MemoryLoggerFactory.__init__`'s 5 logging-config kwargs into an
  internal config dataclass `_MemoryLoggerFactoryConfig` (underscore-prefixed —
  internal-only per locked decision Q4). The factory then takes the config plus the
  `log_stream` parameter.

- REF-2: Delete the dead defensive `if import_checker.is_structlog_installed and
  import_checker.is_litestar_installed:` branch in
  `LitestarLoggingInstrument.bootstrap()` (`litestar_bootstrapper.py:157-174`).
  The instrument couldn't have been registered without those installed.

- LOW-8: Add a docstring to `LoggingInstrument._unset_handlers` documenting that the
  mutation is permanent — `teardown()` does not restore the original handlers.
  Suitable for the microservice-runs-until-process-exit model; risky for other use.

- LOW-9: Add a docstring to `LoggingInstrument.teardown()` documenting that root
  logger level is unconditionally reset to `WARNING`. Pre-existing user
  configuration is overwritten.

- TEST-8: Add a `LoggingInstrument` lifecycle replay test — bootstrap → teardown →
  bootstrap → teardown — asserting no exceptions and that the second bootstrap
  succeeds (initializes a fresh `_logger_factory`).

**Files:** 4-5 — `logging_factory.py` (new), `logging_instrument.py`,
`litestar_bootstrapper.py`, `tests/instruments/test_logging_instrument.py`. Possibly
`__init__.py` if the public surface changes.

**Test impact:** +1 test (lifecycle replay). All existing logging tests must pass.

**Risk:** Medium. The file split touches imports across the codebase. Verify the test
suite passes against the new layout.

---

## PR12: Base layer cleanup (REF-3 + REF-5)

**Branch:** `refactor/ref-3-5-base-layer`

**Scope:**

- REF-3: Drop `abc.ABC` from `BaseInstrument` in `instruments/base.py`. All four
  methods (`bootstrap`, `teardown`, `is_ready`, `check_dependencies`) are concrete
  no-ops with default returns; `abc.ABC` adds nothing. PR7 already removed the
  `# noqa: B027` suppressions (ruff stopped flagging once `Generic[ConfigT]` joined
  the base list). Removing `abc.ABC` clarifies the class's role as a regular base
  class.

  After the change: `class BaseInstrument(typing.Generic[ConfigT]):`. The `abc`
  import becomes unused — drop it.

- REF-5: For `instruments/swagger_instrument.py` and
  `instruments/prometheus_instrument.py` (both very small after PR7), keep them as
  separate files per the locked decision (Q3). Add a one-line module docstring to
  each explaining "Config holder; framework-specific behavior lives in the
  bootstrapper subclasses."

**Files:** 3 — `base.py`, `swagger_instrument.py`, `prometheus_instrument.py`.

**Test impact:** None. Pure code-shape change.

---

## PR13: Frozen/setattr pattern + FastAPI default (REF-6 + LOW-4)

**Branch:** `refactor/ref-6-frozen-setattr`

**Scope:**

- REF-6: Python's dataclass rules forbid surgical unfreezing (a non-frozen
  dataclass can't inherit from a frozen one). To drop `frozen=True` from
  `LoggingInstrument` and `OpenTelemetryInstrument` (the two instruments with
  `object.__setattr__` workarounds), `BaseInstrument` and all 22 instrument
  subclasses must also lose `frozen=True`. Configs all keep `frozen=True`.
  After the cascade, 4 `object.__setattr__(self, "_x", value)` call sites in
  the two instruments become plain `self._x = value`. The `try/finally`
  exception safety from PR3 is preserved.

- LOW-4: `FastAPIConfig.application` declared with `default=None` +
  `# ty: ignore[invalid-assignment]`. Replaced with a proper sentinel-type
  pattern: introduce `UnsetType` + `UNSET` singleton in
  `lite_bootstrap/types.py`, type the field as `fastapi.FastAPI | UnsetType`,
  default to `UNSET`, check via `isinstance(self.application, UnsetType)`. Add
  a `_narrow_app(config)` helper that asserts the type and returns the
  narrowed app; every FastAPI framework instrument calls it. Drops the
  `# ty: ignore`. `FastAPIConfig` stays frozen — the existing
  `object.__setattr__(self, "application", ...)` in `__post_init__` remains
  (a code comment documents the rationale). Sibling configs (`LitestarConfig`,
  `FastStreamConfig`) don't have this need because they use `default_factory`
  for their app fields.

  **Note:** the originally-planned `typing.cast("fastapi.FastAPI", object())`
  sentinel was replaced during implementation with a proper `UnsetType` class.
  This spec has been retroactively updated to match what was built.

**Files:** 13 — 9 instrument modules (`base.py` + 8 base instruments), 3
bootstrapper modules (`fastapi`, `litestar`, `faststream`), and `types.py`
(new `UnsetType` + `UNSET` sentinel).

**Test impact:** Existing tests should pass unchanged. Watch for any test that relied
on `FrozenInstanceError` being raised on instrument mutation — none expected.

**Risk:** Medium. The cascade is mechanical but missing one entry breaks the build
(TypeError at import). The `frozen` change is observable to user code that relied on
`dataclasses.replace` for instruments — unlikely in practice but worth noting.

---

## PR14: FastStream broker timeout (REF-7)

**Branch:** `fix/ref-7-faststream-timeout`

**Scope:**

- Add `faststream_health_check_broker_timeout: float = 5.0` to `FastStreamConfig`
  (per locked decision Q5 — field belongs on FastStream-specific config, not shared
  `HealthChecksConfig`).
- Update
  `FastStreamHealthChecksInstrument._define_health_status` in
  `bootstrappers/faststream_bootstrapper.py:100-104` to use
  `self.bootstrap_config.faststream_health_check_broker_timeout` instead of the
  hardcoded `timeout=5`.
- Add a test asserting that a custom timeout reaches `broker.ping(timeout=...)`.

**Files:** 3 — `faststream_bootstrapper.py`, `tests/test_faststream_bootstrap.py`.

**Test impact:** +1 test.

---

## PR15: Naming pass with deprecation aliases (LOW-7 + `Opentelemetry`→`OpenTelemetry`)

**Branch:** `refactor/low-7-naming`

**Scope:** Two API-surface renames. Both ship silent backward-compat aliases
(locked decision Q2 — no deprecation warnings, just aliases).

- `OpentelemetryConfig` → `OpenTelemetryConfig` (lowercase t → uppercase T to match
  `OpenTelemetryServiceFieldsConfig` from PR6 and the conventional product
  capitalization). Add silent alias:

  ```python
  OpenTelemetryConfig = OpentelemetryConfig  # canonical name from <date>
  # OpentelemetryConfig kept as alias for backward compatibility
  ```

  Update all internal references to use the new name. Re-export from `__init__.py`.

- `FreeBootstrapperConfig` → `FreeConfig` (consistency with sibling configs:
  `FastAPIConfig`, `LitestarConfig`, `FastStreamConfig` — none have the
  `Bootstrapper` infix). Add silent alias. Update internal references and
  `__init__.py`.

Internal references to update:
- `bootstrappers/free_bootstrapper.py` — `FreeBootstrapper.bootstrap_config:
  FreeConfig`, ctor signature.
- All framework configs that inherit from `OpentelemetryConfig` → inherit from
  `OpenTelemetryConfig`.
- `__init__.py` exports: both names exported (canonical + alias).

**Files:** 4-5 — `opentelemetry_instrument.py`, `free_bootstrapper.py`, `__init__.py`,
plus the four framework configs (`fastapi_bootstrapper.py`,
`litestar_bootstrapper.py`, `faststream_bootstrapper.py`, the `FreeBootstrapperConfig`
itself). May also touch tests if any reference the renamed classes by name.

**Test impact:** None expected — the aliases preserve all existing code paths.
Existing tests using the old names continue to work via the alias.

**Risk:** Low-Medium. The PR is mechanical but touches public surface; ensure
exports are correct and aliases don't shadow.

---

## Branch hygiene & CI

- One branch per PR off `main`. `fix/<finding-id>-<slug>` or
  `refactor/<finding-id>-<slug>` matching the parent sequencing spec's conventions.
- Each PR runs `just lint-ci` and `just test`.
- Squash-merge each PR before the next branches off.
- For PR11 specifically: verify `ty check` passes after the file split — the new
  `logging_factory.py` module's protocols and conditional imports need to align with
  the existing patterns.
- For PR13: verify `ty check` passes after dropping `frozen=True` on the two
  instruments — `dataclasses.replace` interactions, if any, will surface.
- For PR15: after merge, do a global grep to confirm no straggler internal
  references use the old names.

---

## Locked decisions

| Decision | Choice |
|----------|--------|
| Q1: PR13 frozen-drop scope | Keep PR3's `try/finally`; PR13 only drops `frozen=True` and `object.__setattr__` |
| Q2: PR15 deprecation aliases | Silent (no warn-on-access). Document in module docstring |
| Q3: PR12 collapse vs keep | Keep `swagger_instrument.py` and `prometheus_instrument.py` separate; add module docstring |
| Q4: PR11 MemoryLoggerFactory config | Internal — prefix `_MemoryLoggerFactoryConfig`, not exported |
| Q5: PR14 timeout field placement | `FastStreamConfig` (not shared `HealthChecksConfig`) |
| Q6: PR10 ordering | Keep early in sequence — pure additions, zero risk |
| Q7: Single-PR cadence | One at a time, squash-merge each before next branches off |

---

## Out of scope

These are explicitly NOT part of this sequencing pass:

- Anything not in the audit. Items surfaced during PR2-PR7 reviews that weren't in
  the audit (e.g., the cosmetic `SwaggerInstrument` body being `pass` after PR7)
  stay out unless they affect correctness.
- Documentation-only additions (CONTRIBUTING notes about the `is_ready` /
  `check_dependencies` invariant). Could ship as a doc-only follow-up PR if desired.
- API additions or new features. The audit is a cleanup baseline.

---

## Cross-references

After this sequence completes (15 PRs total counting the parent), the audit's findings
are fully addressed. Status will be:

- **Critical bugs:** all 3 closed (PR1-3).
- **Design issues:** all 5 closed (PR4-7).
- **Refactor opportunities:** all 7 closed (REF-1 in PR9; REF-2, REF-4 in PR11;
  REF-3, REF-5 in PR12; REF-6 in PR13; REF-7 in PR14).
- **Test gaps:** all 8 closed (paired with criticals/design in PR1-7; remaining 3 in
  PR10, 11).
- **Low-priority items:** all 9 closed (LOW-1, LOW-2 in PR8; LOW-3, LOW-5 in PR9;
  LOW-6, LOW-8, LOW-9 in PR11; LOW-4 in PR13; LOW-7 in PR15).

Plus the bonus capitalization rename surfaced during PR6 review (closed in PR15).
