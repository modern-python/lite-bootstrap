# PR1 — Lifecycle & Teardown Correctness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land all 10 lifecycle/teardown fixes from the 2026-06-05 audit (LOG-1..9 + SEC-4) into one cohesive PR.

**Architecture:** Each fix is a small TDD cycle (failing test → implement → verify → commit). The sub-fixes are independent code-wise but share the "bootstrap promised, teardown didn't deliver" theme. Tasks are ordered to land the simplest invariants first (assert → raise), then the OTel teardown completeness, then the broader teardown-robustness fixes, then the app-reuse safety guards.

**Tech Stack:** Python 3.10+, `uv` workspace, `pytest`, `pytest-asyncio`, `ty` type checker, `ruff` formatter, `structlog`, `opentelemetry-sdk`, `sentry-sdk`, `fastmcp`, `litestar`, `faststream`, `fastapi`.

**Branch:** `fix/bug-audit-v2-pr1-lifecycle`

**Important deviation from sequencing doc:** During plan drafting, the OTel SDK's `set_tracer_provider` was found to be enforced as set-once via `_TRACER_PROVIDER_SET_ONCE.do_once(...)` (see `opentelemetry/trace/__init__.py:548-556` in the pinned version). A second `set_tracer_provider(NoOpTracerProvider())` would be logged-and-ignored, not applied. **LOG-1 therefore becomes a docstring-only change** that documents the OTel set-once constraint — the existing `shutdown()` call (added in CRIT-2) is the only practical teardown action. The audit's TEST-NEW-2 splits accordingly: the "shutdown called" half is already covered by `test_opentelemetry_instrument_teardown_shuts_down_tracer_provider`; the "global is reset" half is dropped because OTel doesn't support it.

---

## File Structure

Modifications to existing files only — no new files.

| File | What changes |
|------|-------------|
| `lite_bootstrap/bootstrappers/fastapi_bootstrapper.py` | `_narrow_app` assert → raise (Task 1); LOG-8 re-wrap guard (Task 10) |
| `lite_bootstrap/bootstrappers/fastmcp_bootstrapper.py` | LOG-7 re-attach guard (Task 9) |
| `lite_bootstrap/bootstrappers/faststream_bootstrapper.py` | LOG-4 broker logger restore (Task 6) |
| `lite_bootstrap/bootstrappers/litestar_bootstrapper.py` | LOG-6 WeakKeyDictionary cache (Task 8) |
| `lite_bootstrap/instruments/logging_instrument.py` | LOG-3 teardown try/finally (Task 5) |
| `lite_bootstrap/instruments/opentelemetry_instrument.py` | LOG-1 docstring (Task 3); LOG-2 logger restore (Task 4) |
| `lite_bootstrap/instruments/pyroscope_instrument.py` | Pyroscope precondition assert → raise (Task 2) |
| `lite_bootstrap/instruments/sentry_instrument.py` | LOG-9 teardown override (Task 7) |
| `tests/test_fastapi_bootstrap.py` | Tests for Tasks 1, 10 |
| `tests/test_fastmcp_bootstrap.py` | Test for Task 9 |
| `tests/test_faststream_bootstrap.py` | Test for Task 6 |
| `tests/test_litestar_bootstrap.py` | Test for Task 8 |
| `tests/instruments/test_logging_instrument.py` | Test for Task 5 |
| `tests/instruments/test_opentelemetry_instrument.py` | Tests for Tasks 3, 4 |
| `tests/instruments/test_pyroscope_instrument.py` | Test for Task 2 |
| `tests/instruments/test_sentry_instrument.py` | Test for Task 7; remove `finally: sentry_sdk.init()` workarounds |

---

## Task 1: LOG-5 part A — `_narrow_app` assert → explicit raise

**Files:**
- Modify: `lite_bootstrap/bootstrappers/fastapi_bootstrapper.py:78-80`
- Test: `tests/test_fastapi_bootstrap.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_fastapi_bootstrap.py`:

```python
import dataclasses

import pytest

from lite_bootstrap.bootstrappers.fastapi_bootstrapper import _narrow_app
from lite_bootstrap.types import UNSET


def test_narrow_app_raises_when_application_unset() -> None:
    # Build a config and forcibly reset application to UNSET to simulate the
    # invariant violation `_narrow_app` was guarding with an assert.
    config = FastAPIConfig()
    object.__setattr__(config, "application", UNSET)
    with pytest.raises(RuntimeError, match="application is UNSET"):
        _narrow_app(config)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
just test -- tests/test_fastapi_bootstrap.py::test_narrow_app_raises_when_application_unset
```

Expected: FAIL — current code uses `assert` which raises `AssertionError`, not `RuntimeError`. The `pytest.raises(RuntimeError, match=...)` will not match.

- [ ] **Step 3: Replace the assert**

In `lite_bootstrap/bootstrappers/fastapi_bootstrapper.py`, replace lines 78-80:

```python
def _narrow_app(config: "FastAPIConfig") -> "fastapi.FastAPI":
    if isinstance(config.application, UnsetType):
        msg = "FastAPIConfig.application is UNSET; __post_init__ did not run"
        raise RuntimeError(msg)
    return config.application
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
just test -- tests/test_fastapi_bootstrap.py::test_narrow_app_raises_when_application_unset
```

Expected: PASS.

- [ ] **Step 5: Verify nothing else broke**

