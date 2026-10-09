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
    logging_buffer_capacity=0,
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
    fastmcp_logging_middleware_enabled=True,
)
```

Enabled, each message is logged with its `method`, `source` and `type`, plus `duration` in
nanoseconds. A message that raises is logged at exception level and the exception is re-raised.

Set `health_checks_enabled=False` to omit the health route.

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

The metrics path, the health-check path (unless `opentelemetry_generate_health_check_spans` is on)
`opentelemetry_excluded_urls` and `OTEL_PYTHON_STARLETTE_EXCLUDED_URLS` produce no spans. An application already instrumented by
`StarletteInstrumentor` is left as is, so no request is traced twice.

Teardown is wired through FastMCP's provider lifecycle — `bootstrapper.teardown()`
runs automatically when the FastMCP server's ASGI lifespan shuts down (i.e. when
the application that serves `application.http_app()` shuts down).

Read more about available configuration options [here](../introduction/configuration.md).
