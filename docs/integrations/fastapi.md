# Usage with `FastAPI`

*Another example of usage with FastAPI - [fastapi-sqlalchemy-template](https://github.com/modern-python/fastapi-sqlalchemy-template)*

## 1. Install `lite-bootstrap[fastapi-all]`:

=== "uv"

      ```bash
      uv add "lite-bootstrap[fastapi-all]"
      ```

=== "pip"

      ```bash
      pip install "lite-bootstrap[fastapi-all]"
      ```

=== "poetry"

      ```bash
      poetry add "lite-bootstrap[fastapi-all]"
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

## Sentry

While Sentry tracing is off, lite-bootstrap reports request errors itself instead of through
sentry-sdk's `StarletteIntegration` and `FastApiIntegration`. Tracing counts as off when
`sentry_traces_sample_rate` is unset and `sentry_additional_params` sets none of
`traces_sample_rate`, `traces_sampler` and `enable_tracing`. With tracing off, the integrations
still build a transaction for every request and then discard it
([getsentry/sentry-python#7400](https://github.com/getsentry/sentry-python/issues/7400)).

`sentry_lean_error_capture` picks the path:

- `None`, the default: lean capture while tracing is off and `sentry_integrations` holds neither
  integration, the integrations otherwise.
- `True`: lean capture always. lite-bootstrap warns when tracing is on, since no request starts a
  transaction, and when `sentry_integrations` holds either integration, which gets dropped.
- `False`: the integrations always.

Lean capture passes both integrations in `disabled_integrations` and adds one pure-ASGI middleware.
It gives each HTTP and WebSocket request its own Sentry scope, and its own release-health session
when `sentry_auto_session_tracking` is on. It continues an incoming `sentry-trace` and `baggage`,
and attaches the request to every event sent while the request runs.

The request data follows the same [`data_collection`](../introduction/configuration.md#sentry-data-collection)
settings the integrations read. Method, URL, query string, headers and cookies are filtered by
their denylists. The event's transaction is the route template, such as `/items/{item_id}`. The
client address and the user that Starlette's `AuthenticationMiddleware` sets are attached only
when `user_info` is on. A body is attached only when `http_bodies` includes `"incoming_request"`
and the handler has read all of it: lean capture copies what the application reads and never
reads the stream itself. JSON and URL-encoded form bodies are attached parsed, a multipart body is
replaced by a placeholder, and any other body is attached as text. On sentry-sdk 2.x the
integrations read the body before the handler runs.

What is reported matches the integrations. An exception that escapes the application is reported.
An exception that an exception handler answers is reported only when it carries a `status_code`
from 500 to 599, as `HTTPException(503)` does, whatever the handler responds. So a 404 from
`HTTPException` is not reported, and neither is a custom exception your handler turns into a 503
unless the exception itself has a 5xx `status_code`. To find those handlers, lean capture looks
through the middleware below it for Starlette's `ExceptionMiddleware`. A middleware added before
bootstrap that keeps its inner application anywhere but `.app` hides it, and then only escaping
exceptions are reported.

uvicorn and Granian log an exception that escapes the application. sentry-sdk's dedupe integration
drops that log event, because it carries the same exception, so each failing request sends one
event either way.

Measured in-process on a do-nothing handler, over the same app without Sentry:

| Sentry setup | sentry-sdk 2.73.0 | 3.0.0b2 |
|---|---:|---:|
| lean capture, the default | +6.1 µs | +5.1 µs |
| the same, request carries a sampled `sentry-trace` | +11.5 µs | +10.9 µs |
| `sentry_lean_error_capture=False` | +57.1 µs | +47.0 µs |
| the same, request carries a sampled `sentry-trace` | +59.2 µs | +113.2 µs |

sentry-sdk records installed integrations for the whole process, and `disabled_integrations`
cannot remove one that an earlier `sentry_sdk.init` installed. That matters only with
[`sentry_auto_enabling_integrations`](../introduction/configuration.md#sentry-auto-enabling-integrations)
on, since lean capture otherwise leaves auto-enabling off and sentry-sdk never enables the framework
integration. With it on, lite-bootstrap warns that errors may be reported twice.

## Logging

Structlog is configured process-wide, so `structlog.get_logger()` works in any route handler.

FastAPI has no access log of its own, so lite-bootstrap provides one. It is **off by default**,
because uvicorn already writes an access line per request and an HTTP service is the highest-volume
place to add a log record. Turn it on explicitly:

```python
FastAPIConfig(
    service_name="microservice",
    logging_access_log_enabled=True,
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
    logging_access_log_enabled=True,
    logging_unset_handlers=["uvicorn.access"],
)
```