```bash
just test -- tests/test_fastapi_bootstrap.py tests/test_fastapi_offline_docs.py
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add lite_bootstrap/bootstrappers/fastapi_bootstrapper.py tests/test_fastapi_bootstrap.py
git commit -m "fix: replace _narrow_app assert with RuntimeError (LOG-5/SEC-4 part A)

Bandit B101 flagged the assert as stripped under \`python -O\`. Replace with
explicit raise so the invariant holds under all Python optimization levels."
```

---

## Task 2: LOG-5 part B — Pyroscope precondition assert → explicit raise

**Files:**
- Modify: `lite_bootstrap/instruments/pyroscope_instrument.py:34-37`
- Test: `tests/instruments/test_pyroscope_instrument.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/instruments/test_pyroscope_instrument.py`:

```python
def test_pyroscope_bootstrap_raises_when_endpoint_unset() -> None:
    # Build a config that passes is_configured (endpoint set), then forcibly
    # clear the endpoint to simulate a caller bypassing the bootstrapper's
    # is_configured gate.
    config = _make_config()
    object.__setattr__(config, "pyroscope_endpoint", None)
    instrument = PyroscopeInstrument(bootstrap_config=config)
    with pytest.raises(RuntimeError, match="pyroscope_endpoint is unset"):
        instrument.bootstrap()
```

Verify `pytest` is already imported in the file (it is — see line 4).

- [ ] **Step 2: Run test to verify it fails**

```bash
just test -- tests/instruments/test_pyroscope_instrument.py::test_pyroscope_bootstrap_raises_when_endpoint_unset
```

Expected: FAIL — the current `assert` raises `AssertionError`, not `RuntimeError`.

- [ ] **Step 3: Replace the assert**

In `lite_bootstrap/instruments/pyroscope_instrument.py`, replace lines 34-37:

```python
def bootstrap(self) -> None:
    # is_configured() guarantees pyroscope_endpoint is set when called via the
    # bootstrapper. Direct callers bypassing is_configured see an explicit raise.
    if self.bootstrap_config.pyroscope_endpoint is None:
        msg = "pyroscope_endpoint is unset; PyroscopeInstrument.is_configured() should have returned False"
        raise RuntimeError(msg)
    namespace = self.bootstrap_config.opentelemetry_namespace
    tags = ({"service_namespace": namespace} if namespace else {}) | self.bootstrap_config.pyroscope_tags
    pyroscope.configure(
        application_name=self.bootstrap_config.opentelemetry_service_name or self.bootstrap_config.service_name,
        server_address=self.bootstrap_config.pyroscope_endpoint,
        sample_rate=self.bootstrap_config.pyroscope_sample_rate,
        tags=tags,
        **self.bootstrap_config.pyroscope_additional_params,
    )
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
just test -- tests/instruments/test_pyroscope_instrument.py::test_pyroscope_bootstrap_raises_when_endpoint_unset
```

Expected: PASS.

- [ ] **Step 5: Verify nothing else broke**

```bash
just test -- tests/instruments/test_pyroscope_instrument.py
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add lite_bootstrap/instruments/pyroscope_instrument.py tests/instruments/test_pyroscope_instrument.py
git commit -m "fix: replace pyroscope precondition assert with RuntimeError (LOG-5/SEC-4 part B)

Bandit B101 flagged the assert as stripped under \`python -O\`. Replace with
explicit raise. Resolves the second of the two bandit B101 findings in PR1."
```

---

## Task 3: LOG-1 — Document OTel `set_tracer_provider` constraint

**Files:**
- Modify: `lite_bootstrap/instruments/opentelemetry_instrument.py` (class docstring on `OpenTelemetryInstrument`)

**Context:** `opentelemetry.trace.set_tracer_provider` is enforced as set-once via `_TRACER_PROVIDER_SET_ONCE.do_once(...)` (verified against the pinned OTel SDK). A teardown that resets the global to a no-op would require touching private SDK internals (`_TRACER_PROVIDER` and `_TRACER_PROVIDER_SET_ONCE`). That hack is out of scope for this PR — we instead document the constraint so users understand the lifecycle. The audit's LOG-1 finding is downgraded to "documentation only" once the OTel API behavior is verified.

- [ ] **Step 1: Add docstring to `OpenTelemetryInstrument`**

In `lite_bootstrap/instruments/opentelemetry_instrument.py:80-86`, add a class docstring:

```python
@dataclasses.dataclass(kw_only=True, slots=True)
class OpenTelemetryInstrument(BaseInstrument[OpenTelemetryConfig]):
    """OpenTelemetry tracing instrument.

    Lifecycle note: ``bootstrap()`` calls ``opentelemetry.trace.set_tracer_provider``,
    which the OTel SDK enforces as **set-once per process** (subsequent calls log
    "Overriding of current TracerProvider is not allowed" and have no effect).
    ``teardown()`` calls ``shutdown()`` on the provider, which flushes batched
    spans and closes exporters, but it cannot reset the process-global pointer —
    callers of ``opentelemetry.trace.get_tracer_provider()`` after teardown will
    still receive the shut-down provider. The supported lifecycle is one
    ``OpenTelemetryInstrument`` per process; do not bootstrap a second instance.
    """

    not_ready_message = "opentelemetry_endpoint is empty and opentelemetry_log_traces is False"
    missing_dependency_message = "opentelemetry is not installed"
    _tracer_provider: "TracerProvider | None" = dataclasses.field(
        default_factory=lambda: None, init=False, repr=False, compare=False
    )
```

