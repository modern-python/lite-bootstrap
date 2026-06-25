# 05.01-bug-audit-v2 — implementation plan

> Multi-PR plan: this change shipped as a sequence of PRs. Each section below was an independent per-PR plan; they are preserved verbatim here as the bundle's single `plan.md` (the spec is [`design.md`](./design.md)).


---

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


---

# PR2 — Config UX & Security Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land six config-layer fixes from the 2026-06-05 audit (UX-1, UX-2, UX-3, SEC-1, SEC-2, SEC-3 + folded TEST-NEW-1 and TEST-NEW-6) in one PR.

**Architecture:** Each fix is a small TDD cycle. The work all happens at config-construction time or at the user-facing helper layer — no instrument lifecycle changes. Tasks are ordered to land additive UX improvements first (UX-1, UX-2, UX-3), then the security validators (SEC-1, SEC-2, SEC-3) which are slightly more cross-cutting (SEC-2 introduces an `OpenTelemetryConfig.__post_init__` that interacts with the FastAPIConfig override touched in Task 1).

**Tech Stack:** Python 3.10+, `uv` workspace, `pytest` (with `pytest-asyncio`), `ty` type checker, `ruff` formatter, `structlog`, `prometheus_client`, `opentelemetry-sdk`, `fastapi`, `litestar`, `faststream`, `fastmcp`.

