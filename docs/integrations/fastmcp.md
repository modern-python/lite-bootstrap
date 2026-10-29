# Usage with `FastMCP`

## 1. Install `lite-bootstrap[fastmcp-all]`:

=== "uv"

      ```bash
      uv add "lite-bootstrap[fastmcp-all]"
      ```

=== "pip"

      ```bash
      pip install "lite-bootstrap[fastmcp-all]"
      ```

=== "poetry"

      ```bash
      poetry add "lite-bootstrap[fastmcp-all]"
      ```

Read more about available extras [here](../introduction/installation.md).

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
)
bootstrapper = FastMcpBootstrapper(bootstrap_config=bootstrapper_config)
application: FastMCP = bootstrapper.bootstrap()


@application.tool
def greet_person(person_name: str) -> str:
    return f"Hello, {person_name}!"
```

## Logging

The per-MCP-message access log is **off by default**, matching FastAPI and Litestar. Turn it on
explicitly:

```python
FastMcpConfig(
    service_name="microservice",
    logging_access_log_enabled=True,
)
```

Enabled, each message is logged with its `method`, `source` and `type`, plus `duration` in
nanoseconds. A message that raises is logged at exception level and the exception is re-raised.

lite-bootstrap 2.0 requires fastmcp 4, where this log sees every message a client sends. That
includes notifications such as `notifications/initialized` and `notifications/cancelled`, the
`server/discover` request of a modern connection, and requests that fail before reaching a handler.
On fastmcp 3 it saw only routable requests.

Set `health_checks_enabled=False` to omit the health route.

## Sentry

While Sentry tracing is off, lite-bootstrap reports errors in every application
`application.http_app()` builds itself, instead of through sentry-sdk's `StarletteIntegration`.
FastMCP's HTTP application is a Starlette application, so it works as it does
[on FastAPI](fastapi.md#sentry): the same `sentry_lean_error_capture` rule, the same middleware and
the same request data. Lean capture also leaves
[auto-enabling integrations](../introduction/configuration.md#sentry-auto-enabling-integrations) off,
which drops `MCPIntegration` too. With tracing off it measured no cost per tool call, and the only
difference it made to a tool error's event was a `parent_span_id` from its unsampled span.

A tool that raises does not fail the request: FastMCP answers with an error result and logs the
exception, and the logging integration turns that record into one event with the `/mcp` request
attached, with lean capture on or off and with `MCPIntegration` on or off.

Measured in-process per `tools/call` over stateless JSON HTTP, over the same app without Sentry:

| Sentry setup | sentry-sdk 2.73.0 |
|---|---:|
| lean capture, the default | +20.6 µs |
| `sentry_lean_error_capture=False` | +82.2 µs |
| the same, request carries a sampled `sentry-trace` | +82.3 µs |

A tool call costs about 620 µs before Sentry, and rows differ by up to 15% between runs.

## Metrics

With the `fastmcp-metrics` extra installed, the registry is served at `prometheus_metrics_path`,
every application `application.http_app()` builds counts its requests by route, and every tool call
is counted and timed. See [the configuration reference](../introduction/configuration.md#prometheus-fastmcp)
for the metric names and parameters.

## Tracing

With `opentelemetry_endpoint` set (and the `fastmcp-otl` extra installed), every ASGI application
`application.http_app()` builds, including the one `application.run(transport="http")` builds, is
wrapped in OpenTelemetry's ASGI middleware. Each request produces a server span named after its
route, such as `POST /mcp` or `GET /health/`, with the route in `http.route`. A request to an
unknown path produces a span named after the HTTP method alone, without `http.route`.

The metrics path, the health-check path (unless `opentelemetry_generate_health_check_spans` is True)
`opentelemetry_excluded_urls` and `OTEL_PYTHON_STARLETTE_EXCLUDED_URLS` produce no spans. An application already instrumented by
`StarletteInstrumentor` is left as is, so no request is traced twice.

Teardown is wired through FastMCP's provider lifecycle: `bootstrapper.teardown()`
runs automatically when the FastMCP server's ASGI lifespan shuts down (i.e. when
the application that serves `application.http_app()` shuts down).

Read more about available configuration options [here](../introduction/configuration.md).