- [ ] **Step 2: Verify lint passes**

```bash
just lint-ci
```

Expected: green. Docstring change only.

- [ ] **Step 3: Commit**

```bash
git add lite_bootstrap/instruments/opentelemetry_instrument.py
git commit -m "docs: document OTel set_tracer_provider set-once constraint (LOG-1)

The OTel SDK enforces set_tracer_provider as set-once per process. teardown()
calls shutdown() (added in CRIT-2) but cannot reset the process-global pointer.
Document the supported lifecycle: one OpenTelemetryInstrument per process."
```

---

## Task 4: LOG-2 — Restore disabled OTel loggers on teardown

**Files:**
- Modify: `lite_bootstrap/instruments/opentelemetry_instrument.py`
- Test: `tests/instruments/test_opentelemetry_instrument.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/instruments/test_opentelemetry_instrument.py`:

```python
import logging


def test_opentelemetry_teardown_restores_disabled_loggers() -> None:
    instrumentor_logger = logging.getLogger("opentelemetry.instrumentation.instrumentor")
    trace_logger = logging.getLogger("opentelemetry.trace")
    # Capture pre-bootstrap state so the assertion is independent of test order.
    prior_instrumentor_disabled = instrumentor_logger.disabled
    prior_trace_disabled = trace_logger.disabled

    instrument = OpenTelemetryInstrument(
        bootstrap_config=OpenTelemetryConfig(opentelemetry_log_traces=True),
    )
    instrument.bootstrap()
    assert instrumentor_logger.disabled is True
    assert trace_logger.disabled is True

    instrument.teardown()

    assert instrumentor_logger.disabled is prior_instrumentor_disabled
    assert trace_logger.disabled is prior_trace_disabled
```

- [ ] **Step 2: Run test to verify it fails**

```bash
just test -- tests/instruments/test_opentelemetry_instrument.py::test_opentelemetry_teardown_restores_disabled_loggers
```

Expected: FAIL — current `teardown()` does not restore the `disabled` flags.

- [ ] **Step 3: Add capture-and-restore logic**

In `lite_bootstrap/instruments/opentelemetry_instrument.py`, modify the `OpenTelemetryInstrument` dataclass (around line 80-86 — keep the docstring from Task 3) to add a new init=False field:

```python
@dataclasses.dataclass(kw_only=True, slots=True)
class OpenTelemetryInstrument(BaseInstrument[OpenTelemetryConfig]):
    """OpenTelemetry tracing instrument.

    Lifecycle note: ``bootstrap()`` calls ``opentelemetry.trace.set_tracer_provider``,
    which the OTel SDK enforces as **set-once per process** (subsequent calls log
    "Overriding of current TracerProvider is not allowed" and have no effect).
    ``teardown()`` calls ``shutdown()`` on the provider, which flushes batched
    spans and closes exporters, but it cannot reset the process-global pointer —
    callers of ``opentelemetry.trace.get_tracer_provider()`` after teardown will
    still receive the shut-down provider. The supported lifecycle is one
    ``OpenTelemetryInstrument`` per process; do not bootstrap a second instance.
    """

    not_ready_message = "opentelemetry_endpoint is empty and opentelemetry_log_traces is False"
    missing_dependency_message = "opentelemetry is not installed"
    _tracer_provider: "TracerProvider | None" = dataclasses.field(
        default_factory=lambda: None, init=False, repr=False, compare=False
    )
    _prior_logger_disabled: dict[str, bool] = dataclasses.field(
        default_factory=dict, init=False, repr=False, compare=False
    )
```

In the same file, modify `bootstrap()` (lines 107-109 currently set `.disabled = True` on two loggers). Replace those two lines with capture-then-set:

```python
def bootstrap(self) -> None:
    for logger_name in ("opentelemetry.instrumentation.instrumentor", "opentelemetry.trace"):
        otel_logger = logging.getLogger(logger_name)
        self._prior_logger_disabled[logger_name] = otel_logger.disabled
        otel_logger.disabled = True
    attributes = {
        resources.SERVICE_NAME: self.bootstrap_config.opentelemetry_service_name
        or self.bootstrap_config.service_name,
        resources.TELEMETRY_SDK_LANGUAGE: "python",
        resources.SERVICE_NAMESPACE: self.bootstrap_config.opentelemetry_namespace,
        resources.SERVICE_VERSION: self.bootstrap_config.service_version,
        resources.CONTAINER_NAME: self.bootstrap_config.opentelemetry_container_name,
    }
    # ... (rest of bootstrap body unchanged from current code)
```

In `teardown()` (lines 146-156), add restore logic. Place it after the uninstrument loop, before the `_tracer_provider.shutdown()` block so restoration happens even if shutdown raises:

```python
def teardown(self) -> None:
    for one_instrumentor in self.bootstrap_config.opentelemetry_instrumentors:
        if isinstance(one_instrumentor, InstrumentorWithParams):
            one_instrumentor.instrumentor.uninstrument(**one_instrumentor.additional_params)
        else:
            one_instrumentor.uninstrument()
    for logger_name, prior in self._prior_logger_disabled.items():
        logging.getLogger(logger_name).disabled = prior
    self._prior_logger_disabled.clear()
    if self._tracer_provider is not None:
        try:
            self._tracer_provider.shutdown()
        finally:
            self._tracer_provider = None
```

- [ ] **Step 4: Run the new test to verify it passes**

