# Usage with `Litestar`

*Another example of usage with LiteStar - [litestar-sqlalchemy-template](https://github.com/modern-python/litestar-sqlalchemy-template)*

## 1. Install `lite-bootstrap[litestar-all]`:

=== "uv"

      ```bash
      uv add lite-bootstrap[litestar-all]
      ```

=== "pip"

      ```bash
      pip install lite-bootstrap[litestar-all]
      ```

=== "poetry"

      ```bash
      poetry add lite-bootstrap[litestar-all]
      ```

Read more about available extras [here](../introduction/installation.md).

## 2. Define bootstrapper config and build your application:

```python
from lite_bootstrap import LitestarConfig, LitestarBootstrapper


bootstrapper_config = LitestarConfig(
    service_name="microservice",
    service_version="2.0.0",
    service_environment="test",
    cors_allowed_origins=["http://test"],
    health_checks_path="/custom-health/",
    opentelemetry_endpoint="otl",
    prometheus_metrics_path="/custom-metrics/",
    sentry_dsn="https://testdsn@localhost/1",
    swagger_offline_docs=True,
)
bootstrapper = LitestarBootstrapper(bootstrapper_config)
application = bootstrapper.bootstrap()
```

Read more about available configuration options [here](../introduction/configuration.md).

## Logging

Structlog is integrated via Litestar's `StructlogPlugin`, which makes `request.logger` available in route handlers:

```python
from litestar import Request, get


@get("/items")
async def list_items(request: Request) -> list[str]:
    request.logger.info("listing items")
    return []
```

Litestar's own `LoggingMiddleware` is **off by default** here. Its defaults log
full request and response bodies, which puts credentials and the whole offline
Swagger bundle into your logs. Turn it on explicitly:

```python
LitestarConfig(
    service_name="microservice",
    litestar_logging_middleware_enabled=True,
)
```

Enabled this way, it logs metadata only — `path`, `method`, `content_type`,
`path_params` for requests and `status_code` for responses — and skips
`swagger_path`, `swagger_static_path` (when `swagger_offline_docs` is on),
`health_checks_path` and `prometheus_metrics_path`. Those four paths are
excluded whether or not the corresponding instrument is actually configured —
so if you disable health checks but still serve your own route at
`health_checks_path`, that route is not access-logged either.

`path` and `path_params` are logged, so a secret embedded in the URL itself
(e.g. `/reset-password/{token}`) is recorded. Keep secrets in the request
body, which is never logged.

To take full control, pass your own config (it replaces the defaults above
entirely, including the path exclusions):

```python
from litestar.middleware.logging import LoggingMiddlewareConfig

LitestarConfig(
    service_name="microservice",
    litestar_logging_middleware_enabled=True,
    litestar_logging_middleware_config=LoggingMiddlewareConfig(request_log_fields=("path", "method", "content_type")),
)
```

A bare `LoggingMiddlewareConfig()` restores Litestar's own defaults wholesale
— including full request/response body logging — so pass explicit
`request_log_fields` / `response_log_fields` rather than relying on the
built-in default.

## Prometheus

`prometheus_group_path` defaults to `True`, so the `path` metric label uses the
route template (`/users/{id}`) instead of the raw URL. This bounds metric
cardinality; without it, parameterized routes mint a new series per distinct
value and grow memory unbounded ([litestar#4891](https://github.com/litestar-org/litestar/issues/4891)).

Set `prometheus_group_path=False` to record raw paths. Anything in
`prometheus_additional_params` (including `group_path`) overrides the default:

```python
LitestarConfig(
    service_name="microservice",
    prometheus_group_path=False,  # raw paths
    prometheus_additional_params={"exclude_unhandled_paths": True},
)
```