**Branch:** `fix/bug-audit-v2-pr2-config-security` (branch off `main` after PR1 merges, or off PR1's branch if parallel work is desired).

**Sequencing prerequisite:** PR1 should merge first. PR2 doesn't structurally depend on PR1, but Task 5 introduces `OpenTelemetryConfig.__post_init__` which interacts with the `_prior_logger_disabled` field added in PR1 Task 4 (both touch `OpenTelemetryConfig`/`OpenTelemetryInstrument`). Rebasing PR2 onto a merged PR1 keeps the conflict resolution trivial.

---

## File Structure

Modifications to existing files only — no new files.

| File | What changes |
|------|-------------|
| `lite_bootstrap/bootstrappers/fastapi_bootstrapper.py` | Move user-app field overrides into UnsetType branch (Task 1); add `super().__post_init__()` for Task 5 cascade |
| `lite_bootstrap/bootstrappers/faststream_bootstrapper.py` | Add `prometheus_collector_registry` field + thread to instrument (Task 2); add `opentelemetry_excluded_urls` field (Task 3) |
| `lite_bootstrap/helpers/fastapi_helpers.py` | Validate `root_path` via `is_valid_path` + fall back on warning (Task 4) |
| `lite_bootstrap/instruments/cors_instrument.py` | Add `__post_init__` to `CorsConfig` rejecting wildcard + credentials combo (Task 6) |
| `lite_bootstrap/instruments/opentelemetry_instrument.py` | Add `__post_init__` to `OpenTelemetryConfig` warning on insecure non-local endpoint (Task 5) |
| `tests/test_fastapi_bootstrap.py` | Test for Task 1 |
| `tests/test_fastapi_offline_docs.py` | Test for Task 4 |
| `tests/test_faststream_bootstrap.py` | Tests for Tasks 2, 3 |
| `tests/instruments/test_cors_instrument.py` | Test for Task 6 |
| `tests/instruments/test_opentelemetry_instrument.py` | Test for Task 5 |

---

## Task 1: UX-1 — `FastAPIConfig` respects user app's title/debug/version

**Files:**
- Modify: `lite_bootstrap/bootstrappers/fastapi_bootstrapper.py:58-75`
- Test: `tests/test_fastapi_bootstrap.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_fastapi_bootstrap.py` (at the bottom, after existing tests):

```python
def test_user_supplied_app_keeps_title_version_debug() -> None:
    user_app = fastapi.FastAPI(title="user-title", version="9.9.9", debug=False)
    config = FastAPIConfig(
        application=user_app,
        service_name="lite-name",
        service_version="1.0.0",
        service_debug=True,
    )
    assert config.application is user_app
    assert user_app.title == "user-title"
    assert user_app.version == "9.9.9"
    assert user_app.debug is False
```

`fastapi`, `FastAPIConfig` are already imported in this file.

- [ ] **Step 2: Run test to verify it fails**

```bash
just test -- tests/test_fastapi_bootstrap.py::test_user_supplied_app_keeps_title_version_debug
```

Expected: FAIL — current `__post_init__` overwrites `application.title/.debug/.version` with the config defaults even when the user supplies a pre-configured app.

- [ ] **Step 3: Move the field overrides into the UnsetType branch**

In `lite_bootstrap/bootstrappers/fastapi_bootstrapper.py`, the current `__post_init__` (lines 58-75) reads:

```python
def __post_init__(self) -> None:
    if not import_checker.is_fastapi_installed:
        msg = "fastapi is not installed"
        raise ConfigurationError(msg)

    if isinstance(self.application, UnsetType):
        application = fastapi.FastAPI(docs_url=self.swagger_path, **self.application_kwargs)
        # FastAPIConfig stays frozen for user-facing immutability; __post_init__ needs
        # to set application after construction, so we bypass the freeze here.
        object.__setattr__(self, "application", application)
    else:
        application = self.application
        if self.application_kwargs:
            warnings.warn("application_kwargs must be used without application", stacklevel=2)

    application.title = self.service_name
    application.debug = self.service_debug
    application.version = self.service_version
```

Replace with:

```python
def __post_init__(self) -> None:
    if not import_checker.is_fastapi_installed:
        msg = "fastapi is not installed"
        raise ConfigurationError(msg)

    if isinstance(self.application, UnsetType):
        application = fastapi.FastAPI(docs_url=self.swagger_path, **self.application_kwargs)
        # FastAPIConfig stays frozen for user-facing immutability; __post_init__ needs
        # to set application after construction, so we bypass the freeze here.
        object.__setattr__(self, "application", application)
        application.title = self.service_name
        application.debug = self.service_debug
        application.version = self.service_version
    elif self.application_kwargs:
        warnings.warn("application_kwargs must be used without application", stacklevel=2)
```

Key changes:
- Three `application.X = ...` lines moved inside the `if isinstance(...)` branch
- The `else: application = self.application` line is gone (no longer needed since we don't reference `application` after the branch)
- `else: if self.application_kwargs:` collapsed to `elif self.application_kwargs:`

- [ ] **Step 4: Run the new test to verify it passes**

```bash
just test -- tests/test_fastapi_bootstrap.py::test_user_supplied_app_keeps_title_version_debug
```

Expected: PASS.

- [ ] **Step 5: Verify nothing else broke**

```bash
just test -- tests/test_fastapi_bootstrap.py tests/test_fastapi_offline_docs.py
```

Expected: all green. In particular `test_fastapi_bootstrapper_apps_and_kwargs_warning` still triggers when both `application` and `application_kwargs` are passed.

- [ ] **Step 6: Run full suite + lint**

```bash
just test
just lint-ci
```

Expected: 165 passed (164 + 1 new), 100% coverage, lint clean.

- [ ] **Step 7: Commit**

```bash
git add lite_bootstrap/bootstrappers/fastapi_bootstrapper.py tests/test_fastapi_bootstrap.py
git commit -m "$(cat <<'EOF'
fix: FastAPIConfig respects user-supplied app title/version/debug (UX-1)

Move the application.title/.debug/.version assignments inside the UnsetType
branch so they only apply when lite-bootstrap built the FastAPI() instance.
Pre-configured user apps now keep their construction-time values.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: UX-2 — Injectable `prometheus_collector_registry` on FastStream

**Files:**
- Modify: `lite_bootstrap/bootstrappers/faststream_bootstrapper.py:63-72` (add config field), `:143-167` (thread to instrument)
- Test: `tests/test_faststream_bootstrap.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_faststream_bootstrap.py`:

```python
import uuid


async def test_faststream_prometheus_uses_injected_registry(broker: RedisBroker) -> None:
    custom_registry = prometheus_client.CollectorRegistry()
    counter_name = f"injected_counter_{uuid.uuid4().hex}_total"
    counter = prometheus_client.Counter(counter_name, "Injected registry counter", registry=custom_registry)
    counter.inc()

    bootstrap_config = dataclasses.replace(
        build_faststream_config(broker=broker),
        prometheus_collector_registry=custom_registry,
    )
    bootstrapper = FastStreamBootstrapper(bootstrap_config=bootstrap_config)
    application = bootstrapper.bootstrap()
    try:
        with TestClient(app=application) as test_client, TestRedisBroker(broker):
            response = test_client.get(bootstrap_config.prometheus_metrics_path)
            assert response.status_code == status.HTTP_200_OK
            assert counter_name.encode() in response.content
    finally:
        bootstrapper.teardown()
```

Imports — verify `prometheus_client` is imported at module level (it isn't yet in this test file). Add:

```python
import prometheus_client
```

Near the existing `import` block at the top of `tests/test_faststream_bootstrap.py`. `dataclasses`, `uuid`, `status`, `TestClient`, `TestRedisBroker`, `RedisBroker` are already imported or will be from new imports.

- [ ] **Step 2: Run test to verify it fails**

```bash
just test -- tests/test_faststream_bootstrap.py::test_faststream_prometheus_uses_injected_registry
```

Expected: FAIL — `FastStreamConfig` doesn't have `prometheus_collector_registry` field; `dataclasses.replace(...)` raises `TypeError: __init__() got an unexpected keyword argument 'prometheus_collector_registry'`.

- [ ] **Step 3: Add the config field**

In `lite_bootstrap/bootstrappers/faststream_bootstrapper.py`, the current `FastStreamConfig` (lines 63-72) reads:

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class FastStreamConfig(
    HealthChecksConfig, LoggingConfig, OpenTelemetryConfig, PrometheusConfig, PyroscopeConfig, SentryConfig
):
    application: "AsgiFastStream" = dataclasses.field(default_factory=_make_asgi_faststream)
    opentelemetry_middleware_cls: type[FastStreamTelemetryMiddlewareProtocol] | None = None
    prometheus_middleware_cls: type[FastStreamPrometheusMiddlewareProtocol] | None = None
    faststream_log_level: int = logging.WARNING
    faststream_health_check_broker_timeout: float = 5.0
```

Add a `prometheus_collector_registry` field after `prometheus_middleware_cls`:

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class FastStreamConfig(
    HealthChecksConfig, LoggingConfig, OpenTelemetryConfig, PrometheusConfig, PyroscopeConfig, SentryConfig
):
    application: "AsgiFastStream" = dataclasses.field(default_factory=_make_asgi_faststream)
    opentelemetry_middleware_cls: type[FastStreamTelemetryMiddlewareProtocol] | None = None
    prometheus_middleware_cls: type[FastStreamPrometheusMiddlewareProtocol] | None = None
    prometheus_collector_registry: "prometheus_client.CollectorRegistry | None" = None
    faststream_log_level: int = logging.WARNING
    faststream_health_check_broker_timeout: float = 5.0
```

The string-annotation form `"prometheus_client.CollectorRegistry | None"` works because `prometheus_client` is imported conditionally at module scope (`if import_checker.is_prometheus_client_installed: import prometheus_client`). Dataclass field type annotations are not resolved at runtime by default, so the conditional import is fine.

- [ ] **Step 4: Thread the field into `FastStreamPrometheusInstrument`**

Currently (lines 143-167):

```python
@dataclasses.dataclass(kw_only=True)
class FastStreamPrometheusInstrument(PrometheusInstrument):
    bootstrap_config: FastStreamConfig
    collector_registry: "prometheus_client.CollectorRegistry" = dataclasses.field(
        default_factory=_make_collector_registry, init=False
    )
    not_ready_message = PrometheusInstrument.not_ready_message + " or prometheus_middleware_cls is missing"
    missing_dependency_message = "prometheus_client is not installed"
    ...
```

Replace the `collector_registry` field declaration with an `init=False` field set in `__post_init__`:

```python
@dataclasses.dataclass(kw_only=True)
class FastStreamPrometheusInstrument(PrometheusInstrument):
    bootstrap_config: FastStreamConfig
    collector_registry: "prometheus_client.CollectorRegistry" = dataclasses.field(init=False)
    not_ready_message = PrometheusInstrument.not_ready_message + " or prometheus_middleware_cls is missing"
    missing_dependency_message = "prometheus_client is not installed"

    def __post_init__(self) -> None:
        injected = self.bootstrap_config.prometheus_collector_registry
        self.collector_registry = injected if injected is not None else _make_collector_registry()

    @classmethod
    def is_configured(cls, bootstrap_config: "FastStreamConfig") -> bool:  # ty: ignore[invalid-method-override]
        return super().is_configured(bootstrap_config) and bool(bootstrap_config.prometheus_middleware_cls)
    ...
```

`__post_init__` runs after dataclass `__init__`; assignment via `self.collector_registry = ...` works because the instrument is non-frozen.

Keep the rest of the class unchanged (the `is_configured`, `check_dependencies`, `bootstrap` methods).

- [ ] **Step 5: Run the new test to verify it passes**

```bash
just test -- tests/test_faststream_bootstrap.py::test_faststream_prometheus_uses_injected_registry
```

Expected: PASS.

- [ ] **Step 6: Verify default-path still works**

```bash
just test -- tests/test_faststream_bootstrap.py
```

Expected: all green. Existing `test_faststream_bootstrap` (which doesn't supply `prometheus_collector_registry`) continues to use the per-instance default.

- [ ] **Step 7: Full suite + lint**

```bash
just test
just lint-ci
```

Expected: 166 passed (165 + 1 new), 100% coverage, lint clean.

- [ ] **Step 8: Commit**

```bash
git add lite_bootstrap/bootstrappers/faststream_bootstrapper.py tests/test_faststream_bootstrap.py
git commit -m "$(cat <<'EOF'
feat: support injectable Prometheus CollectorRegistry on FastStream (UX-2)

Add prometheus_collector_registry: CollectorRegistry | None config field on
FastStreamConfig. When non-None, FastStreamPrometheusInstrument uses the
injected registry; otherwise the existing per-instance default is preserved.
Lets users expose metrics that were registered on a shared registry.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: UX-3 — Add `opentelemetry_excluded_urls` to FastStreamConfig

**Files:**
- Modify: `lite_bootstrap/bootstrappers/faststream_bootstrapper.py:63-72`
- Test: `tests/test_faststream_bootstrap.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_faststream_bootstrap.py`:

```python
def test_faststream_opentelemetry_excluded_urls_in_built_set(broker: RedisBroker) -> None:
    from lite_bootstrap.bootstrappers.faststream_bootstrapper import (
        FastStreamOpenTelemetryInstrument,
    )

    bootstrap_config = dataclasses.replace(
        build_faststream_config(broker=broker),
        opentelemetry_excluded_urls=["/foo", "/bar"],
    )
    instrument = FastStreamOpenTelemetryInstrument(bootstrap_config=bootstrap_config)
    excluded = instrument._build_excluded_urls()  # noqa: SLF001
    assert "/foo" in excluded
    assert "/bar" in excluded
```

- [ ] **Step 2: Run test to verify it fails**

```bash
just test -- tests/test_faststream_bootstrap.py::test_faststream_opentelemetry_excluded_urls_in_built_set
```

Expected: FAIL — `dataclasses.replace(...)` raises because `FastStreamConfig` has no `opentelemetry_excluded_urls` field.

- [ ] **Step 3: Add the field**

In `lite_bootstrap/bootstrappers/faststream_bootstrapper.py`, the current `FastStreamConfig` (after Task 2's edit) reads approximately:

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class FastStreamConfig(
    HealthChecksConfig, LoggingConfig, OpenTelemetryConfig, PrometheusConfig, PyroscopeConfig, SentryConfig
):
    application: "AsgiFastStream" = dataclasses.field(default_factory=_make_asgi_faststream)
    opentelemetry_middleware_cls: type[FastStreamTelemetryMiddlewareProtocol] | None = None
    prometheus_middleware_cls: type[FastStreamPrometheusMiddlewareProtocol] | None = None
    prometheus_collector_registry: "prometheus_client.CollectorRegistry | None" = None
    faststream_log_level: int = logging.WARNING
    faststream_health_check_broker_timeout: float = 5.0
```

Add `opentelemetry_excluded_urls` after `opentelemetry_middleware_cls`:

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class FastStreamConfig(
    HealthChecksConfig, LoggingConfig, OpenTelemetryConfig, PrometheusConfig, PyroscopeConfig, SentryConfig
):
    application: "AsgiFastStream" = dataclasses.field(default_factory=_make_asgi_faststream)
    opentelemetry_middleware_cls: type[FastStreamTelemetryMiddlewareProtocol] | None = None
    opentelemetry_excluded_urls: list[str] = dataclasses.field(default_factory=list)
    prometheus_middleware_cls: type[FastStreamPrometheusMiddlewareProtocol] | None = None
    prometheus_collector_registry: "prometheus_client.CollectorRegistry | None" = None
    faststream_log_level: int = logging.WARNING
    faststream_health_check_broker_timeout: float = 5.0
```

The behavior of `_build_excluded_urls` (in `opentelemetry_instrument.py`) is unchanged — it already reads via `getattr(self.bootstrap_config, "opentelemetry_excluded_urls", [])`. The new field is just for discoverability (IDE help, tab completion).

- [ ] **Step 4: Run the new test to verify it passes**

```bash
just test -- tests/test_faststream_bootstrap.py::test_faststream_opentelemetry_excluded_urls_in_built_set
```

Expected: PASS.

- [ ] **Step 5: Full suite + lint**

```bash
just test
just lint-ci
```

Expected: 167 passed (166 + 1 new), 100% coverage, lint clean.

- [ ] **Step 6: Commit**

```bash
git add lite_bootstrap/bootstrappers/faststream_bootstrapper.py tests/test_faststream_bootstrap.py
git commit -m "$(cat <<'EOF'
feat: add opentelemetry_excluded_urls to FastStreamConfig (UX-3)

FastAPIConfig and LitestarConfig already expose opentelemetry_excluded_urls;
FastStream relied on getattr fallback with no discoverable field. Add the field
to FastStreamConfig matching the FastAPI/Litestar pattern. _build_excluded_urls
behavior is unchanged — the getattr access still works the same way.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: SEC-1 — Validate `root_path` in offline-docs HTML

**Files:**
- Modify: `lite_bootstrap/helpers/fastapi_helpers.py`
- Test: `tests/test_fastapi_offline_docs.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_fastapi_offline_docs.py`:

```python
def test_offline_docs_rejects_unsafe_root_path() -> None:
    malicious_root = "/foo</script><script>alert(1)</script>"
    app = FastAPI(title="Tests", root_path=malicious_root, docs_url="/custom_docs")
    enable_offline_docs(app, static_path="/static")

    with TestClient(app, root_path=malicious_root) as client, pytest.warns(UserWarning, match="root_path"):
        response = client.get("/custom_docs")
    assert response.status_code == HTTPStatus.OK
    assert "<script>alert(1)</script>" not in response.text
    assert "/static/swagger-ui.css" in response.text  # falls back to empty root_path
```

`FastAPI`, `TestClient`, `HTTPStatus`, `pytest`, `enable_offline_docs` are already imported in this file.

- [ ] **Step 2: Run test to verify it fails**

```bash
just test -- tests/test_fastapi_offline_docs.py::test_offline_docs_rejects_unsafe_root_path
```

Expected: FAIL — current handler reflects `root_path` verbatim into the swagger HTML, so the `<script>` tag from `root_path` lands in the response.

- [ ] **Step 3: Add the validation helper and use it in both handlers**

In `lite_bootstrap/helpers/fastapi_helpers.py`, add `warnings` and `is_valid_path` imports near the top:

```python
import pathlib
import typing
import warnings

from lite_bootstrap import import_checker
from lite_bootstrap.exceptions import ConfigurationError
from lite_bootstrap.helpers.path import is_valid_path
```

Then add a module-level helper just above `enable_offline_docs`:

```python
def _safe_root_path(scope_root_path: str) -> str:
    """Strip trailing slash and validate against the project's path allowlist.

    An empty `root_path` is the normal case (no proxy prefix) and is allowed without warning.
    Any other path that fails the `is_valid_path` regex is rejected (falls back to empty) so
    that proxy-header-derived root paths can't inject HTML into the offline-docs response.
    """
    candidate = scope_root_path.rstrip("/")
    if not candidate:
        return ""
    if not is_valid_path(candidate):
        warnings.warn(
            f"root_path {candidate!r} contains characters outside the valid-path allowlist; "
            "falling back to empty root_path to prevent HTML injection in offline docs.",
            stacklevel=3,
        )
        return ""
    return candidate
```

In `custom_swagger_ui_html` (currently around line 38-46), replace:

```python
async def custom_swagger_ui_html(request: Request) -> HTMLResponse:
    root_path = request.scope.get("root_path", "").rstrip("/")
    ...
```

with:

```python
async def custom_swagger_ui_html(request: Request) -> HTMLResponse:
    root_path = _safe_root_path(request.scope.get("root_path", ""))
    ...
```

Same change in `redoc_html` (currently around line 53-58): replace the `root_path = request.scope.get("root_path", "").rstrip("/")` line with `root_path = _safe_root_path(request.scope.get("root_path", ""))`.

- [ ] **Step 4: Run the new test to verify it passes**

```bash
just test -- tests/test_fastapi_offline_docs.py::test_offline_docs_rejects_unsafe_root_path
```

Expected: PASS — the malicious `root_path` is rejected, falls back to empty, no `<script>` injection in the response, and the warning fires.

- [ ] **Step 5: Verify existing tests still pass**

```bash
just test -- tests/test_fastapi_offline_docs.py
```

Expected: all green. `test_fastapi_offline_docs_root_path` (which uses the valid `/some-root-path`) still validates the safe case.

- [ ] **Step 6: Full suite + lint**

```bash
just test
just lint-ci
```

Expected: 168 passed (167 + 1 new), 100% coverage, lint clean.

- [ ] **Step 7: Commit**

```bash
git add lite_bootstrap/helpers/fastapi_helpers.py tests/test_fastapi_offline_docs.py
git commit -m "$(cat <<'EOF'
fix: validate root_path in offline-docs HTML to prevent injection (SEC-1)

The swagger/redoc handlers reflected request.scope["root_path"] verbatim into
HTML script/link tags. In default ASGI deployments root_path comes from server
config (uvicorn --root-path), but if a user enables ProxyHeadersMiddleware with
trusted X-Forwarded-Prefix, a malicious proxy could inject script content.
Validate via the project's existing is_valid_path allowlist and fall back to
empty (with a warning) on invalid input.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: SEC-2 — Warn on insecure non-local OTLP endpoint

**Files:**
- Modify: `lite_bootstrap/instruments/opentelemetry_instrument.py` (add `__post_init__` on `OpenTelemetryConfig`)
- Modify: `lite_bootstrap/bootstrappers/fastapi_bootstrapper.py` (cascade `super().__post_init__()` so FastAPIConfig users also get the warning)
- Test: `tests/instruments/test_opentelemetry_instrument.py`

**Context:** Only `FastAPIConfig` defines its own `__post_init__` among the framework configs. `FreeConfig`, `FastStreamConfig`, `LitestarConfig` inherit `OpenTelemetryConfig.__post_init__` (the one we're adding here) automatically via the dataclass MRO. `FastMcpConfig` doesn't inherit `OpenTelemetryConfig`, so the warning doesn't fire for it — that's correct since FastMCP doesn't bootstrap OTel today.

- [ ] **Step 1: Write the failing tests**

Add to `tests/instruments/test_opentelemetry_instrument.py`:

```python
import warnings


def test_opentelemetry_config_warns_on_insecure_non_local_endpoint() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        OpenTelemetryConfig(
            opentelemetry_endpoint="http://collector.example.com:4317",
            opentelemetry_insecure=True,
        )
    matching = [w for w in caught if "unencrypted" in str(w.message)]
    assert matching, [str(w.message) for w in caught]


def test_opentelemetry_config_no_warning_for_localhost_endpoint() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        # Should not raise — no warning emitted for localhost.
        OpenTelemetryConfig(
            opentelemetry_endpoint="http://localhost:4317",
            opentelemetry_insecure=True,
        )


def test_opentelemetry_config_no_warning_when_insecure_false() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        OpenTelemetryConfig(
            opentelemetry_endpoint="https://collector.example.com:4317",
            opentelemetry_insecure=False,
        )


def test_opentelemetry_config_no_warning_when_endpoint_unset() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        OpenTelemetryConfig(opentelemetry_log_traces=True)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
just test -- tests/instruments/test_opentelemetry_instrument.py::test_opentelemetry_config_warns_on_insecure_non_local_endpoint
```

Expected: FAIL — `OpenTelemetryConfig` has no `__post_init__`, so no warning is emitted.

The three "no warning" tests would pass even on the unmodified code (vacuously), but they pin the contract once the warning logic is added.

- [ ] **Step 3: Add `__post_init__` on `OpenTelemetryConfig`**

In `lite_bootstrap/instruments/opentelemetry_instrument.py`, add `urllib.parse` and `warnings` to the imports near the top (alongside the existing `import dataclasses`, `import logging`, `import os`, `import typing`):

```python
import dataclasses
import logging
import os
import typing
import urllib.parse
import warnings
```

Then modify `OpenTelemetryConfig` (currently lines 41-53) to add `__post_init__`. Current code:

```python
@dataclasses.dataclass(kw_only=True, frozen=True)
class OpenTelemetryConfig(OpenTelemetryServiceFieldsConfig):
    opentelemetry_container_name: str | None = dataclasses.field(
        default_factory=lambda: os.environ.get("HOSTNAME") or None
    )
    opentelemetry_endpoint: str | None = None
    opentelemetry_insecure: bool = True
    opentelemetry_instrumentors: list[typing.Union[InstrumentorWithParams, "BaseInstrumentor"]] = dataclasses.field(
        default_factory=list
    )
    opentelemetry_log_traces: bool = False
    opentelemetry_generate_health_check_spans: bool = True
```

Replace with:

```python
_LOCAL_HOSTS: typing.Final[frozenset[str]] = frozenset({"localhost", "127.0.0.1", "::1", ""})


@dataclasses.dataclass(kw_only=True, frozen=True)
class OpenTelemetryConfig(OpenTelemetryServiceFieldsConfig):
    opentelemetry_container_name: str | None = dataclasses.field(
        default_factory=lambda: os.environ.get("HOSTNAME") or None
    )
    opentelemetry_endpoint: str | None = None
    opentelemetry_insecure: bool = True
    opentelemetry_instrumentors: list[typing.Union[InstrumentorWithParams, "BaseInstrumentor"]] = dataclasses.field(
        default_factory=list
    )
    opentelemetry_log_traces: bool = False
    opentelemetry_generate_health_check_spans: bool = True

    def __post_init__(self) -> None:
        if not self.opentelemetry_endpoint or not self.opentelemetry_insecure:
            return
        if self.opentelemetry_endpoint.startswith("unix://"):
            return
        parsed = urllib.parse.urlparse(self.opentelemetry_endpoint)
        host = (parsed.hostname or parsed.path.split(":")[0]).lower()
        if host in _LOCAL_HOSTS:
            return
        warnings.warn(
            f"OTLP exporter sending traces unencrypted to non-local host {host!r}; "
            "set opentelemetry_insecure=False or use a localhost/unix endpoint.",
            stacklevel=3,
        )
```

The `_LOCAL_HOSTS` frozenset is module-private and reusable for any future host-locality checks. `urllib.parse.urlparse` handles both `host:port` and `scheme://host:port` (falls back to splitting `:` if `urlparse` can't extract a host).

- [ ] **Step 4: Cascade `super().__post_init__()` in FastAPIConfig**

After Task 1 lands, `FastAPIConfig.__post_init__` (in `lite_bootstrap/bootstrappers/fastapi_bootstrapper.py`) looks like:

```python
def __post_init__(self) -> None:
    if not import_checker.is_fastapi_installed:
        msg = "fastapi is not installed"
        raise ConfigurationError(msg)

    if isinstance(self.application, UnsetType):
        application = fastapi.FastAPI(docs_url=self.swagger_path, **self.application_kwargs)
        object.__setattr__(self, "application", application)
        application.title = self.service_name
        application.debug = self.service_debug
        application.version = self.service_version
    elif self.application_kwargs:
        warnings.warn("application_kwargs must be used without application", stacklevel=2)
```

Add `super().__post_init__()` as the first line of the body so the OpenTelemetryConfig warning fires for FastAPIConfig too:

```python
def __post_init__(self) -> None:
    super().__post_init__()
    if not import_checker.is_fastapi_installed:
        msg = "fastapi is not installed"
        raise ConfigurationError(msg)

    if isinstance(self.application, UnsetType):
        application = fastapi.FastAPI(docs_url=self.swagger_path, **self.application_kwargs)
        object.__setattr__(self, "application", application)
        application.title = self.service_name
        application.debug = self.service_debug
        application.version = self.service_version
    elif self.application_kwargs:
        warnings.warn("application_kwargs must be used without application", stacklevel=2)
```

The MRO chain for `FastAPIConfig` resolves `super().__post_init__()` to `OpenTelemetryConfig.__post_init__` (via CorsConfig → HealthChecksConfig → LoggingConfig → OpenTelemetryConfig).

- [ ] **Step 5: Add a FastAPIConfig-specific cascade test**

Add to `tests/test_fastapi_bootstrap.py`:

```python
def test_fastapi_config_inherits_otel_insecure_warning() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        FastAPIConfig(
            opentelemetry_endpoint="http://collector.example.com:4317",
            opentelemetry_insecure=True,
        )
    matching = [w for w in caught if "unencrypted" in str(w.message)]
    assert matching, [str(w.message) for w in caught]
```

Verify `warnings` is imported at the top of `tests/test_fastapi_bootstrap.py` — it was added in PR1 Task 10.

- [ ] **Step 6: Run all new tests**

```bash
just test -- tests/instruments/test_opentelemetry_instrument.py tests/test_fastapi_bootstrap.py
```

Expected: all green, including the new SEC-2 tests and the FastAPIConfig cascade test.

- [ ] **Step 7: Full suite + lint**

```bash
just test
just lint-ci
```

Expected: 173 passed (168 + 5 new), 100% coverage, lint clean.

- [ ] **Step 8: Commit**

```bash
git add lite_bootstrap/instruments/opentelemetry_instrument.py lite_bootstrap/bootstrappers/fastapi_bootstrapper.py tests/instruments/test_opentelemetry_instrument.py tests/test_fastapi_bootstrap.py
git commit -m "$(cat <<'EOF'
fix: warn on insecure non-local OTLP endpoint (SEC-2)

Add OpenTelemetryConfig.__post_init__ that emits a warning when
opentelemetry_endpoint points to a non-local host AND opentelemetry_insecure is
True (the unfortunate default). Localhost, 127.0.0.1, ::1, and unix:// endpoints
are silent. FastAPIConfig.__post_init__ now calls super().__post_init__() so
FastAPI users see the warning too; other framework configs (FreeConfig,
FastStreamConfig, LitestarConfig) don't have their own __post_init__ and
inherit the new behavior automatically.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: SEC-3 — Reject unsafe CORS configurations at construction

**Files:**
- Modify: `lite_bootstrap/instruments/cors_instrument.py` (add `__post_init__` on `CorsConfig`)
- Test: `tests/instruments/test_cors_instrument.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/instruments/test_cors_instrument.py`:

```python
import pytest

from lite_bootstrap.exceptions import ConfigurationError


@pytest.mark.parametrize(
    ("origins", "regex"),
    [
        (["*"], None),
        ([], ".*"),
        ([], r".+"),
        (["*", "http://safe.example.com"], None),
    ],
)
def test_cors_config_rejects_wildcard_with_credentials(
    origins: list[str], regex: str | None
) -> None:
    with pytest.raises(ConfigurationError, match="Unsafe CORS"):
        CorsConfig(
            cors_allowed_origins=origins,
            cors_allowed_origin_regex=regex,
            cors_allowed_credentials=True,
        )


def test_cors_config_accepts_credentials_with_explicit_origins() -> None:
    config = CorsConfig(
        cors_allowed_origins=["http://example.com"],
        cors_allowed_credentials=True,
    )
    assert config.cors_allowed_credentials is True


def test_cors_config_accepts_wildcard_without_credentials() -> None:
    config = CorsConfig(
        cors_allowed_origins=["*"],
        cors_allowed_credentials=False,
    )
    assert config.cors_allowed_origins == ["*"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
just test -- tests/instruments/test_cors_instrument.py::test_cors_config_rejects_wildcard_with_credentials
```

Expected: FAIL — `CorsConfig` accepts the unsafe combination today.

- [ ] **Step 3: Add `__post_init__` to `CorsConfig`**

In `lite_bootstrap/instruments/cors_instrument.py`, the current `CorsConfig` (lines 6-15) reads:

```python
@dataclasses.dataclass(kw_only=True, frozen=True)
class CorsConfig(BaseConfig):
    cors_allowed_origins: list[str] = dataclasses.field(default_factory=list)
    cors_allowed_methods: list[str] = dataclasses.field(default_factory=list)
    cors_allowed_headers: list[str] = dataclasses.field(default_factory=list)
    cors_exposed_headers: list[str] = dataclasses.field(default_factory=list)
    cors_allowed_credentials: bool = False
    cors_allowed_origin_regex: str | None = None
    cors_max_age: int = 600
```

Add an import for `ConfigurationError` at the top:

```python
import dataclasses

from lite_bootstrap.exceptions import ConfigurationError
from lite_bootstrap.instruments.base import BaseConfig, BaseInstrument
```

And add `__post_init__`:

```python
_PERMISSIVE_ORIGIN_REGEX: typing.Final[frozenset[str]] = frozenset({".*", r".+"})


@dataclasses.dataclass(kw_only=True, frozen=True)
class CorsConfig(BaseConfig):
    cors_allowed_origins: list[str] = dataclasses.field(default_factory=list)
    cors_allowed_methods: list[str] = dataclasses.field(default_factory=list)
    cors_allowed_headers: list[str] = dataclasses.field(default_factory=list)
    cors_exposed_headers: list[str] = dataclasses.field(default_factory=list)
    cors_allowed_credentials: bool = False
    cors_allowed_origin_regex: str | None = None
    cors_max_age: int = 600

    def __post_init__(self) -> None:
        if not self.cors_allowed_credentials:
            return
        wildcard_in_origins = "*" in self.cors_allowed_origins
        permissive_regex = self.cors_allowed_origin_regex in _PERMISSIVE_ORIGIN_REGEX
        if wildcard_in_origins or permissive_regex:
            msg = (
                "Unsafe CORS configuration: cors_allowed_credentials=True combined with a "
                "wildcard origin is rejected by browsers and is a security misconfiguration. "
                "Use an explicit list of allowed origins (or a narrow regex)."
            )
            raise ConfigurationError(msg)
```

Add `import typing` if not already imported.

- [ ] **Step 4: Run the new tests to verify they pass**

```bash
just test -- tests/instruments/test_cors_instrument.py
```

Expected: all green (new tests + existing tests like `test_cors_instrument_configured_with_origins`).

- [ ] **Step 5: Run downstream tests that build FastAPI/Litestar configs with CORS**

```bash
just test -- tests/test_fastapi_bootstrap.py tests/test_litestar_bootstrap.py
```

Expected: green. None of the existing fixtures use the wildcard + credentials combo.

- [ ] **Step 6: Full suite + lint**

```bash
just test
just lint-ci
```

Expected: 176 passed (173 + 3 new), 100% coverage, lint clean.

- [ ] **Step 7: Commit**

```bash
git add lite_bootstrap/instruments/cors_instrument.py tests/instruments/test_cors_instrument.py
git commit -m "$(cat <<'EOF'
fix: reject unsafe CORS wildcard + credentials combo at construction (SEC-3)

cors_allowed_credentials=True with cors_allowed_origins=["*"] (or a permissive
regex like ".*"/".+") is the canonical CORS misconfiguration. FastAPI's
CORSMiddleware refuses to set the credentials header in that combo but
Litestar's behavior differs and may silently accept it. Add a CorsConfig
__post_init__ that raises ConfigurationError on the unsafe combination
at config-construction time, before any framework sees the values.

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

Expected: 176 passed (164 baseline + 12 new across the 6 tasks), 100% coverage.

- [ ] **Step 2: Lint + type check**

```bash
just lint-ci
```

Expected: green.

- [ ] **Step 3: Confirm commit log shape**

```bash
git log --oneline origin/main..HEAD
```

Expected: 6 task commits, each titled with a `fix:` or `feat:` prefix and tagged with the audit ID(s) it closes:

- Task 1 (UX-1) — `fix:`
- Task 2 (UX-2) — `feat:`
- Task 3 (UX-3) — `feat:`
- Task 4 (SEC-1) — `fix:`
- Task 5 (SEC-2) — `fix:`
- Task 6 (SEC-3) — `fix:`

---

## Self-Review

1. **Spec coverage:** UX-1 (Task 1) · UX-2 (Task 2) · UX-3 (Task 3) · SEC-1 (Task 4) · SEC-2 (Task 5) · SEC-3 (Task 6). TEST-NEW-1 folds into Task 1; TEST-NEW-6 folds into Task 6. All 6 PR2 findings + 2 paired test items mapped.
2. **Placeholder scan:** every step has full code blocks, exact commands, and expected outcomes.
3. **Type consistency:** `FastStreamConfig.prometheus_collector_registry: prometheus_client.CollectorRegistry | None` (Task 2), `FastStreamConfig.opentelemetry_excluded_urls: list[str]` (Task 3), `OpenTelemetryConfig` adds no fields (Task 5), `CorsConfig` adds no fields (Task 6). All consistent between definition and usage.
4. **Commit isolation:** each task ends with a single commit scoped to its finding ID.
5. **Cross-task interaction:** Task 5 modifies the `FastAPIConfig.__post_init__` that Task 1 already restructured. The plan orders Task 5 after Task 1 so the `super().__post_init__()` insertion lands cleanly. No other cross-task structural conflicts.


---

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