```bash
just test -- tests/instruments/test_opentelemetry_instrument.py::test_opentelemetry_teardown_restores_disabled_loggers
```

Expected: PASS.

- [ ] **Step 5: Verify the rest of the OTel test file**

```bash
just test -- tests/instruments/test_opentelemetry_instrument.py
```

Expected: all green. In particular `test_opentelemetry_instrument_teardown_resets_tracer_provider_when_shutdown_raises` should still pass because the new `_prior_logger_disabled` restore runs **before** the shutdown raise.

- [ ] **Step 6: Commit**

```bash
git add lite_bootstrap/instruments/opentelemetry_instrument.py tests/instruments/test_opentelemetry_instrument.py
git commit -m "fix: restore OTel loggers' disabled state on teardown (LOG-2)

bootstrap() previously set opentelemetry.instrumentation.instrumentor and
opentelemetry.trace loggers to disabled=True unconditionally, with no symmetric
restoration. Capture the pre-bootstrap state and restore on teardown so unrelated
code in the same process retains its expected logger configuration."
```

---

## Task 5: LOG-3 — Protect `LoggingInstrument.teardown()` root-handler loop

**Files:**
- Modify: `lite_bootstrap/instruments/logging_instrument.py:163-178`
- Test: `tests/instruments/test_logging_instrument.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/instruments/test_logging_instrument.py`:

```python
def test_logging_instrument_teardown_aggregates_handler_close_errors() -> None:
    instrument = LoggingInstrument(
        bootstrap_config=LoggingConfig(logging_buffer_capacity=0),
    )
    instrument.bootstrap()
    root_logger = logging.getLogger()

    # Find the StreamHandler added by _configure_foreign_loggers and patch its close.
    bootstrap_added = [h for h in root_logger.handlers if isinstance(h, logging.StreamHandler)]
    assert bootstrap_added, "bootstrap should have added at least one StreamHandler to root"
    target_handler = bootstrap_added[0]

    with patch.object(target_handler, "close", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError, match="boom"):
            instrument.teardown()

    # After teardown despite the raise, post-loop cleanup must have completed:
    assert instrument._logger_factory is None  # noqa: SLF001
    assert root_logger.level == logging.WARNING
    # And the broken handler must have been removed from root despite raising.
    assert target_handler not in root_logger.handlers
```

`patch` is already imported in the file (see line 3); `pytest` and `logging` are already in scope.

- [ ] **Step 2: Run test to verify it fails**

```bash
just test -- tests/instruments/test_logging_instrument.py::test_logging_instrument_teardown_aggregates_handler_close_errors
```

Expected: FAIL — current `teardown` would let `h.close()` raise mid-loop; `_logger_factory.close_handlers()` never runs and `_logger_factory` stays non-None. The level reset also doesn't fire.

- [ ] **Step 3: Rewrite teardown with try/finally**

In `lite_bootstrap/instruments/logging_instrument.py`, replace `teardown()` (lines 163-178):

```python
def teardown(self) -> None:
    """Reset structlog and root logger.

    Root logger level is unconditionally set to WARNING; pre-existing user configuration is overwritten.

    Best-effort cleanup: errors from individual ``handler.close()`` calls are collected and
    re-raised after the rest of teardown (level reset, factory close) completes, so a single
    misbehaving handler can't prevent the instrument from releasing the rest of its resources.
    """
    structlog.reset_defaults()
    root_logger = logging.getLogger()
    close_errors: list[BaseException] = []
    try:
        for h in root_logger.handlers[:]:
            root_logger.removeHandler(h)
            try:
                h.close()
            except Exception as e:  # noqa: BLE001, PERF203
                close_errors.append(e)
        root_logger.setLevel(logging.WARNING)
    finally:
        if self._logger_factory is not None:
            try:
                self._logger_factory.close_handlers()
            finally:
                self._logger_factory = None
    if close_errors:
        raise close_errors[0]
```

- [ ] **Step 4: Run the new test to verify it passes**

```bash
just test -- tests/instruments/test_logging_instrument.py::test_logging_instrument_teardown_aggregates_handler_close_errors
```

Expected: PASS.

- [ ] **Step 5: Verify the rest of the logging tests**

```bash
just test -- tests/instruments/test_logging_instrument.py
```

Expected: all green. In particular `test_logging_instrument_teardown_resets_factory_when_close_handlers_raises` (existing) still asserts that `_logger_factory` is nulled on close_handlers raise — the new try/finally preserves that behavior.

- [ ] **Step 6: Commit**

```bash
git add lite_bootstrap/instruments/logging_instrument.py tests/instruments/test_logging_instrument.py
git commit -m "fix: protect LoggingInstrument.teardown root-handler loop (LOG-3)

A raise from handler.close() mid-loop previously left remaining handlers
attached, skipped the root-level reset, and never called close_handlers on the
factory. Wrap in try/finally and aggregate close errors so the rest of teardown
completes before the first error is re-raised."
```

---

## Task 6: LOG-4 — Restore broker logger storage on FastStream teardown

**Files:**
- Modify: `lite_bootstrap/bootstrappers/faststream_bootstrapper.py:110-120`
- Test: `tests/test_faststream_bootstrap.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_faststream_bootstrap.py`:

```python
def test_faststream_teardown_restores_broker_params_storage(broker: RedisBroker) -> None:
    config = build_faststream_config(broker=broker)
    original_storage = broker.config.logger.params_storage
    bootstrapper = FastStreamBootstrapper(bootstrap_config=config)
    bootstrapper.bootstrap()
    assert isinstance(broker.config.logger.params_storage, ManualLoggerStorage)
    assert broker.config.logger.params_storage is not original_storage

    bootstrapper.teardown()

    assert broker.config.logger.params_storage is original_storage
```

