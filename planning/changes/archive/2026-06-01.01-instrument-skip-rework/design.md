---
status: shipped
date: 2026-06-01
slug: instrument-skip-rework
supersedes: null
superseded_by: stdlib-logging-and-build-summary
pr: null
outcome: shipped (partially superseded; see stdlib-logging-and-build-summary)
---
# Design: Instrument Skip Rework — Replace `InstrumentNotReadyWarning` With Pre-Instantiation Config Check + Summary Log

**Date:** 2026-06-01
**Status:** Approved (design complete; implementation pending)

## Problem

PR #86 (commit `992b3db`, "feat: unify instrument skip feedback through warning subclasses") added
`InstrumentNotReadyWarning` as a sibling to `InstrumentDependencyMissingWarning`. Both fire from
`BaseBootstrapper._register_or_skip` when an instrument is skipped — `InstrumentNotReadyWarning`
specifically fires when an instrument's `is_ready()` instance method returns False, which is
typically a user-config decision (`sentry_dsn` empty, `pyroscope_endpoint` empty, `logging_enabled` False, etc.).

The change escalated the not-ready path from `logger.info` (pre-#86, silently dropped because logging
hadn't bootstrapped yet) to a real `warnings.warn` call. The escalation surfaces an expected-path
event as a warning, generating noise in every downstream service that uses a subset of the
available instruments. Services must add `warnings.filterwarnings` to suppress; lite-bootstrap's own
test suite asserts on these warnings with `pytest.warns(InstrumentNotReadyWarning)`, so suppression
can't be global.

A second, related issue: even pre-#86, `InstrumentDependencyMissingWarning` fires for unconfigured
instruments when the user didn't install the optional extra. Example: install `lite-bootstrap[fastapi]`
without `[sentry]`, never configure Sentry → `SentryInstrument.check_dependencies()` returns False →
`InstrumentDependencyMissingWarning` fires. The user didn't want Sentry; the warning is noise.

Root cause: the bootstrapper runs `check_dependencies()` before checking whether the user wanted
the instrument. PR #88 (commit `b5e00a2`) made the order strict — `check_dependencies()` MUST run
before instantiation because `FastStreamPrometheusInstrument` has a `default_factory` that calls
`prometheus_client.CollectorRegistry()`, which NameErrors when `prometheus_client` isn't installed.

The post-#86 flow:

1. `check_dependencies()` — static method on type. Fires `InstrumentDependencyMissingWarning` on False.
2. Instantiate.
3. `is_ready()` — instance method. Fires `InstrumentNotReadyWarning` on False.

Both warnings can fire on the expected path of any service that doesn't use every available instrument.

## Goal

Establish a contract where warnings only fire for genuine deployment surprises (user configured an
instrument, but the dependency is missing). Skipped-due-to-config becomes silent at the warning
level, with structured introspection available on the bootstrapper instance and a single
INFO-level summary log for diagnostic visibility.

## Design

### API change: `is_ready` becomes `is_configured` classmethod

`BaseInstrument` API:

```python
class BaseInstrument(typing.Generic[ConfigT]):
    bootstrap_config: ConfigT
    not_ready_message: typing.ClassVar[str] = ""
    missing_dependency_message: typing.ClassVar[str] = ""

    @classmethod
    def is_configured(cls, bootstrap_config: ConfigT) -> bool:
        """Return True if config indicates this instrument should be active. Default: always active."""
        return True

    @staticmethod
    def check_dependencies() -> bool:
        return True

    def bootstrap(self) -> None: ...
    def teardown(self) -> None: ...
```

`is_configured` is a classmethod taking `bootstrap_config` because it must run before instantiation
(so PR #88's NameError constraint is preserved — no instance, no default-factory eval, no NameError).
The signature change is a one-time migration cost; the trade-off buys correct ordering.

`is_ready` instance method: **removed**. Existing callers migrate to `XInstrument.is_configured(config)`.

`not_ready_message`: **kept** as a class attribute on each instrument. Used as the human-readable
reason in `skipped_instruments` and the summary log.

### Bootstrapper flow reorder

`BaseBootstrapper.__init__` body changes:

```python
self.instruments: list[BaseInstrument] = []
self.skipped_instruments: list[tuple[type[BaseInstrument], str]] = []  # NEW

for instrument_type in self.instruments_types:
    if not instrument_type.is_configured(self.bootstrap_config):
        self.skipped_instruments.append((instrument_type, instrument_type.not_ready_message))
        continue
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

The `_register_or_skip` helper goes away — the flow is short enough inline.

Order semantics:

1. `is_configured(config)` False → silent skip + entry in `skipped_instruments`. No warning.
2. `is_configured(config)` True, `check_dependencies()` False → `InstrumentDependencyMissingWarning`
   fires. This IS a genuine deployment surprise: user configured the instrument but the optional
   package isn't installed.
3. Both True → instrument instantiated and registered.

### Introspection

The new `bootstrapper.skipped_instruments: list[tuple[type[BaseInstrument], str]]` exposes
unconfigured instruments as structured data — class object + the `not_ready_message` string. Tests
and third-party tooling consume this directly instead of warning capture.

`bootstrapper.instruments: list[BaseInstrument]` (already exists) exposes the configured instances.

### Summary log

One `logger.info(...)` call at the end of `__init__`, after all decisions. Default Python logging
suppresses INFO-level by default, so users see nothing unless they `logging.basicConfig(level=logging.INFO)`
or otherwise configure their root logger. The pre-#86 "silently dropped" property is preserved by
default while keeping an opt-in path to visibility.

The summary is one line (not per-instrument). Even if it's dropped silently in production, the
hit-count cost is constant per bootstrap call, not per-instrument.

The `logger` is the existing module-level structlog/stdlib logger (whichever is available) in
`bootstrappers/base.py:19-21`.

## Per-instrument migration

All 8 base instruments + 3 framework-specific overrides. Mechanical signature change.

| Instrument | Current `is_ready(self)` body | New `is_configured(cls, bootstrap_config)` body |
|---|---|---|
| `BaseInstrument` | (default `return True`) | (default `return True`) |
| `CorsInstrument` | `bool(self.bootstrap_config.cors_allowed_origins) or bool(self.bootstrap_config.cors_allowed_origin_regex)` | `bool(bootstrap_config.cors_allowed_origins) or bool(bootstrap_config.cors_allowed_origin_regex)` |
| `HealthChecksInstrument` | `self.bootstrap_config.health_checks_enabled` | `bootstrap_config.health_checks_enabled` |
| `LoggingInstrument` | `self.bootstrap_config.logging_enabled` | `bootstrap_config.logging_enabled` |
| `OpenTelemetryInstrument` | `bool(self.bootstrap_config.opentelemetry_endpoint or self.bootstrap_config.opentelemetry_log_traces)` | (same w/ `bootstrap_config.`) |
| `PrometheusInstrument` | `bool(self.bootstrap_config.prometheus_metrics_path) and is_valid_path(self.bootstrap_config.prometheus_metrics_path)` | (same w/ `bootstrap_config.`) |
| `PyroscopeInstrument` | `bool(self.bootstrap_config.pyroscope_endpoint)` | `bool(bootstrap_config.pyroscope_endpoint)` |
| `SentryInstrument` | `bool(self.bootstrap_config.sentry_dsn)` | `bool(bootstrap_config.sentry_dsn)` |
| `SwaggerInstrument` | (default `return True`) | (default `return True`) |

Framework-specific overrides:

- `LitestarSwaggerInstrument.is_ready` → `is_configured` classmethod; same body with `bootstrap_config` arg.
- `FastStreamOpenTelemetryInstrument.is_ready`: `super().is_ready() and bool(self.bootstrap_config.opentelemetry_middleware_cls)` → `super().is_configured(bootstrap_config) and bool(bootstrap_config.opentelemetry_middleware_cls)`.
- `FastStreamPrometheusInstrument.is_ready`: `super().is_ready() and import_checker.is_prometheus_client_installed and bool(self.bootstrap_config.prometheus_middleware_cls)` → classmethod form. The `import_checker.is_prometheus_client_installed` conjunct is dead per the DES-5 audit finding (already covered by `check_dependencies`); can be dropped during migration.

## Tests

### `tests/test_free_bootstrap.py::test_free_bootstrap_logging_disabled`

Current:

```python
with pytest.warns(InstrumentNotReadyWarning) as records:
    FreeBootstrapper(bootstrap_config=FreeBootstrapperConfig(logging_enabled=False, ...))
messages = [str(r.message) for r in records]
assert "LoggingInstrument is not ready: logging_enabled is False" in messages
assert "PyroscopeInstrument is not ready: pyroscope_endpoint is empty" in messages
```

New:

```python
bootstrapper = FreeBootstrapper(
    bootstrap_config=FreeBootstrapperConfig(logging_enabled=False, ...),
)
skipped_classes = {cls for cls, _ in bootstrapper.skipped_instruments}
assert LoggingInstrument in skipped_classes
assert PyroscopeInstrument in skipped_classes
```

### `tests/instruments/test_*_instrument.py` (PR10 additions)

`assert not instrument.is_ready()` → `assert not XInstrument.is_configured(config)`.
`assert instrument.not_ready_message == "..."` → `assert XInstrument.not_ready_message == "..."`
(class attribute access; functionally identical).

Affected files: `test_cors_instrument.py`, `test_healthchecks_instrument.py`, `test_prometheus_instrument.py`, `test_pyroscope_instrument.py`, `test_swagger_instrument.py`.

### Existing tests that continue to work unchanged

`test_fastapi_bootstrapper_with_missing_instrument_dependency` and its
`{litestar,faststream,free}` siblings exercise the dep-missing warning path. Under the new flow,
they still pass: when a configured instrument's optional dep is missing, the warning fires as
before. The reorder doesn't affect them — these tests use a config that DOES configure the
relevant instrument (`is_configured` returns True), so the dep check runs.

### Optional new test: summary log assertion

A small test in `test_free_bootstrap.py` using pytest's `caplog` fixture can pin the new INFO
summary log behavior:

```python
def test_bootstrap_emits_summary_log(caplog) -> None:
    with caplog.at_level(logging.INFO, logger="lite_bootstrap.bootstrappers.base"):
        FreeBootstrapper(bootstrap_config=FreeBootstrapperConfig(sentry_dsn="https://x@y/1"))
    assert any("FreeBootstrapper" in r.message and "configured=" in r.message for r in caplog.records)
```

Worth adding to prevent silent regression where someone deletes the summary call.

### Cross-check

Pre-flight grep before implementation to confirm all `is_ready()` call sites:

```bash
grep -rn "\.is_ready(" lite_bootstrap/ tests/ --include="*.py"
```

Expected: only the migration sites listed above. Any user-visible API contract change beyond the
listed call sites is out of scope and should be flagged.

## Exports / public API

`lite_bootstrap/exceptions.py`:
- **Remove** `InstrumentNotReadyWarning` class (hard delete; 4 weeks old, acceptable churn).
- **Keep** `InstrumentSkippedWarning` (base; document as forward-compat for additional skip categories) and `InstrumentDependencyMissingWarning` (subclass).

`lite_bootstrap/__init__.py`:
- Remove `InstrumentNotReadyWarning` from imports and `__all__`.
- `InstrumentSkippedWarning` and `InstrumentDependencyMissingWarning` remain exported.

`BaseBootstrapper.skipped_instruments` becomes a new public attribute. No deprecation needed for `instruments` — unchanged.

## Documentation

- `docs/introduction/configuration.md` — PR #86 added a 31-line section about the warning subclasses. Revise to: only `InstrumentDependencyMissingWarning` remains; not-configured instruments live in `bootstrapper.skipped_instruments` and the startup INFO log.
- `CLAUDE.md` — update the "Key design decisions" section to mention the `is_configured` classmethod precondition and the silent-skip-vs-warn distinction. Add a line to the `Optional dependencies` bullet noting that the new is_configured → check_dependencies order means missing-dep warnings only fire for instruments the user configured.

## Backward compatibility

`InstrumentNotReadyWarning` is publicly exported and was introduced 4 weeks ago. Hard removal:
anyone importing it from `lite_bootstrap` will get `ImportError` after this lands.

Decision: hard remove, no deprecation period. Consistent with the framing ("this was a bad idea").

`is_ready` instance method removal: also hard. Any user calling `instrument.is_ready()` will get
`AttributeError`. The call pattern is rare in user code (it's library-internal lifecycle).

Migration path for any user who hits these: rename `from lite_bootstrap import InstrumentNotReadyWarning`
imports to remove the line; replace `instrument.is_ready()` calls with `type(instrument).is_configured(config)`.

## Out of scope

- `InstrumentSkippedWarning` removal — only one subclass left after this PR, but keeping the base
  is cheap forward-compat. If another skip category arises later, it slots in cleanly.
- Per-bootstrapper logger configuration — the summary log uses the existing module-level logger.
  Customizing the log format/destination is a separate concern.
- Adding skipped-with-dep-missing to `skipped_instruments` data — only `is_configured`-skipped
  instruments live there. The dep-missing path still fires its warning (deployment surprise) and
  also doesn't populate `instruments`. Could be added later if there's demand.

## Risk

Medium. The cascade touches all instrument files, the bootstrapper base, exceptions, tests, and
public docs. The `is_configured` signature change is the migration cost; the bootstrapper reorder
is the substantive design improvement.

Mitigation: existing test suite covers all framework integration paths (FastAPI, Litestar, FastStream,
Free). After migration the suite must pass without `pytest.warns(InstrumentNotReadyWarning)` assertions
anywhere (one such site removed in `test_free_bootstrap.py`). Pre-flight grep for `is_ready` call
sites catches any missed migration.
