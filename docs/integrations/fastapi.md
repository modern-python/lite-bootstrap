# Usage with `FastAPI`

*Another example of usage with FastAPI - [fastapi-sqlalchemy-template](https://github.com/modern-python/fastapi-sqlalchemy-template)*

## 1. Install `lite-bootstrap[fastapi-all]`:

=== "uv"

      ```bash
      uv add lite-bootstrap[fastapi-all]
      ```

=== "pip"

      ```bash
      pip install lite-bootstrap[fastapi-all]
      ```

=== "poetry"

      ```bash
      poetry add lite-bootstrap[fastapi-all]
      ```

Read more about available extras [here](../introduction/installation.md).

## 2. Define bootstrapper config and build your application:

```python
from lite_bootstrap import FastAPIConfig, FastAPIBootstrapper


bootstrapper_config = FastAPIConfig(
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
bootstrapper = FastAPIBootstrapper(bootstrapper_config)
application = bootstrapper.bootstrap()
```

Read more about available configuration options [here](../introduction/configuration.md).

## Logging

Structlog is configured process-wide, so `structlog.get_logger()` works in any route handler.

FastAPI has no access log of its own, so lite-bootstrap provides one. It is **off by default**,
because uvicorn already writes an access line per request and an HTTP service is the highest-volume
place to add a log record. Turn it on explicitly:

```python
FastAPIConfig(
    service_name="microservice",
    fastapi_logging_middleware_enabled=True,
)
```

Enabled, it writes one `http_request` line per request to the `http.access` logger, carrying `method`,
`path`, `content_type`, `path_params` and `status_code` under `http`, plus `duration` in nanoseconds.
A request that raises is logged at exception level and the exception is re-raised unchanged.

Request and response **bodies are never read or logged**. `path` and `path_params` are, so a secret
embedded in the URL itself (e.g. `/reset-password/{token}`) is recorded. Keep secrets in the request
body.

These paths are skipped, whether or not the corresponding instrument is configured: `swagger_path`,
`swagger_static_path` (when `swagger_offline_docs` is on), `health_checks_path` and
`prometheus_metrics_path`. So if you disable health checks but still serve your own route at
`health_checks_path`, that route is not access-logged either.

If you keep uvicorn's own access log as well, you will get two lines per request. To leave only the
structured one, clear uvicorn's handlers:

```python
FastAPIConfig(
    service_name="microservice",
    fastapi_logging_middleware_enabled=True,
    logging_unset_handlers=["uvicorn.access"],
)
```