`ManualLoggerStorage` and `RedisBroker` are already imported in the file (lines 11-12); `build_faststream_config` is defined locally (line 34).

- [ ] **Step 2: Run test to verify it fails**

```bash
just test -- tests/test_faststream_bootstrap.py::test_faststream_teardown_restores_broker_params_storage
```

Expected: FAIL — `FastStreamLoggingInstrument` has no `teardown()` override, so `params_storage` stays as the `ManualLoggerStorage` set by bootstrap.

- [ ] **Step 3: Add snapshot field and teardown override**

In `lite_bootstrap/bootstrappers/faststream_bootstrapper.py`, modify `FastStreamLoggingInstrument` (lines 110-120) to add a snapshot field and a teardown override:

```python
@dataclasses.dataclass(kw_only=True)
class FastStreamLoggingInstrument(LoggingInstrument):
    bootstrap_config: FastStreamConfig
    _prior_broker_params_storage: typing.Any = dataclasses.field(
        default=None, init=False, repr=False, compare=False
    )
    _broker_logger_replaced: bool = dataclasses.field(
        default=False, init=False, repr=False, compare=False
    )

    def bootstrap(self) -> None:
        super().bootstrap()
        broker = self.bootstrap_config.application.broker
        if broker is not None and import_checker.is_structlog_installed and import_checker.is_faststream_installed:
            logger = structlog.get_logger("faststream")
            logger.setLevel(self.bootstrap_config.faststream_log_level)
            self._prior_broker_params_storage = broker.config.logger.params_storage
            broker.config.logger.params_storage = ManualLoggerStorage(logger)
            self._broker_logger_replaced = True

    def teardown(self) -> None:
        if self._broker_logger_replaced:
            broker = self.bootstrap_config.application.broker
            if broker is not None:
                broker.config.logger.params_storage = self._prior_broker_params_storage
            self._broker_logger_replaced = False
            self._prior_broker_params_storage = None
        super().teardown()
```

- [ ] **Step 4: Run the new test to verify it passes**

```bash
just test -- tests/test_faststream_bootstrap.py::test_faststream_teardown_restores_broker_params_storage
```

Expected: PASS.

- [ ] **Step 5: Verify the rest of the FastStream tests**

```bash
just test -- tests/test_faststream_bootstrap.py
```

Expected: all green. In particular `test_faststream_logging_instrument_injects_structlog_logger` should still pass — it inspects state mid-bootstrap, before teardown.

- [ ] **Step 6: Commit**

```bash
git add lite_bootstrap/bootstrappers/faststream_bootstrapper.py tests/test_faststream_bootstrap.py
git commit -m "fix: restore broker logger storage on FastStreamLoggingInstrument teardown (LOG-4)

bootstrap() mutates broker.config.logger.params_storage to inject a structlog
logger; teardown() now captures and restores the original value. Symmetric with
LoggingInstrument's parent teardown, which still runs via super()."
```

---

## Task 7: LOG-9 — Add `SentryInstrument.teardown()`

**Files:**
- Modify: `lite_bootstrap/instruments/sentry_instrument.py:94-125`
- Modify: `tests/instruments/test_sentry_instrument.py` (add test + drop workarounds)

- [ ] **Step 1: Write the failing test**

Add to `tests/instruments/test_sentry_instrument.py`:

```python
def test_sentry_teardown_disables_sdk(minimal_sentry_config: SentryConfig) -> None:
    instrument = SentryInstrument(bootstrap_config=minimal_sentry_config)
    instrument.bootstrap()
    assert sentry_sdk.Hub.current.client is not None

    instrument.teardown()

    # sentry_sdk.init() with no DSN disables the SDK; the Hub's client either becomes
    # None or has dsn=None depending on the SDK version. Both indicate "disabled".
    client = sentry_sdk.Hub.current.client
    assert client is None or client.dsn is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
just test -- tests/instruments/test_sentry_instrument.py::test_sentry_teardown_disables_sdk
```

Expected: FAIL — `SentryInstrument` currently has no `teardown()` override, so the SDK stays initialized with the test DSN.

- [ ] **Step 3: Add the teardown override**

In `lite_bootstrap/instruments/sentry_instrument.py`, extend `SentryInstrument` (after `bootstrap()`, around line 125):

```python
def teardown(self) -> None:
    """Flush pending events and reset the SDK to a no-op state.

    Calling ``sentry_sdk.init()`` with no DSN disables further event capture. This
    cleans up after a bootstrap so the same process can be torn down and re-tested
    without leaking the previous DSN/transport into subsequent code.
    """
    sentry_sdk.flush(timeout=2)
    sentry_sdk.init()
```

- [ ] **Step 4: Run the new test to verify it passes**

```bash
just test -- tests/instruments/test_sentry_instrument.py::test_sentry_teardown_disables_sdk
```

Expected: PASS.

- [ ] **Step 5: Drop the redundant `finally: sentry_sdk.init()` workarounds**

The existing tests at `tests/instruments/test_sentry_instrument.py:43` and `:65` use
`finally: sentry_sdk.init()` to reset the SDK between test cases. With the new
`teardown()` in place, callers that go through the bootstrapper / instrument will get the
reset automatically. Update the two tests so the cleanup happens via `instrument.teardown()`:

