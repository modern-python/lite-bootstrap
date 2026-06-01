# FastMCP Bootstrapper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a `FastMcpBootstrapper` and `FastMcpConfig` that wire the lite-bootstrap instrument stack (Sentry, Pyroscope, structlog logging with an MCP-aware access middleware, JSON health check, Prometheus metrics) onto a FastMCP server, with teardown plumbed through the FastMCP lifespan.

**Architecture:** Single-file bootstrapper module mirroring `faststream_bootstrapper.py` (Approach A from brainstorming). Frozen dataclass config composed via multiple inheritance over the shared instrument configs (no OTel/CORS/Swagger). Framework-specific instrument subclasses. Teardown wired by replacing `FastMCP.lifespan` with `fastmcp.utilities.lifespan.combine_lifespans(existing, teardown_lifespan)`. Two new pyproject extras (`fastmcp`, `fastmcp-metrics`); no composite/rollup extras per the project rule.

**Tech Stack:** Python 3.10+ dataclasses, `fastmcp`, `structlog`, `prometheus_client`, `starlette.responses`, `pytest-asyncio` (auto mode), `httpx2` test client, `unittest.mock.MagicMock` / `pytest.MonkeyPatch`.

**Parent spec:** `docs/superpowers/specs/2026-06-01-fastmcp-bootstrapper-design.md`
**Reference PR:** [microbootstrap PR #141](https://github.com/community-of-python/microbootstrap/pull/141).

---

## File Structure

Two new files, six modified files.

- **Create:** `lite_bootstrap/bootstrappers/fastmcp_bootstrapper.py` — `_make_fastmcp`, `_build_teardown_lifespan`, `FastMcpConfig`, `FastMcpLoggingMiddleware`, `FastMcpHealthChecksInstrument`, `FastMcpLoggingInstrument`, `FastMcpPrometheusInstrument`, `FastMcpBootstrapper`.
- **Create:** `tests/test_fastmcp_bootstrap.py` — full test suite (13 tests; see spec §Tests).
- **Create:** `docs/integrations/fastmcp.md` — integration usage page.
- **Modify:** `lite_bootstrap/import_checker.py` — add `is_fastmcp_installed`.
- **Modify:** `lite_bootstrap/__init__.py` — re-export `FastMcpBootstrapper`, `FastMcpConfig`.
- **Modify:** `pyproject.toml` — add extras, append `"fastmcp"` keyword.
- **Modify:** `README.md` — append FastMCP to framework list.
- **Modify:** `docs/index.md` — append FastMCP to framework list.
- **Modify:** `docs/introduction/installation.md` — new column in extras table + composition note.
- **Modify:** `CLAUDE.md` — `FastMcpBootstrapper` in Core-pattern tree.

---

## Locked decisions (from spec)

- **Instrument set:** Sentry, Pyroscope, structlog logging + MCP middleware, health, prometheus. No OTel/CORS/Swagger.
- **Middleware default:** mounted on; `logging_turn_off_middleware: bool = False` flag to opt out.
- **Prometheus route:** `application.custom_route` at `prometheus_metrics_path`, always-on (no per-bootstrapper opt-out flag).
- **Teardown:** wired automatically via `FastMCP.add_provider(_TeardownProvider(self.teardown))` in `FastMcpBootstrapper.__init__`. `_TeardownProvider` is an empty `Provider` subclass whose `async def lifespan(self)` calls the teardown callable on exit. This is the only **public, post-construction** lifecycle hook FastMCP exposes — `FastMCP.lifespan` is a read-only bound method and `_lifespan` is private. Two earlier approaches considered and rejected: wrapping `FastMCP.lifespan` via `combine_lifespans` (impossible — `lifespan` is read-only) and manual teardown (briefly adopted then reverted when `add_provider` was identified). See spec §"Teardown via Provider.lifespan".
- **Extras:** `fastmcp`, `fastmcp-metrics`, and `fastmcp-all` rollup (matches `fastapi-all` / `litestar-all` / `faststream-all`). No `fastmcp-sentry` / `fastmcp-logging` because per-pair composites add no new direct dependencies.
- **Default config app:** `default_factory=_make_fastmcp` where `_make_fastmcp()` returns `FastMCP()`. No `UnsetType` sentinel — `FastMCP()` needs no derived config.
- **Middleware default registry:** `prometheus_client.REGISTRY`. No fastmcp-specific registry config field.

---

## Task 1: Create branch

**Files:** (no files; git only)

- [ ] **Step 1: Branch off `main`**

```bash
git checkout main
git pull --ff-only origin main
git checkout -b feat/fastmcp-bootstrapper
```

Expected: `Switched to a new branch 'feat/fastmcp-bootstrapper'`.

---

## Task 2: Add `is_fastmcp_installed` to import_checker

**Files:**
- Modify: `lite_bootstrap/import_checker.py`

- [ ] **Step 1: Add the spec check**

Current file ends at line 19 with `is_pyroscope_installed`. Append a new line after it:

```python
is_fastmcp_installed = find_spec("fastmcp") is not None
```

After the change the relevant tail of `lite_bootstrap/import_checker.py` reads:

```python
is_pyroscope_installed = find_spec("pyroscope") is not None
is_fastmcp_installed = find_spec("fastmcp") is not None
```

- [ ] **Step 2: Quick smoke-import**

Run: `uv run --no-sync python -c "from lite_bootstrap.import_checker import is_fastmcp_installed; print(is_fastmcp_installed)"`

Expected: prints `False` (fastmcp is not yet installed — Task 3 installs it). No `ImportError`.

- [ ] **Step 3: Commit**

```bash
git add lite_bootstrap/import_checker.py
git commit -m "feat: detect fastmcp via import_checker"
```

---

## Task 3: Add fastmcp extras and install

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Append the `fastmcp` extra**

In `pyproject.toml` under `[project.optional-dependencies]`, immediately after the `faststream-all` block (line 114–117 currently), add:

```toml
fastmcp = [
    "fastmcp",
]
fastmcp-metrics = [
    "lite-bootstrap[fastmcp]",
    "prometheus-client>=0.20",
]
```

Do NOT add `fastmcp-sentry`, `fastmcp-logging`, or `fastmcp-all` — composite extras that don't pull in a new dependency are excluded by the project rule.

- [ ] **Step 2: Append the `"fastmcp"` keyword**

In `pyproject.toml` line 10–21, the `keywords` list ends with `"structlog",`. Insert `"fastmcp",` before the closing bracket so it joins the existing list:

```toml
keywords = [
    "python",
    "microservice",
    "bootstrap",
    "opentelemetry",
    "sentry",
    "error-tracing",
    "fastapi",
    "litestar",
    "faststream",
    "structlog",
    "fastmcp",
]
```

- [ ] **Step 3: Sync dependencies**

Run: `just install`

Expected: `uv lock --upgrade` updates `uv.lock` to include `fastmcp` (and its transitive deps: `starlette`, `mcp`, etc.). `uv sync --all-extras --frozen --group lint` installs them. No errors.

- [ ] **Step 4: Verify fastmcp is importable**

Run: `uv run --no-sync python -c "from fastmcp import FastMCP; print(FastMCP)"`

Expected: prints `<class 'fastmcp.server.server.FastMCP'>` (or similar — confirms install).

Run: `uv run --no-sync python -c "from lite_bootstrap.import_checker import is_fastmcp_installed; print(is_fastmcp_installed)"`

Expected: prints `True`.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "feat: add fastmcp and fastmcp-metrics extras"
```

---

## Task 4: Scaffold `fastmcp_bootstrapper.py` with config + module helpers

**Files:**
- Create: `lite_bootstrap/bootstrappers/fastmcp_bootstrapper.py`
- Create: `tests/test_fastmcp_bootstrap.py`

This task lands the module skeleton: imports, optional-import guards, `_make_fastmcp`, `_build_teardown_lifespan`, `FastMcpConfig`, and a minimal `FastMcpBootstrapper` with `instruments_types = []`. Tests at the end of this task: default-factory yields a `FastMCP`, `bootstrap()` returns the same `FastMCP`, "not ready when fastmcp missing" raises.

### Step 1: Write the failing tests

- [ ] Create `tests/test_fastmcp_bootstrap.py` with the following content:

```python
import contextlib
import time
import typing

import prometheus_client
import pytest
import structlog
from fastmcp import FastMCP
from fastmcp.server.middleware import Middleware, MiddlewareContext
from starlette import status
from starlette.testclient import TestClient

from lite_bootstrap import FastMcpBootstrapper, FastMcpConfig
from lite_bootstrap.bootstrappers.fastmcp_bootstrapper import FastMcpLoggingMiddleware
from tests.conftest import emulate_package_missing


logger = structlog.getLogger(__name__)


def test_fastmcp_config_default_application() -> None:
    config = FastMcpConfig()
    assert isinstance(config.application, FastMCP)


def test_fastmcp_bootstrap_returns_same_application() -> None:
    config = FastMcpConfig(service_name="test-mcp", service_version="1.2.3")
    bootstrapper = FastMcpBootstrapper(bootstrap_config=config)
    application = bootstrapper.bootstrap()
    assert application is config.application
    bootstrapper.teardown()


def test_fastmcp_bootstrapper_not_ready() -> None:
    with emulate_package_missing("fastmcp"), pytest.raises(RuntimeError, match="fastmcp is not installed"):
        FastMcpBootstrapper(bootstrap_config=FastMcpConfig())
```

### Step 2: Run tests to verify failure mode

Run: `just test -- tests/test_fastmcp_bootstrap.py -v`

Expected: All three tests fail with `ImportError: cannot import name 'FastMcpBootstrapper' from 'lite_bootstrap'` (collection error). This is the failure we want — it proves the symbols don't yet exist.

### Step 3: Create the bootstrapper module skeleton

- [ ] Create `lite_bootstrap/bootstrappers/fastmcp_bootstrapper.py` with the following content:

```python
import dataclasses
import time
import typing

from lite_bootstrap import import_checker
from lite_bootstrap.bootstrappers.base import BaseBootstrapper
from lite_bootstrap.instruments.healthchecks_instrument import HealthChecksConfig, HealthChecksInstrument
from lite_bootstrap.instruments.logging_instrument import LoggingConfig, LoggingInstrument
from lite_bootstrap.instruments.prometheus_instrument import PrometheusConfig, PrometheusInstrument
from lite_bootstrap.instruments.pyroscope_instrument import PyroscopeConfig, PyroscopeInstrument
from lite_bootstrap.instruments.sentry_instrument import SentryConfig, SentryInstrument


if import_checker.is_fastmcp_installed:
    from fastmcp import FastMCP
    from fastmcp.server.middleware import Middleware, MiddlewareContext
    from starlette.requests import Request
    from starlette.responses import JSONResponse, Response

if import_checker.is_structlog_installed:
    import structlog

    fastmcp_access_logger: typing.Final = structlog.get_logger("mcp.access")

if import_checker.is_prometheus_client_installed:
    import prometheus_client


def _make_fastmcp() -> "FastMCP[typing.Any]":
    return FastMCP()


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class FastMcpConfig(
    HealthChecksConfig, LoggingConfig, PrometheusConfig, PyroscopeConfig, SentryConfig
):
    application: "FastMCP[typing.Any]" = dataclasses.field(default_factory=_make_fastmcp)
    logging_turn_off_middleware: bool = False


class FastMcpBootstrapper(BaseBootstrapper["FastMCP[typing.Any]"]):
    __slots__ = "bootstrap_config", "instruments"

    instruments_types: typing.ClassVar = []
    bootstrap_config: FastMcpConfig
    not_ready_message = "fastmcp is not installed"

    def is_ready(self) -> bool:
        return import_checker.is_fastmcp_installed

    def _prepare_application(self) -> "FastMCP[typing.Any]":
        return self.bootstrap_config.application
```

Note: no `__init__` override and no lifespan wiring. `FastMCP.lifespan` was empirically determined to be a read-only bound method, with the real hook stored in private `_lifespan` at construction time. Per the spec's documented fallback, teardown is manual — users call `bootstrapper.teardown()` themselves.

### Step 4: Re-export from package __init__

- [ ] Update `lite_bootstrap/__init__.py`. Insert imports alphabetically (after the existing `faststream_bootstrapper` import) and add the names to `__all__`:

```python
from lite_bootstrap.bootstrappers.fastapi_bootstrapper import FastAPIBootstrapper, FastAPIConfig
from lite_bootstrap.bootstrappers.fastmcp_bootstrapper import FastMcpBootstrapper, FastMcpConfig
from lite_bootstrap.bootstrappers.faststream_bootstrapper import FastStreamBootstrapper, FastStreamConfig
```

Add `"FastMcpBootstrapper"` and `"FastMcpConfig"` to `__all__`, keeping alphabetical order:

```python
__all__ = [
    "BootstrapperNotReadyError",
    "ConfigurationError",
    "FastAPIBootstrapper",
    "FastAPIConfig",
    "FastMcpBootstrapper",
    "FastMcpConfig",
    "FastStreamBootstrapper",
    "FastStreamConfig",
    ...
]
```

### Step 5: Run tests to verify pass

Run: `just test -- tests/test_fastmcp_bootstrap.py -v`

Expected: all three tests pass.

If `test_fastmcp_bootstrapper_not_ready` errors with `Failed: DID NOT RAISE`, recheck that `FastMcpBootstrapper.is_ready()` reads `import_checker.is_fastmcp_installed` (not a cached module-level value).

### Step 6: Commit

```bash
git add lite_bootstrap/bootstrappers/fastmcp_bootstrapper.py lite_bootstrap/__init__.py tests/test_fastmcp_bootstrap.py
git commit -m "feat: scaffold FastMcpBootstrapper and FastMcpConfig"
```

---

## Task 5: Verify teardown resets is_bootstrapped (direct + via ASGI lifespan)

Initially this task covered only the direct-call assertion because the design first concluded teardown had to be manual (the `FastMCP.lifespan` read-only finding). Once `add_provider` + `Provider.lifespan` was identified as the right post-construction hook, the ASGI-lifespan replay test was restored alongside the direct test. Both land in the same task. (The earlier `test_fastmcp_bootstrap_returns_same_application` test calls `teardown()` at the end too; this task makes the assertion explicit and adds the lifespan-driven counterpart.)

**Files:**
- Modify: `tests/test_fastmcp_bootstrap.py`

### Step 1: Write the failing test

- [ ] Append to `tests/test_fastmcp_bootstrap.py`:

```python
def test_fastmcp_teardown_resets_is_bootstrapped() -> None:
    bootstrapper = FastMcpBootstrapper(bootstrap_config=FastMcpConfig())
    bootstrapper.bootstrap()
    assert bootstrapper.is_bootstrapped is True
    bootstrapper.teardown()
    assert bootstrapper.is_bootstrapped is False
```

### Step 2: Run tests to verify pass

Run: `just test -- tests/test_fastmcp_bootstrap.py::test_fastmcp_teardown_resets_is_bootstrapped -v`

Expected: passes immediately (the assertions only exercise the base class's idempotent teardown plumbing, which already works).

### Step 3: Commit

```bash
git add tests/test_fastmcp_bootstrap.py
git commit -m "test: verify FastMcpBootstrapper teardown resets state"
```

---

## Task 6: Add `FastMcpLoggingMiddleware`

The MCP protocol-level middleware. Logs `method`, `source`, `type`, and duration to `mcp.access` structlog logger. 1:1 port of microbootstrap PR141's middleware.

**Files:**
- Modify: `lite_bootstrap/bootstrappers/fastmcp_bootstrapper.py`
- Modify: `tests/test_fastmcp_bootstrap.py`

### Step 1: Write the failing tests

- [ ] Append to `tests/test_fastmcp_bootstrap.py`:

```python
async def test_fastmcp_logging_middleware_logs_success(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import MagicMock

    fake_logger = MagicMock()
    monkeypatch.setattr(
        "lite_bootstrap.bootstrappers.fastmcp_bootstrapper.fastmcp_access_logger",
        fake_logger,
    )
    middleware = FastMcpLoggingMiddleware()
    context = MiddlewareContext(
        message={"payload": "test"},
        method="tools/list",
        source="client",
        type="request",
    )

    async def call_next(received: MiddlewareContext[typing.Any]) -> dict[str, str]:
        assert received is context
        return {"status": "ok"}

    result = await middleware.on_message(context, call_next)

    assert result == {"status": "ok"}
    fake_logger.info.assert_called_once()
    call_kwargs = fake_logger.info.call_args
    assert call_kwargs.args[0] == "tools/list"
    assert call_kwargs.kwargs["mcp"] == {
        "method": "tools/list",
        "source": "client",
        "type": "request",
    }
    assert isinstance(call_kwargs.kwargs["duration"], int)


async def test_fastmcp_logging_middleware_logs_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import MagicMock

    fake_logger = MagicMock()
    monkeypatch.setattr(
        "lite_bootstrap.bootstrappers.fastmcp_bootstrapper.fastmcp_access_logger",
        fake_logger,
    )
    middleware = FastMcpLoggingMiddleware()
    context = MiddlewareContext(
        message={"payload": "test"},
        method="tools/call",
        source="client",
        type="request",
    )

    class CustomError(RuntimeError):
        pass

    async def call_next(_: MiddlewareContext[typing.Any]) -> None:
        raise CustomError("boom")

    with pytest.raises(CustomError, match="boom"):
        await middleware.on_message(context, call_next)

    fake_logger.exception.assert_called_once()
    fake_logger.info.assert_not_called()
```

### Step 2: Run tests to verify failure mode

Run: `just test -- tests/test_fastmcp_bootstrap.py::test_fastmcp_logging_middleware_logs_success tests/test_fastmcp_bootstrap.py::test_fastmcp_logging_middleware_logs_exception -v`

Expected: failure with `ImportError: cannot import name 'FastMcpLoggingMiddleware' from 'lite_bootstrap.bootstrappers.fastmcp_bootstrapper'` (collection error).

### Step 3: Add the middleware to the bootstrapper module

- [ ] In `lite_bootstrap/bootstrappers/fastmcp_bootstrapper.py`, after the `_build_teardown_lifespan` function and before the `FastMcpConfig` dataclass, add:

```python
class FastMcpLoggingMiddleware(Middleware):
    async def on_message(
        self,
        context: "MiddlewareContext[typing.Any]",
        call_next: "typing.Callable[[MiddlewareContext[typing.Any]], typing.Awaitable[typing.Any]]",
    ) -> typing.Any:  # noqa: ANN401
        start_time = time.perf_counter_ns()
        mcp_fields = {
            "method": context.method,
            "source": context.source,
            "type": context.type,
        }
        try:
            result = await call_next(context)
        except Exception:
            fastmcp_access_logger.exception(
                context.method or "unknown",
                mcp=mcp_fields,
                duration=time.perf_counter_ns() - start_time,
            )
            raise

        fastmcp_access_logger.info(
            context.method or "unknown",
            mcp=mcp_fields,
            duration=time.perf_counter_ns() - start_time,
        )
        return result
```

### Step 4: Run tests to verify pass

Run: `just test -- tests/test_fastmcp_bootstrap.py::test_fastmcp_logging_middleware_logs_success tests/test_fastmcp_bootstrap.py::test_fastmcp_logging_middleware_logs_exception -v`

Expected: both pass.

### Step 5: Commit

```bash
git add lite_bootstrap/bootstrappers/fastmcp_bootstrapper.py tests/test_fastmcp_bootstrap.py
git commit -m "feat: add FastMcpLoggingMiddleware"
```

---

## Task 7: Add `FastMcpHealthChecksInstrument` and register it

**Files:**
- Modify: `lite_bootstrap/bootstrappers/fastmcp_bootstrapper.py`
- Modify: `tests/test_fastmcp_bootstrap.py`

### Step 1: Write the failing tests

- [ ] Append to `tests/test_fastmcp_bootstrap.py`:

```python
def _make_test_config(**overrides: typing.Any) -> FastMcpConfig:
    base: dict[str, typing.Any] = {
        "service_name": "test-mcp",
        "service_version": "1.2.3",
        "logging_buffer_capacity": 0,
    }
    base.update(overrides)
    return FastMcpConfig(**base)


def test_fastmcp_health_check_route_serves_200_with_data() -> None:
    config = _make_test_config()
    bootstrapper = FastMcpBootstrapper(bootstrap_config=config)
    application = bootstrapper.bootstrap()
    try:
        with TestClient(application.http_app()) as test_client:
            response = test_client.get(config.health_checks_path)
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "health_status": True,
            "service_name": "test-mcp",
            "service_version": "1.2.3",
        }
    finally:
        bootstrapper.teardown()


def test_fastmcp_health_check_path_is_configurable() -> None:
    config = _make_test_config(health_checks_path="/healthz")
    bootstrapper = FastMcpBootstrapper(bootstrap_config=config)
    application = bootstrapper.bootstrap()
    try:
        with TestClient(application.http_app()) as test_client:
            response = test_client.get("/healthz")
            default_response = test_client.get("/health/")
        assert response.status_code == status.HTTP_200_OK
        assert default_response.status_code == status.HTTP_404_NOT_FOUND
    finally:
        bootstrapper.teardown()


def test_fastmcp_health_check_disabled_when_flag_false() -> None:
    config = _make_test_config(health_checks_enabled=False)
    bootstrapper = FastMcpBootstrapper(bootstrap_config=config)
    application = bootstrapper.bootstrap()
    try:
        with TestClient(application.http_app()) as test_client:
            response = test_client.get(config.health_checks_path)
        assert response.status_code == status.HTTP_404_NOT_FOUND
    finally:
        bootstrapper.teardown()
```

### Step 2: Run tests to verify failure mode

Run: `just test -- tests/test_fastmcp_bootstrap.py::test_fastmcp_health_check_route_serves_200_with_data tests/test_fastmcp_bootstrap.py::test_fastmcp_health_check_path_is_configurable tests/test_fastmcp_bootstrap.py::test_fastmcp_health_check_disabled_when_flag_false -v`

Expected: all three fail with `404` (no health instrument registered yet).

### Step 3: Add the instrument

- [ ] In `lite_bootstrap/bootstrappers/fastmcp_bootstrapper.py`, after `FastMcpLoggingMiddleware`, add:

```python
@dataclasses.dataclass(kw_only=True)
class FastMcpHealthChecksInstrument(HealthChecksInstrument):
    bootstrap_config: FastMcpConfig

    def bootstrap(self) -> None:
        @self.bootstrap_config.application.custom_route(
            self.bootstrap_config.health_checks_path,
            methods=["GET"],
            name="health_check",
            include_in_schema=self.bootstrap_config.health_checks_include_in_schema,
        )
        async def health_check_handler(_: "Request") -> "JSONResponse":
            return JSONResponse(dict(self.render_health_check_data()))
```

- [ ] Update `FastMcpBootstrapper.instruments_types` to include the new instrument:

```python
    instruments_types: typing.ClassVar = [
        FastMcpHealthChecksInstrument,
    ]
```

### Step 4: Run tests to verify pass

Run: `just test -- tests/test_fastmcp_bootstrap.py -v -k "health_check"`

Expected: all three health-check tests pass. The earlier tests (`test_fastmcp_bootstrap_returns_same_application` etc.) still pass.

### Step 5: Commit

```bash
git add lite_bootstrap/bootstrappers/fastmcp_bootstrapper.py tests/test_fastmcp_bootstrap.py
git commit -m "feat: add FastMcpHealthChecksInstrument"
```

---

## Task 8: Add `FastMcpPrometheusInstrument` and register it

**Files:**
- Modify: `lite_bootstrap/bootstrappers/fastmcp_bootstrapper.py`
- Modify: `tests/test_fastmcp_bootstrap.py`

### Step 1: Write the failing tests

- [ ] Append to `tests/test_fastmcp_bootstrap.py`:

```python
def test_fastmcp_prometheus_route_exposes_registered_metric() -> None:
    counter_name = "fastmcp_plan_test_requests_total"
    # Counter constructors register against the default registry by default; if a
    # prior test registered the same name, reuse it rather than re-registering.
    try:
        counter = prometheus_client.Counter(counter_name, "FastMCP plan test counter.")
    except ValueError:
        # Already registered from a prior test in the same process.
        collector = prometheus_client.REGISTRY._names_to_collectors[counter_name]  # noqa: SLF001
        counter = typing.cast(prometheus_client.Counter, collector)
    counter.inc()

    config = _make_test_config()
    bootstrapper = FastMcpBootstrapper(bootstrap_config=config)
    application = bootstrapper.bootstrap()
    try:
        with TestClient(application.http_app()) as test_client:
            response = test_client.get(config.prometheus_metrics_path)
        assert response.status_code == status.HTTP_200_OK
        assert response.headers["content-type"].startswith(prometheus_client.CONTENT_TYPE_LATEST.split(";")[0])
        assert counter_name.encode() in response.content
    finally:
        bootstrapper.teardown()


def test_fastmcp_prometheus_path_is_configurable() -> None:
    config = _make_test_config(prometheus_metrics_path="/m")
    bootstrapper = FastMcpBootstrapper(bootstrap_config=config)
    application = bootstrapper.bootstrap()
    try:
        with TestClient(application.http_app()) as test_client:
            response = test_client.get("/m")
            default_response = test_client.get("/metrics")
        assert response.status_code == status.HTTP_200_OK
        assert default_response.status_code == status.HTTP_404_NOT_FOUND
    finally:
        bootstrapper.teardown()
```

### Step 2: Run tests to verify failure mode

Run: `just test -- tests/test_fastmcp_bootstrap.py -v -k "prometheus"`

Expected: both fail with `404` (no prometheus instrument registered).

### Step 3: Add the instrument

- [ ] In `lite_bootstrap/bootstrappers/fastmcp_bootstrapper.py`, after `FastMcpHealthChecksInstrument`, add:

```python
@dataclasses.dataclass(kw_only=True)
class FastMcpPrometheusInstrument(PrometheusInstrument):
    bootstrap_config: FastMcpConfig
    missing_dependency_message = "prometheus_client is not installed"

    @staticmethod
    def check_dependencies() -> bool:
        return import_checker.is_prometheus_client_installed

    def bootstrap(self) -> None:
        @self.bootstrap_config.application.custom_route(
            self.bootstrap_config.prometheus_metrics_path,
            methods=["GET"],
            name="metrics",
            include_in_schema=self.bootstrap_config.prometheus_metrics_include_in_schema,
        )
        async def metrics_handler(_: "Request") -> "Response":
            return Response(
                prometheus_client.generate_latest(prometheus_client.REGISTRY),
                headers={"content-type": prometheus_client.CONTENT_TYPE_LATEST},
            )
```

- [ ] Update `FastMcpBootstrapper.instruments_types`:

```python
    instruments_types: typing.ClassVar = [
        FastMcpHealthChecksInstrument,
        FastMcpPrometheusInstrument,
    ]
```

### Step 4: Run tests to verify pass

Run: `just test -- tests/test_fastmcp_bootstrap.py -v -k "prometheus or health_check"`

Expected: all five tests pass.

### Step 5: Commit

```bash
git add lite_bootstrap/bootstrappers/fastmcp_bootstrapper.py tests/test_fastmcp_bootstrap.py
git commit -m "feat: add FastMcpPrometheusInstrument"
```

---

## Task 9: Add `FastMcpLoggingInstrument` and register it

**Files:**
- Modify: `lite_bootstrap/bootstrappers/fastmcp_bootstrapper.py`
- Modify: `tests/test_fastmcp_bootstrap.py`

### Step 1: Write the failing tests

- [ ] Append to `tests/test_fastmcp_bootstrap.py`:

```python
def _find_mcp_logging_middleware(application: "FastMCP") -> list[FastMcpLoggingMiddleware]:
    return [m for m in application.middleware if isinstance(m, FastMcpLoggingMiddleware)]


def test_fastmcp_logging_middleware_is_mounted_by_default() -> None:
    config = _make_test_config()
    bootstrapper = FastMcpBootstrapper(bootstrap_config=config)
    application = bootstrapper.bootstrap()
    try:
        assert len(_find_mcp_logging_middleware(application)) == 1
    finally:
        bootstrapper.teardown()


def test_fastmcp_logging_middleware_disabled_via_flag() -> None:
    config = _make_test_config(logging_turn_off_middleware=True)
    bootstrapper = FastMcpBootstrapper(bootstrap_config=config)
    application = bootstrapper.bootstrap()
    try:
        assert _find_mcp_logging_middleware(application) == []
    finally:
        bootstrapper.teardown()
```

### Step 2: Run tests to verify failure mode

Run: `just test -- tests/test_fastmcp_bootstrap.py -v -k "logging_middleware_is_mounted or logging_middleware_disabled"`

Expected: `test_fastmcp_logging_middleware_is_mounted_by_default` fails (`assert 0 == 1`), `test_fastmcp_logging_middleware_disabled_via_flag` passes incidentally.

### Step 3: Add the instrument

- [ ] In `lite_bootstrap/bootstrappers/fastmcp_bootstrapper.py`, after `FastMcpPrometheusInstrument`, add:

```python
@dataclasses.dataclass(kw_only=True)
class FastMcpLoggingInstrument(LoggingInstrument):
    bootstrap_config: FastMcpConfig

    def bootstrap(self) -> None:
        super().bootstrap()
        if self.bootstrap_config.logging_turn_off_middleware:
            return
        if not import_checker.is_structlog_installed:
            return
        self.bootstrap_config.application.add_middleware(FastMcpLoggingMiddleware())
```

- [ ] Update `FastMcpBootstrapper.instruments_types` to its final form (PyroscopeInstrument, SentryInstrument, then framework-specific ones — matching `FastStreamBootstrapper`'s order):

```python
    instruments_types: typing.ClassVar = [
        PyroscopeInstrument,
        SentryInstrument,
        FastMcpHealthChecksInstrument,
        FastMcpLoggingInstrument,
        FastMcpPrometheusInstrument,
    ]
```

### Step 4: Run tests to verify pass

Run: `just test -- tests/test_fastmcp_bootstrap.py -v`

Expected: all tests pass.

### Step 5: Commit

```bash
git add lite_bootstrap/bootstrappers/fastmcp_bootstrapper.py tests/test_fastmcp_bootstrap.py
git commit -m "feat: add FastMcpLoggingInstrument with MCP access middleware"
```

---

## Task 10: Add missing-dependency regression tests

Per the established project pattern (`test_faststream_bootstrap.py::test_faststream_bootstrapper_with_missing_instrument_dependency`), every framework bootstrapper has a parametrized test that confirms missing optional dependencies surface as warnings, not crashes.

**Files:**
- Modify: `tests/test_fastmcp_bootstrap.py`

### Step 1: Write the failing tests

- [ ] Update the imports at the top of `tests/test_fastmcp_bootstrap.py` to include the with-reload helper:

```python
from tests.conftest import emulate_package_missing, emulate_package_missing_with_module_reload
```

- [ ] Append to `tests/test_fastmcp_bootstrap.py`:

```python
@pytest.mark.parametrize(
    "package_name",
    [
        "sentry_sdk",
        "structlog",
        "prometheus_client",
    ],
)
def test_fastmcp_bootstrapper_with_missing_instrument_dependency(package_name: str) -> None:
    with emulate_package_missing(package_name), pytest.warns(UserWarning, match=package_name):
        FastMcpBootstrapper(bootstrap_config=FastMcpConfig())


def test_fastmcp_bootstrap_without_prometheus_client() -> None:
    # Regression guard mirroring the FastStream prometheus-missing test: ensures
    # FastMcpPrometheusInstrument.check_dependencies() prevents construction-time
    # failure when prometheus_client is absent.
    with emulate_package_missing_with_module_reload(
        "prometheus_client",
        ["lite_bootstrap.bootstrappers.fastmcp_bootstrapper"],
    ):
        with pytest.warns(UserWarning, match="prometheus_client"):
            bootstrapper = FastMcpBootstrapper(bootstrap_config=FastMcpConfig())
        bootstrapper.bootstrap()
        bootstrapper.teardown()


def test_fastmcp_bootstrap_without_structlog() -> None:
    # Regression guard: FastMcpLoggingInstrument.bootstrap() must short-circuit
    # the middleware registration when structlog is absent, because the
    # middleware references fastmcp_access_logger which only exists inside
    # the structlog guard.
    with emulate_package_missing_with_module_reload(
        "structlog",
        ["lite_bootstrap.bootstrappers.fastmcp_bootstrapper"],
    ):
        with pytest.warns(UserWarning, match="structlog"):
            bootstrapper = FastMcpBootstrapper(bootstrap_config=FastMcpConfig())
        bootstrapper.bootstrap()
        bootstrapper.teardown()
```

### Step 2: Run tests to verify pass

Run: `just test -- tests/test_fastmcp_bootstrap.py -v`

Expected: all tests pass. If `test_fastmcp_bootstrap_without_structlog` fails with a `NameError: name 'fastmcp_access_logger' is not defined`, recheck that `FastMcpLoggingInstrument.bootstrap()` shorts on `not import_checker.is_structlog_installed` *before* instantiating `FastMcpLoggingMiddleware`.

### Step 3: Commit

```bash
git add tests/test_fastmcp_bootstrap.py
git commit -m "test: cover missing optional dependencies for FastMcpBootstrapper"
```

---

## Task 11: Documentation updates

Documents the new bootstrapper end-to-end.

**Files:**
- Modify: `README.md`
- Modify: `docs/index.md`
- Modify: `docs/introduction/installation.md`
- Modify: `CLAUDE.md`
- Create: `docs/integrations/fastmcp.md`

### Step 1: Update `README.md`

- [ ] In `README.md` line 22–25, append `- [FastMCP](https://lite-bootstrap.readthedocs.io/integrations/fastmcp)` to the bullet list:

```markdown
Those instruments can be bootstrapped for:

- [LiteStar](https://lite-bootstrap.readthedocs.io/integrations/litestar)
- [FastStream](https://lite-bootstrap.readthedocs.io/integrations/faststream)
- [FastAPI](https://lite-bootstrap.readthedocs.io/integrations/fastapi)
- [FastMCP](https://lite-bootstrap.readthedocs.io/integrations/fastmcp)
- [services and scripts without frameworks](https://lite-bootstrap.readthedocs.io/integrations/free)
```

### Step 2: Update `docs/index.md`

- [ ] In `docs/index.md` line 19–22, append the matching bullet:

```markdown
Those instruments can be bootstrapped for:

- [LiteStar](integrations/litestar)
- [FastStream](integrations/faststream)
- [FastAPI](integrations/fastapi)
- [FastMCP](integrations/fastmcp)
- [services and scripts without frameworks](integrations/free)
```

### Step 3: Create `docs/integrations/fastmcp.md`

- [ ] Write `docs/integrations/fastmcp.md` with the following content:

````markdown
# Usage with `FastMCP`

## 1. Install `lite-bootstrap` with the FastMCP extras and any instruments you want:

`lite-bootstrap` does not ship a `fastmcp-all` rollup extra — compose the extras
you need explicitly.

=== "uv"

      ```bash
      uv add 'lite-bootstrap[fastmcp,fastmcp-metrics,sentry,logging,pyroscope]'
      ```

=== "pip"

      ```bash
      pip install 'lite-bootstrap[fastmcp,fastmcp-metrics,sentry,logging,pyroscope]'
      ```

=== "poetry"

      ```bash
      poetry add 'lite-bootstrap[fastmcp,fastmcp-metrics,sentry,logging,pyroscope]'
      ```

Read more about available extras [here](../../../introduction/installation):

## 2. Define bootstrapper config and build your application:

```python
from fastmcp import FastMCP
from lite_bootstrap import FastMcpBootstrapper, FastMcpConfig


bootstrapper_config = FastMcpConfig(
    service_name="microservice",
    service_version="2.0.0",
    service_environment="test",
    sentry_dsn="https://testdsn@localhost/1",
    prometheus_metrics_path="/custom-metrics/",
    health_checks_path="/custom-health/",
    logging_buffer_capacity=0,
)
bootstrapper = FastMcpBootstrapper(bootstrap_config=bootstrapper_config)
application: FastMCP = bootstrapper.bootstrap()


@application.tool
def greet_person(person_name: str) -> str:
    return f"Hello, {person_name}!"
```

Set `logging_turn_off_middleware=True` on the config to disable the per-MCP-message
access log middleware. Set `health_checks_enabled=False` to omit the health route.

## 3. Teardown

`FastMcpBootstrapper` does not wire teardown automatically (FastMCP captures its
lifespan at construction time only). Call `bootstrapper.teardown()` yourself
during shutdown — typically from a `lifespan=` callable you pass to `FastMCP`,
from an ASGI shutdown handler, or via `atexit`:

```python
import contextlib
from fastmcp import FastMCP


@contextlib.asynccontextmanager
async def lifespan(app: FastMCP):
    try:
        yield
    finally:
        bootstrapper.teardown()


bootstrapper_config = FastMcpConfig(
    service_name="microservice",
    application=FastMCP(lifespan=lifespan),
)
bootstrapper = FastMcpBootstrapper(bootstrap_config=bootstrapper_config)
application = bootstrapper.bootstrap()
```

Read more about available configuration options [here](../../../introduction/configuration):
````

### Step 4: Update `docs/introduction/installation.md`

- [ ] In the extras table (`docs/introduction/installation.md` lines 7–17), insert a new `FastMCP` column after `FastAPI`. The table becomes:

```markdown
| Instrument    | Litestar           | Faststream           | FastAPI           | FastMCP                  | Free Bootstrapper, without framework |
|---------------|--------------------|----------------------|-------------------|--------------------------|--------------------------------------|
| sentry        | `litestar-sentry`  | `faststream-sentry`  | `fastapi-sentry`  | `sentry` (compose)       | `sentry`                             |
| prometheus    | `litestar-metrics` | `faststream-metrics` | `fastapi-metrics` | `fastmcp-metrics`        | not used                             |
| opentelemetry | `litestar-otl`     | `faststream-otl`     | `fastapi-otl`     | not used                 | `otl`                                |
| pyroscope     | `pyroscope`        | `pyroscope`          | `pyroscope`       | `pyroscope`              | `pyroscope`                          |
| structlog     | `litestar-logging` | `faststream-logging` | `fastapi-logging` | `logging` (compose)      | `logging`                            |
| cors          | no extra           | not used             | no extra          | not used                 | not used                             |
| swagger       | no extra           | not used             | no extra          | not used                 | not used                             |
| health-checks | no extra           | no extra             | no extra          | no extra                 | not used                             |
| all           | `litestar-all`     | `faststream-all`     | `fastapi-all`     | no rollup (compose)      | `free-all`                           |
```

Above the table (after line 5), add the note:

```markdown
FastMCP has no per-pair (`fastmcp-sentry`, …) or rollup (`fastmcp-all`) extras because they would not pull in new dependencies. Compose what you need yourself, e.g. `lite-bootstrap[fastmcp,fastmcp-metrics,sentry,logging,pyroscope]`.
```

### Step 5: Update `CLAUDE.md`

- [ ] In `CLAUDE.md` under "Core pattern" (the `BaseBootstrapper` tree), insert `FastMcpBootstrapper` before `FreeBootstrapper`:

```
BaseBootstrapper (abc.ABC)
    ├── FastAPIBootstrapper
    ├── LitestarBootstrapper
    ├── FastStreamBootstrapper
    ├── FastMcpBootstrapper
    └── FreeBootstrapper
```

Do not add a row to the "Optional dependency groups" table — there is no `fastmcp-all` rollup, and the table only lists rollups.

### Step 6: Commit

```bash
git add README.md docs/index.md docs/introduction/installation.md CLAUDE.md docs/integrations/fastmcp.md
git commit -m "docs: document FastMcpBootstrapper integration"
```

---

## Task 12: Final lint, full test, and PR

**Files:** (no source changes; verification + PR)

### Step 1: Full lint

Run: `just lint`

Expected: clean exit. If `ty` reports issues, fix them inline before continuing. Typical pyright false positives (`reportPossiblyUnbound`, etc.) are suppressed project-wide per the existing `[tool.pyright]` block and should not surface; `ty` is the enforcing checker.

### Step 2: Full test suite

Run: `just test`

Expected: full pass. Confirm `tests/test_fastmcp_bootstrap.py` reports ~15 tests, all passing. Total suite count should be ≈ previous_count + 15 (parametrized).

### Step 3: Branch verification

Run: `git log --oneline main..HEAD`

Expected: 10 commits, in order:

```
docs: document FastMcpBootstrapper integration
test: cover missing optional dependencies for FastMcpBootstrapper
feat: add FastMcpLoggingInstrument with MCP access middleware
feat: add FastMcpPrometheusInstrument
feat: add FastMcpHealthChecksInstrument
feat: add FastMcpLoggingMiddleware
test: verify FastMcpBootstrapper teardown via ASGI lifespan
feat: scaffold FastMcpBootstrapper and FastMcpConfig
feat: add fastmcp and fastmcp-metrics extras
feat: detect fastmcp via import_checker
```

(Newest first.)

### Step 4: Push and open PR

```bash
git push -u origin feat/fastmcp-bootstrapper
```

Then open the PR:

```bash
gh pr create --title "feat: add FastMcpBootstrapper" --body "$(cat <<'EOF'
## Summary

- Add `FastMcpBootstrapper` and `FastMcpConfig` wiring the lite-bootstrap instrument stack (Sentry, Pyroscope, structlog logging with MCP-aware access middleware, health checks, Prometheus metrics) onto a FastMCP server.
- Plumb teardown through the FastMCP lifespan via `combine_lifespans` so shutdown runs deterministically on ASGI lifespan shutdown.
- Add `fastmcp` and `fastmcp-metrics` extras. No composite or rollup extras (project rule: extras must add a direct dependency).
- Document the integration (README, docs/index, new `docs/integrations/fastmcp.md`, extras table).

Mirrors the instrument set merged upstream in [microbootstrap PR #141](https://github.com/community-of-python/microbootstrap/pull/141) and improves on it by wiring teardown.

Spec: `docs/superpowers/specs/2026-06-01-fastmcp-bootstrapper-design.md`.

## Test plan

- [x] `just test` — full suite passes (including 15 new fastmcp tests)
- [x] `just lint` — clean
- [ ] Manual smoke test: build a FastMCP server, register `/health/` and `/metrics`, hit them via `application.http_app()`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Return the PR URL.

---

## Self-review checklist (run before handoff)

1. **Spec coverage:**
   - Config (`FastMcpConfig` + `application` field + `logging_turn_off_middleware`) → Task 4 Step 3.
   - `FastMcpLoggingMiddleware` → Task 6.
   - `FastMcpHealthChecksInstrument` → Task 7.
   - `FastMcpPrometheusInstrument` → Task 8.
   - `FastMcpLoggingInstrument` → Task 9.
   - `FastMcpBootstrapper` + teardown lifespan wiring → Task 4 Step 3 (skeleton) + Task 5 (test).
   - `is_fastmcp_installed` → Task 2.
   - `fastmcp` + `fastmcp-metrics` extras → Task 3.
   - All 13 spec tests → distributed across Tasks 4, 5, 6, 7, 8, 9; the missing-dependency parametrized test + structlog-absent guard from spec §Edge cases → Task 10.
   - All docs changes → Task 11.
   - PyPI keyword → Task 3 Step 2.

2. **Placeholder scan:** No "TBD", "TODO", or "fill in" markers. Every code step contains the actual code. No "similar to Task N" references — each task is self-contained.

3. **Type consistency:**
   - `FastMcpConfig` used consistently in all instrument `bootstrap_config:` annotations (Tasks 4, 7, 8, 9).
   - `FastMcpLoggingMiddleware` referenced by full name in Tasks 6 (definition), 9 (registration), 10 (regression test) — no typo variants.
   - `application.lifespan` mutation pattern in Task 4 Step 3 matches the test in Task 5 Step 1 (no signature drift).
   - `_make_test_config` helper introduced in Task 7 Step 1 is referenced in Tasks 8 and 9 — confirm Task 8/9 do NOT re-import it.
   - `_drive_asgi_lifespan` helper introduced in Task 5 Step 1 — only used in Task 5 tests; no later task references it.
   - `_find_mcp_logging_middleware` helper introduced in Task 9 Step 1 — only used in Task 9.

4. **No new test deps:** All tests use stdlib (`contextlib`, `time`, `typing`, `unittest.mock`), already-installed test deps (`pytest`, `structlog`, `prometheus_client`), `starlette.testclient` (transitive via `fastmcp`), and `fastmcp` itself (Task 3 install). No new dev-group entries needed.
