---
status: shipped
date: 2026-06-01
slug: fastmcp-bootstrapper
summary: New `FastMcpBootstrapper` mirroring microbootstrap's fastmcp support.
supersedes: null
superseded_by: null
pr: null
outcome: shipped
---
# FastMCP Bootstrapper Design

**Date:** 2026-06-01
**Reference:** [microbootstrap PR #141](https://github.com/community-of-python/microbootstrap/pull/141) — "Add fastmcp bootstrapper" (merged upstream).
**Deliverable:** A new `FastMcpBootstrapper` that wires the same instrument set used by `FastStreamBootstrapper`, minus OpenTelemetry/CORS/Swagger. Includes a FastMCP protocol-level access-log middleware, a Prometheus `/metrics` route, and a JSON `/health` route — all mounted on the user's `FastMCP` instance.

This is a design spec, not an implementation plan. Per-PR sequencing and task-by-task execution are deferred to a follow-up plan produced by the `writing-plans` skill.

---

## Goals

- Match the behavior shipped by microbootstrap PR141: Sentry, Pyroscope, structlog-based logging (with an MCP-aware access middleware), an HTTP health endpoint, and an HTTP Prometheus endpoint.
- Match the lite-bootstrap architectural conventions (frozen-dataclass configs composed via multiple inheritance, framework-subclass instruments, `instruments_types` ClassVar, optional-import guards via `import_checker`).
- Improve over PR141 by wiring `teardown()` through FastMCP's `Provider.lifespan` hook so it runs automatically on ASGI shutdown.

> **Execution note (2026-06-01):** the design first tried to wrap `FastMCP.lifespan` via `combine_lifespans`. Implementation discovered `FastMCP.lifespan` is a read-only bound method and the runtime hook (`_lifespan`) is captured at constructor time only, so post-construction wrapping is impossible. We briefly fell back to "manual teardown" (matching microbootstrap PR141) but then identified `FastMCP.add_provider()` + `Provider.lifespan` as the correct post-construction hook — public, documented, invoked during ASGI startup/shutdown. Adopted; see §"Bootstrapper" and §"Tests" below. The PR's final code uses this approach.

## Non-goals

- No OpenTelemetry instrument. MCP is JSON-RPC, not REST; ASGI-level OTel spans would only cover the HTTP transport and not the MCP method dimension. (Decided in Q1.)
- No CORS or Swagger instruments. MCP isn't browser-facing and doesn't ship an OpenAPI document.
- No "composite extras" (`fastmcp-sentry`, `fastmcp-logging`, `fastmcp-all`). Per the project's extras rule, an extra exists only when it pulls in a new dependency. (Decided in Q5.)
- No stdio-only behavior changes. The bootstrapper works whether the user calls `application.run(transport="stdio")` or `application.http_app()`. The HTTP-only instruments (health, metrics) silently no-op when no HTTP transport is used.

---

## Architecture

### Module layout

| Path | Status | Purpose |
|------|--------|---------|
| `lite_bootstrap/bootstrappers/fastmcp_bootstrapper.py` | new | `FastMcpConfig`, `FastMcpLoggingMiddleware`, framework-specific instrument subclasses, `FastMcpBootstrapper`. Single-file layout matches FastStream. |
| `lite_bootstrap/import_checker.py` | modified | Add `is_fastmcp_installed = find_spec("fastmcp") is not None`. |
| `lite_bootstrap/__init__.py` | modified | Re-export `FastMcpConfig`, `FastMcpBootstrapper`. |
| `pyproject.toml` | modified | Add `fastmcp = ["fastmcp"]`, `fastmcp-metrics = ["lite-bootstrap[fastmcp]", "prometheus-client>=0.20"]`. Append `"fastmcp"` to `keywords`. |
| `tests/test_fastmcp_bootstrap.py` | new | Unit + integration tests (full list below). |
| `README.md` | modified | Add FastMCP to the supported-frameworks list. |
| `docs/index.md` | modified | Same addition. |
| `docs/integrations/fastmcp.md` | new | Mirror `docs/integrations/faststream.md` structure. |
| `docs/introduction/installation.md` | modified | Add a FastMCP column to the extras table + a one-line note about no composite/rollup extras. |
| `CLAUDE.md` | modified | Add `FastMcpBootstrapper` to the Core-pattern tree. No row added to the "Optional dependency groups" table (no rollup extra). |

No new package directories. `FastMcpLoggingMiddleware` lives in the same file as the bootstrapper, matching how `LitestarOpenTelemetryInstrumentationMiddleware` and FastStream's protocol classes are kept inline with their bootstrappers.

### Class shape

```
FastMcpConfig(HealthChecksConfig, LoggingConfig, PrometheusConfig, PyroscopeConfig, SentryConfig)
    application: FastMCP[Any]                       # default_factory=_make_fastmcp
    logging_turn_off_middleware: bool = False       # opt-out for the MCP access log middleware

FastMcpLoggingMiddleware(fastmcp.server.middleware.Middleware)
    on_message: log method/source/type/duration via `mcp.access` structlog logger

FastMcpHealthChecksInstrument(HealthChecksInstrument)
    bootstrap: application.custom_route(path, methods=["GET"]) → JSONResponse(render_health_check_data())

FastMcpLoggingInstrument(LoggingInstrument)
    bootstrap: super().bootstrap(); if not logging_turn_off_middleware and is_structlog_installed:
                   application.add_middleware(FastMcpLoggingMiddleware())

FastMcpPrometheusInstrument(PrometheusInstrument)
    check_dependencies: is_prometheus_client_installed
    missing_dependency_message: "prometheus_client is not installed"
    bootstrap: application.custom_route(metrics_path, methods=["GET"]) → Response(generate_latest(), CONTENT_TYPE_LATEST)

FastMcpBootstrapper(BaseBootstrapper["FastMCP[Any]"])
    instruments_types = [PyroscopeInstrument, SentryInstrument,
                         FastMcpHealthChecksInstrument, FastMcpLoggingInstrument, FastMcpPrometheusInstrument]
    is_ready: import_checker.is_fastmcp_installed
    __init__: super().__init__(config); wrap application.lifespan with teardown via combine_lifespans
    _prepare_application: return self.bootstrap_config.application
```

`SentryInstrument` and `PyroscopeInstrument` are used unchanged — they configure global SDKs, not the application object.

Instrument order (Pyroscope → Sentry → Health → Logging → Prometheus) mirrors `FastStreamBootstrapper.instruments_types` so cross-framework users see a consistent boot order.

### FastMCP integration details (from FastMCP docs)

- **Custom HTTP routes**: `@application.custom_route(path, methods=["GET"], name=..., include_in_schema=...)` registers Starlette-style handlers that surface on `application.http_app()`. Custom routes bypass `AuthProvider`, which is correct behavior for health and metrics endpoints.
- **MCP protocol middleware**: `application.add_middleware(middleware_instance)` registers a FastMCP `Middleware` subclass that runs on every MCP message (tools/list, tool/call, resources/list, etc.). This is distinct from Starlette HTTP middleware passed via `application.http_app(middleware=[...])`. We use the former because we want per-method MCP-level access logs.
- **Lifecycle hook — `Provider.lifespan`**: FastMCP exposes no `on_shutdown`-style API. `FastMCP(lifespan=...)` is constructor-only (the runtime hook is the private `_lifespan` attribute, captured at construction time). The only **public, post-construction** hook is `app.add_provider(provider)`: each registered provider's `async def lifespan(self)` runs as an async context manager during the server's ASGI lifespan startup/shutdown. The bootstrapper registers an empty internal `_TeardownProvider` whose `lifespan` calls `self.teardown()` on exit. Documented in FastMCP under "Custom Provider — Lifecycle Management".

---

## Config: `FastMcpConfig`

```python
def _make_fastmcp() -> "FastMCP[typing.Any]":
    return FastMCP()


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class FastMcpConfig(
    HealthChecksConfig, LoggingConfig, PrometheusConfig, PyroscopeConfig, SentryConfig
):
    application: "FastMCP[typing.Any]" = dataclasses.field(default_factory=_make_fastmcp)
    logging_turn_off_middleware: bool = False
```

- Frozen, `kw_only=True`, `slots=True` — matches every other framework config.
- `_make_fastmcp` is module-level so the default value is shared via factory (no mutable default footgun).
- `logging_turn_off_middleware` is a fastmcp-specific field, *not* a field on the shared `LoggingConfig` — only this bootstrapper installs an MCP middleware. The name matches microbootstrap PR141 for portability.
- No `UnsetType` sentinel (see CLAUDE.md "Key design decisions"): we don't need to derive any default-factory argument from sibling config fields. `FastMCP()` accepts no required arguments.

---

## Instruments

### `FastMcpLoggingMiddleware`

```python
fastmcp_access_logger: typing.Final = structlog.get_logger("mcp.access")  # gated by is_structlog_installed


class FastMcpLoggingMiddleware(Middleware):
    async def on_message(self, context, call_next):
        start = time.perf_counter_ns()
        mcp_fields = {"method": context.method, "source": context.source, "type": context.type}
        try:
            result = await call_next(context)
        except Exception:
            fastmcp_access_logger.exception(
                context.method or "unknown", mcp=mcp_fields, duration=time.perf_counter_ns() - start,
            )
            raise
        fastmcp_access_logger.info(
            context.method or "unknown", mcp=mcp_fields, duration=time.perf_counter_ns() - start,
        )
        return result
```

1:1 port of microbootstrap PR141's middleware. Logs one record per MCP message with method, source, type, and duration in nanoseconds. Uses a dedicated `mcp.access` structlog logger so consumers can filter/route MCP traffic independently of application logs.

### `FastMcpHealthChecksInstrument(HealthChecksInstrument)`

`bootstrap()` registers a `GET` route at `health_checks_path` (default `/health/`) returning `JSONResponse(self.render_health_check_data())`. `render_health_check_data()` returns the shared `HealthCheckTypedDict` (`service_name`, `service_version`, `health_status: True`) from the base instrument. Skipped when `health_checks_enabled=False` (handled by `HealthChecksInstrument.is_ready()`).

### `FastMcpLoggingInstrument(LoggingInstrument)`

`bootstrap()` calls `super().bootstrap()` (which configures structlog + foreign loggers), then conditionally calls `application.add_middleware(FastMcpLoggingMiddleware())` when both `logging_turn_off_middleware is False` and `is_structlog_installed is True`. The structlog guard is essential because `FastMcpLoggingMiddleware` references `fastmcp_access_logger`, which is only defined inside the `if import_checker.is_structlog_installed:` block.

### `FastMcpPrometheusInstrument(PrometheusInstrument)`

Overrides `check_dependencies()` to require `prometheus_client`, with `missing_dependency_message = "prometheus_client is not installed"` — matches `LitestarPrometheusInstrument` and `FastStreamPrometheusInstrument`. `bootstrap()` registers a `GET` route at `prometheus_metrics_path` that returns `Response(prometheus_client.generate_latest(prometheus_client.REGISTRY), headers={"content-type": prometheus_client.CONTENT_TYPE_LATEST})`. The default `prometheus_client.REGISTRY` is used (no fastmcp-specific registry field on the config), matching how the other lite-bootstrap framework configs treat the registry.

---

## Bootstrapper: `FastMcpBootstrapper`

```python
class FastMcpBootstrapper(BaseBootstrapper["FastMCP[typing.Any]"]):
    __slots__ = "bootstrap_config", "instruments"

    instruments_types: typing.ClassVar = [
        PyroscopeInstrument,
        SentryInstrument,
        FastMcpHealthChecksInstrument,
        FastMcpLoggingInstrument,
        FastMcpPrometheusInstrument,
    ]
    bootstrap_config: FastMcpConfig
    not_ready_message = "fastmcp is not installed"

    def is_ready(self) -> bool:
        return import_checker.is_fastmcp_installed

    def __init__(self, bootstrap_config: FastMcpConfig) -> None:
        super().__init__(bootstrap_config)
        self.bootstrap_config.application.add_provider(_TeardownProvider(self.teardown))

    def _prepare_application(self) -> "FastMCP[typing.Any]":
        return self.bootstrap_config.application
```

`_TeardownProvider` is a module-private `Provider` subclass whose `lifespan` async-cm wraps a `try/yield/finally` that calls the supplied teardown callable on exit. Registered automatically from `__init__` so users don't need to call `bootstrap_config.application.add_provider(...)` themselves.

### Teardown via Provider.lifespan

`FastMCP.lifespan` is a bound method on the `AggregateProvider` mixin (not a settable attribute), and the actual runtime hook is the private `_lifespan` attribute set at constructor time only. Setting `app.lifespan = ...` succeeds but has zero runtime effect — FastMCP's transport runners read `_lifespan` directly.

The public alternative: `app.add_provider(provider)` accepts a provider post-construction, and FastMCP invokes each registered provider's `async def lifespan(self)` as part of the server's ASGI lifespan startup/shutdown sequence. Verified empirically: registering a `Provider` after construction and driving the ASGI lifespan startup → shutdown does execute the provider's `lifespan` exit branch.

This gives us a documented, public hook with the right semantics. Trade-off: `Provider` is FastMCP's general extension abstraction (for tools/resources/prompts) and using it solely for a shutdown callback is semantically thin — a one-line comment in the source notes that this is the only public post-construction hook for the purpose.

Resolution paths considered and rejected:

- **Mutate `app._lifespan` directly** — works today, but reaches into private API.
- **Rebuild the user's `FastMCP` with a composed `lifespan=`** — intrusive; breaks the "user owns the FastMCP" contract.
- **No automatic wiring (manual teardown)** — adopted briefly, then reverted when `add_provider` was identified.

---

## Optional-import guards

Top-level conditional imports inside `lite_bootstrap/bootstrappers/fastmcp_bootstrapper.py`:

```python
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
```

`starlette` is a fastmcp transitive dependency, so the fastmcp guard covers it. Pyright will flag `reportPossiblyUnbound` on these — expected and suppressed project-wide per the `[tool.pyright]` block (see CLAUDE.md "Type checking"). `ty` (the enforced checker) handles the guard correctly.

---

## Tests (`tests/test_fastmcp_bootstrap.py`)

Async tests rely on the project's existing `asyncio_mode = "auto"` pytest-asyncio setting. No new fixtures needed beyond `conftest.py`.

1. **`test_fastmcp_bootstrap_returns_fastmcp_instance`** — `FastMcpBootstrapper(FastMcpConfig(service_name="x", service_version="1")).bootstrap()` returns the same `FastMCP` instance, confirming `_prepare_application` short-circuits to the configured app.
2. **`test_fastmcp_health_check_route_serves_200_with_data`** — boot, hit `application.http_app()` via `httpx.AsyncClient` at `/health/`, assert 200 + JSON body matching `service_name`, `service_version`, `health_status: True`.
3. **`test_fastmcp_health_check_path_is_configurable`** — set `health_checks_path="/healthz"`, assert route mounted at that path.
4. **`test_fastmcp_health_check_disabled_when_flag_false`** — `health_checks_enabled=False`, assert `/health/` returns 404.
5. **`test_fastmcp_prometheus_route_exposes_registered_metric`** — register a counter on the default registry, boot, GET `/metrics`, assert `content-type` matches `prometheus_client.CONTENT_TYPE_LATEST` and the counter name appears in the body.
6. **`test_fastmcp_prometheus_path_is_configurable`** — set `prometheus_metrics_path="/m"`, assert mounted there.
7. **`test_fastmcp_logging_middleware_is_mounted_by_default`** — assert a `FastMcpLoggingMiddleware` instance appears in `application.middleware`.
8. **`test_fastmcp_logging_middleware_disabled_via_flag`** — `logging_turn_off_middleware=True`, assert no `FastMcpLoggingMiddleware` in `application.middleware`.
9. **`test_fastmcp_logging_middleware_logs_method_source_type_and_duration`** — drive `on_message` directly with a hand-built `MiddlewareContext` and `monkeypatch.setattr` the `fastmcp_access_logger`; assert `info(...)` called once with `method="tools/list"`, `mcp={"method": ..., "source": ..., "type": ...}`, and an integer `duration`.
10. **`test_fastmcp_logging_middleware_logs_exception_on_failure`** — `call_next` raises a custom exception; assert `exception(...)` called once and the exception propagates.
11. **`test_fastmcp_teardown_resets_is_bootstrapped`** — boot, call `bootstrapper.teardown()` directly, assert `bootstrapper.is_bootstrapped is False`.
12. **`test_fastmcp_teardown_runs_via_asgi_lifespan`** — boot, drive the ASGI lifespan startup → shutdown of `application.http_app()` via a hand-rolled ASGI driver, assert `bootstrapper.is_bootstrapped is False` after shutdown (proves the `_TeardownProvider` registration runs through FastMCP's provider lifecycle).
13. **`test_fastmcp_bootstrapper_not_ready_when_fastmcp_missing`** — `emulate_package_missing("fastmcp")`, assert `BootstrapperNotReadyError` raised with `"fastmcp is not installed"`.

Tests 9 and 10 hand-build `MiddlewareContext` instances and monkeypatch the module-level logger — this matches the test style microbootstrap PR141 uses (`tests/middlewares/test_fastmcp.py`).

---

## Docs updates

### `README.md`

Append to the framework list (line 22–25):

```markdown
- [FastMCP](https://lite-bootstrap.readthedocs.io/integrations/fastmcp)
```

### `docs/index.md`

Same addition to the framework list (line 19–22).

### `docs/integrations/fastmcp.md` (new)

Mirror `docs/integrations/faststream.md` structure:

- Section 1: install snippet for `uv add` / `pip install` / `poetry add` with extras `[fastmcp,fastmcp-metrics,sentry,logging,pyroscope]` (manual composition since there's no `fastmcp-all` rollup).
- Section 2: bootstrap example. Construct `FastMcpConfig(service_name=..., service_version=..., sentry_dsn=..., ...)`, build the bootstrapper, call `.bootstrap()`, register a `@application.tool` to show the working surface.

### `docs/introduction/installation.md`

Add a FastMCP column to the extras table. Values:

| Instrument    | FastMCP                |
|---------------|------------------------|
| sentry        | `sentry` (compose)     |
| prometheus    | `fastmcp-metrics`      |
| opentelemetry | not used               |
| pyroscope     | `pyroscope`            |
| structlog     | `logging` (compose)    |
| cors          | not used               |
| swagger       | not used               |
| health-checks | no extra               |
| all           | no rollup (compose)    |

Add a one-line note above the table: "FastMCP has no per-pair (`fastmcp-sentry`, …) or rollup (`fastmcp-all`) extras because they would not pull in new dependencies — compose them yourself: `lite-bootstrap[fastmcp,fastmcp-metrics,sentry,logging,pyroscope]`."

### `CLAUDE.md`

Add `FastMcpBootstrapper` to the `BaseBootstrapper` tree under "Core pattern":

```
BaseBootstrapper (abc.ABC)
    ├── FastAPIBootstrapper
    ├── LitestarBootstrapper
    ├── FastStreamBootstrapper
    ├── FastMcpBootstrapper
    └── FreeBootstrapper
```

No new row in the "Optional dependency groups" table (there is no `fastmcp-all` rollup).

### `pyproject.toml`

Append `"fastmcp"` to the `keywords` list for PyPI discoverability.

---

## Edge cases & decisions log

- **Stdio-only servers**: `FastMcpBootstrapper` accepts a `FastMCP` instance that the user later runs via `transport="stdio"`. The Sentry, Pyroscope, and Logging instruments take effect; the health and metrics routes never receive traffic because no HTTP transport is mounted. No special handling — same as how `FastStreamBootstrapper` assumes the user calls `AsgiFastStream.run()` to expose its ASGI surface.
- **Health check on FastMCP without `http_app()`**: covered above — silently inert. If we ever want to support stdio-mode health pings via a separate channel, that's a future scope expansion, not part of this design.
- **User passes a `FastMCP` with an existing `add_middleware` chain**: our middleware is appended to whatever the user has; FastMCP's middleware list is order-significant (registration order = execution order), so we register last. Documented in the integrations page snippet.
- **`PrometheusInstrument.check_dependencies` override**: required because the shared `PrometheusInstrument` base doesn't gate on `prometheus_client` — the framework subclasses do. Same pattern as `LitestarPrometheusInstrument` and `FastStreamPrometheusInstrument`.
- **No backward-compat alias**: this is a fresh public name (`FastMcpBootstrapper`, `FastMcpConfig`). The "backward-compat aliases for renames" convention from CLAUDE.md doesn't apply.

---

## Out of scope (explicit)

- OpenTelemetry instrument for FastMCP (Q1).
- CORS / Swagger instruments for FastMCP.
- A "FastMCP examples" subdirectory under the repo (PR141 has one upstream; lite-bootstrap doesn't keep example apps in-repo).
- Migration tooling for users coming from microbootstrap (config-field surface is intentionally narrower).
- A `fastmcp-all` extra (Q5).

---

## Open questions

None at design time. The two judgment calls flagged during brainstorming —
"how does FastMCP expose lifespan mutation?" and "how does the MCP access logger
interact with structlog being absent?" — are resolved in the "Teardown wiring
risk" and "Optional-import guards" sections above.