Replace `test_sentry_instrument_with_raise` (lines 36-43):

```python
def test_sentry_instrument_with_raise(minimal_sentry_config: SentryConfig, sentry_mock: SentryTestTransport) -> None:
    instrument = SentryInstrument(bootstrap_config=minimal_sentry_config)
    instrument.bootstrap()

    try:
        std_logger.error("some error")
        assert len(sentry_mock.mock_envelopes) == 1
    finally:
        instrument.teardown()
```

Replace `test_sentry_instrument_with_structlog_error` (lines 46-66):

```python
def test_sentry_instrument_with_structlog_error(
    minimal_sentry_config: SentryConfig, sentry_mock: SentryTestTransport, logging_mock: LoggingMock
) -> None:
    sentry_instrument = SentryInstrument(bootstrap_config=minimal_sentry_config)
    sentry_instrument.bootstrap()
    logging_instrument = LoggingInstrument(
        bootstrap_config=LoggingConfig(
            logging_unset_handlers=["uvicorn"],
            logging_buffer_capacity=0,
            service_debug=False,
            logging_extra_processors=[logging_mock],
        )
    )
    logging_instrument.bootstrap()

    try:
        logger.error("some error")
        logger.error("some error, skipping sentry", skip_sentry=True)
        assert len(sentry_mock.mock_envelopes) == 1
    finally:
        logging_instrument.teardown()
        sentry_instrument.teardown()
```

- [ ] **Step 6: Run the full sentry test file**

```bash
just test -- tests/instruments/test_sentry_instrument.py
```

Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add lite_bootstrap/instruments/sentry_instrument.py tests/instruments/test_sentry_instrument.py
git commit -m "fix: add SentryInstrument.teardown that disables the SDK (LOG-9)

bootstrap() called sentry_sdk.init() but no teardown reset the global state.
Process-local tests had to call sentry_sdk.init() in finally blocks as a
workaround; those are now replaced by instrument.teardown(). flush() drains
in-flight events before the reset."
```

---

## Task 8: LOG-6 — `WeakKeyDictionary` for Litestar OTel cache

**Files:**
- Modify: `lite_bootstrap/bootstrappers/litestar_bootstrapper.py:75-99`
- Test: `tests/test_litestar_bootstrap.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_litestar_bootstrap.py`:

```python
import gc
import weakref


def test_litestar_otel_apps_cache_evicts_dead_refs() -> None:
    from lite_bootstrap.bootstrappers.litestar_bootstrapper import (
        LitestarOpenTelemetryInstrumentationMiddleware,
    )
    from opentelemetry.sdk.trace import TracerProvider

    tracer_provider = TracerProvider()
    middleware = LitestarOpenTelemetryInstrumentationMiddleware(
        tracer_provider=tracer_provider,
        excluded_urls=set(),
    )

    async def transient_app(scope: dict, receive: object, send: object) -> None:  # noqa: ARG001
        return None

    weak_app = weakref.ref(transient_app)
    middleware._otel_apps[transient_app] = "marker"  # noqa: SLF001 — direct cache poke
    assert weak_app() is not None
    assert len(middleware._otel_apps) == 1  # noqa: SLF001

    del transient_app
    gc.collect()

    assert weak_app() is None
    assert len(middleware._otel_apps) == 0  # noqa: SLF001
```

- [ ] **Step 2: Run test to verify it fails**

```bash
just test -- tests/test_litestar_bootstrap.py::test_litestar_otel_apps_cache_evicts_dead_refs
```

Expected: FAIL — `_otel_apps` is a `dict[int, ASGIApp]`; the integer key doesn't evict when the `transient_app` is GC'd. Also fails to even accept `transient_app` as a key (current code uses `id(next_app)`).

The test sets `middleware._otel_apps[transient_app] = "marker"` to verify the dict-like API expects the app object as the key. This will need to be a real WeakKeyDictionary for the assertion to pass.

- [ ] **Step 3: Replace cache with WeakKeyDictionary**

In `lite_bootstrap/bootstrappers/litestar_bootstrapper.py`, add `import weakref` near the top of the file (alongside the existing imports) and replace lines 75-99:

```python
if import_checker.is_litestar_opentelemetry_installed:

    class LitestarOpenTelemetryInstrumentationMiddleware(ASGIMiddleware):
        def __init__(self, tracer_provider: "TracerProvider", excluded_urls: set[str]) -> None:
            self._tracer_provider = tracer_provider
            self._excluded_urls = ",".join(excluded_urls)
            # WeakKeyDictionary so wrapper apps are evicted when Litestar drops the
            # next_app reference (hot reload, plugin add/remove, AppConfig rebuild).
            # Falls back gracefully — apps that don't support weak refs are simply
            # not cached.
            self._otel_apps: "weakref.WeakKeyDictionary[ASGIApp, ASGIApp]" = weakref.WeakKeyDictionary()

        async def handle(
            self,
            scope: "Scope",
            receive: "Receive",
            send: "Send",
            next_app: "ASGIApp",
        ) -> None:
            otel_app = self._otel_apps.get(next_app)
            if otel_app is None:
                otel_app = OpenTelemetryMiddleware(
                    app=next_app,
                    default_span_details=build_litestar_route_details_from_scope,
                    excluded_urls=self._excluded_urls,
                    tracer_provider=self._tracer_provider,
                )
                try:
                    self._otel_apps[next_app] = otel_app  # ty: ignore[invalid-assignment]
                except TypeError:
                    # next_app doesn't support weak references; skip caching for it.
                    pass
            await otel_app(scope, receive, send)  # ty: ignore[invalid-argument-type]
```

- [ ] **Step 4: Run the new test to verify it passes**

```bash
just test -- tests/test_litestar_bootstrap.py::test_litestar_otel_apps_cache_evicts_dead_refs
```

Expected: PASS.

- [ ] **Step 5: Verify the rest of the Litestar tests**

```bash
just test -- tests/test_litestar_bootstrap.py
```

Expected: all green. In particular `test_litestar_otel_span_naming` exercises the cache hit path on real requests.

- [ ] **Step 6: Commit**

```bash
git add lite_bootstrap/bootstrappers/litestar_bootstrapper.py tests/test_litestar_bootstrap.py
git commit -m "fix: use WeakKeyDictionary for Litestar OTel app cache (LOG-6)

The previous dict[int, ASGIApp] keyed by id() never evicted, holding wrapper
OpenTelemetryMiddleware instances alive after Litestar dropped the next_app
reference. Switch to weakref.WeakKeyDictionary so wrappers GC with their apps.
Skip caching gracefully when an app doesn't support weak references."
```

---

## Task 9: LOG-7 — Guard against double `_TeardownProvider` attachment on FastMCP

**Files:**
- Modify: `lite_bootstrap/bootstrappers/fastmcp_bootstrapper.py:152-154`
- Test: `tests/test_fastmcp_bootstrap.py`

**Context:** FastMCP's `add_provider` appends to `self.providers` (verified at
`fastmcp/server/providers/aggregate.py:116`). The list is inherited from `AggregateProvider`
(`fastmcp/server/providers/aggregate.py:88`). We can iterate `application.providers` to
check for existing `_TeardownProvider` instances.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_fastmcp_bootstrap.py`:

```python
import warnings


def test_second_fastmcp_bootstrapper_on_same_app_warns_not_stacks() -> None:
    application = FastMCP()
    config_a = FastMcpConfig(application=application, service_name="a")
    bootstrapper_a = FastMcpBootstrapper(bootstrap_config=config_a)
    providers_after_first = list(application.providers)

    config_b = FastMcpConfig(application=application, service_name="b")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        FastMcpBootstrapper(bootstrap_config=config_b)

    matching = [w for w in caught if "_TeardownProvider" in str(w.message)]
    assert matching, "expected warning about existing _TeardownProvider"
    assert list(application.providers) == providers_after_first, (
        "second bootstrapper must not stack another _TeardownProvider"
    )

    bootstrapper_a.teardown()
```

`FastMCP` and `FastMcpConfig` are already imported in the file.

- [ ] **Step 2: Run test to verify it fails**

```bash
just test -- tests/test_fastmcp_bootstrap.py::test_second_fastmcp_bootstrapper_on_same_app_warns_not_stacks
```

Expected: FAIL — current code unconditionally calls `add_provider`, so `application.providers` would grow by one and no warning is emitted.

- [ ] **Step 3: Add the re-attach guard**

In `lite_bootstrap/bootstrappers/fastmcp_bootstrapper.py`, add `import warnings` at the top
of the file (alongside the existing imports) and modify `__init__` (lines 152-154):

```python
def __init__(self, bootstrap_config: FastMcpConfig) -> None:
    super().__init__(bootstrap_config)
    if any(isinstance(p, _TeardownProvider) for p in self.bootstrap_config.application.providers):
        warnings.warn(
            "FastMCP application already has a _TeardownProvider attached; "
            "skipping re-attachment. Construct one FastMcpBootstrapper per application.",
            stacklevel=2,
        )
        return
    self.bootstrap_config.application.add_provider(_TeardownProvider(self.teardown))
```

- [ ] **Step 4: Run the new test to verify it passes**

```bash
just test -- tests/test_fastmcp_bootstrap.py::test_second_fastmcp_bootstrapper_on_same_app_warns_not_stacks
```

Expected: PASS.

- [ ] **Step 5: Verify the rest of the FastMCP tests**

```bash
just test -- tests/test_fastmcp_bootstrap.py
```

Expected: all green. The existing `test_fastmcp_teardown_runs_via_asgi_lifespan` confirms a single attachment still fires teardown on lifespan shutdown.

- [ ] **Step 6: Commit**

```bash
git add lite_bootstrap/bootstrappers/fastmcp_bootstrapper.py tests/test_fastmcp_bootstrap.py
git commit -m "fix: guard against double _TeardownProvider attachment on FastMCP (LOG-7)

Constructing two FastMcpBootstrappers around the same application previously
stacked two _TeardownProvider instances, doubling the teardown call on shutdown.
Detect an existing _TeardownProvider in application.providers and skip re-attach
with a warning."
```

---

## Task 10: LOG-8 — Guard against double lifespan wrapping on FastAPI

**Files:**
- Modify: `lite_bootstrap/bootstrappers/fastapi_bootstrapper.py:197-205`
- Test: `tests/test_fastapi_bootstrap.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_fastapi_bootstrap.py`:

```python
def test_second_fastapi_bootstrapper_on_same_app_warns_not_stacks(fastapi_config: FastAPIConfig) -> None:
    application = fastapi.FastAPI()
    config_a = dataclasses.replace(fastapi_config, application=application)
    FastAPIBootstrapper(bootstrap_config=config_a)
    lifespan_after_first = application.router.lifespan_context

    config_b = dataclasses.replace(fastapi_config, application=application)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        FastAPIBootstrapper(bootstrap_config=config_b)

    matching = [w for w in caught if "lifespan" in str(w.message).lower()]
    assert matching, "expected warning about existing lite-bootstrap lifespan"
    assert application.router.lifespan_context is lifespan_after_first, (
        "second bootstrapper must not re-wrap the lifespan"
    )
```

`warnings` will need to be imported at the top of the test file (it is — line 4 in current state via no import; verify via Read before committing). If missing, add `import warnings`.

- [ ] **Step 2: Run test to verify it fails**

```bash
just test -- tests/test_fastapi_bootstrap.py::test_second_fastapi_bootstrapper_on_same_app_warns_not_stacks
```

Expected: FAIL — current `__init__` unconditionally wraps `lifespan_context`, so the second bootstrapper stacks another layer.

- [ ] **Step 3: Add the re-wrap guard**

In `lite_bootstrap/bootstrappers/fastapi_bootstrapper.py`, modify the `FastAPIBootstrapper.__init__` (lines 197-205):

```python
def __init__(self, bootstrap_config: FastAPIConfig) -> None:
    super().__init__(bootstrap_config)

    application = _narrow_app(self.bootstrap_config)
    if getattr(application.state, "lite_bootstrap_lifespan_attached", False):
        warnings.warn(
            "FastAPI application already has a lite-bootstrap lifespan wrapper attached; "
            "skipping re-wrap. Construct one FastAPIBootstrapper per application.",
            stacklevel=2,
        )
        return
    application.state.lite_bootstrap_lifespan_attached = True
    old_lifespan_manager = application.router.lifespan_context
    application.router.lifespan_context = _merge_lifespan_context(
        old_lifespan_manager,
        self.lifespan_manager,
    )
```

`warnings` is already imported in this file (line 4). `application.state` is the standard Starlette state container — assignment to arbitrary attributes is supported.

- [ ] **Step 4: Run the new test to verify it passes**

```bash
just test -- tests/test_fastapi_bootstrap.py::test_second_fastapi_bootstrapper_on_same_app_warns_not_stacks
```

Expected: PASS.

- [ ] **Step 5: Verify the rest of the FastAPI tests**

```bash
just test -- tests/test_fastapi_bootstrap.py
```

Expected: all green. The existing `test_fastapi_bootstrap` exercises the single-attachment lifespan path on a real ASGI client.

- [ ] **Step 6: Commit**

```bash
git add lite_bootstrap/bootstrappers/fastapi_bootstrapper.py tests/test_fastapi_bootstrap.py
git commit -m "fix: guard against double lifespan wrapping on FastAPI (LOG-8)

Constructing two FastAPIBootstrappers around the same application previously
stacked two lifespan wrappers, calling teardown twice on shutdown. Detect the
sentinel on application.state and skip re-wrap with a warning. Idempotent
teardown (CRIT-3) means the prior behavior was harmless, but this removes the
log noise and confusing stack depth."
```

---

## Final verification

- [ ] **Step 1: Full test suite**

```bash
just test
```

Expected: all green. Coverage stays at 100% (`--cov-fail-under=100` from `pyproject.toml`).

- [ ] **Step 2: Lint (includes ty type check)**

```bash
just lint-ci
```

Expected: all green.

- [ ] **Step 3: Bandit clean (manual verification of LOG-5/SEC-4 closure)**

```bash
bandit -r lite_bootstrap 2>&1 | grep -c "B101"
```

Expected: `0` (zero remaining B101 findings after Tasks 1 and 2).

- [ ] **Step 4: Confirm the commit log shape**

```bash
git log --oneline origin/main..HEAD
```

Expected: 10 commits, each titled `fix:` (or `docs:` for Task 3), each scoped to a single finding. Optional: rebase to squash trivially-related commits if reviewer prefers — recommend keeping them separate so the PR review can match commits to audit IDs.

---

## Self-review checklist (run after the plan finishes)

1. **Coverage of PR1 findings:** LOG-1 (Task 3) · LOG-2 (Task 4) · LOG-3 (Task 5) · LOG-4 (Task 6) · LOG-5 (Tasks 1+2) · LOG-6 (Task 8) · LOG-7 (Task 9) · LOG-8 (Task 10) · LOG-9 (Task 7) · SEC-4 (Tasks 1+2). All 10.
2. **TEST-NEW coverage:** TEST-NEW-2 (Task 4 — logger restore; LOG-1's "shutdown called" already exists in the suite per the audit) · TEST-NEW-3 (Task 5) · TEST-NEW-4 (Task 6) · TEST-NEW-5 (Tasks 8, 9, 10). All four mapped.
3. **No placeholders:** every step has the exact file path, line numbers where relevant, complete code blocks, exact `just test -- <selector>` command, and the expected outcome.
4. **Type consistency:** `OpenTelemetryInstrument._prior_logger_disabled: dict[str, bool]` (Task 4), `FastStreamLoggingInstrument._prior_broker_params_storage / _broker_logger_replaced` (Task 6), `LitestarOpenTelemetryInstrumentationMiddleware._otel_apps: weakref.WeakKeyDictionary[ASGIApp, ASGIApp]` (Task 8). All consistent between definition and usage.
5. **Commit isolation:** each task ends with a single commit scoped to its finding ID, so PR review can land/revert at the task level if needed.
