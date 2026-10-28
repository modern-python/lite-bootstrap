# Usage with `Litestar`

*Another example of usage with Litestar - [litestar-sqlalchemy-template](https://github.com/modern-python/litestar-sqlalchemy-template)*

## 1. Install `lite-bootstrap[litestar-all]`:

=== "uv"

      ```bash
      uv add "lite-bootstrap[litestar-all]"
      ```

=== "pip"

      ```bash
      pip install "lite-bootstrap[litestar-all]"
      ```

=== "poetry"

      ```bash
      poetry add "lite-bootstrap[litestar-all]"
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

The bootstrapper builds the `Litestar` app itself with `Litestar.from_config`, so app-level settings
go into `application_config=AppConfig(...)` instead of an `application` argument
([ADR-0007](https://github.com/modern-python/lite-bootstrap/blob/main/docs/adr/0007-no-django-bootstrapper.md)
records why).

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
    logging_access_log_enabled=True,
)
```

Enabled this way, it logs metadata only (`path`, `method`, `content_type`,
`path_params` for requests and `status_code` for responses) and skips
`swagger_path`, `swagger_static_path` (when `swagger_offline_docs` is on),
`health_checks_path` and `prometheus_metrics_path`. Those four paths are
excluded whether or not the corresponding instrument is configured, so if
you disable health checks but still serve your own route at
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
    logging_access_log_enabled=True,
    litestar_logging_middleware_config=LoggingMiddlewareConfig(request_log_fields=("path", "method", "content_type")),
)
```

A bare `LoggingMiddlewareConfig()` restores all of Litestar's own defaults,
including full request/response body logging, so pass explicit
`request_log_fields` / `response_log_fields`.

## Sentry

While Sentry tracing is off, lite-bootstrap reports request errors itself instead of through
sentry-sdk's `LitestarIntegration`. Tracing counts as off when `sentry_traces_sample_rate` is unset
and `sentry_additional_params` sets none of `traces_sample_rate`, `traces_sampler` and
`enable_tracing`. With tracing off, the integration still builds a transaction and a span per
middleware for every request and then discards them
([getsentry/sentry-python#7400](https://github.com/getsentry/sentry-python/issues/7400)). On
sentry-sdk 3.0, an incoming `sentry-trace` header marked as sampled makes it record a real span.

`sentry_lean_error_capture` picks the path:

- `None`, the default: lean capture while tracing is off and `sentry_integrations` holds no
  `LitestarIntegration`, the integration otherwise.
- `True`: lean capture always. lite-bootstrap warns when tracing is on, since no request starts a
  transaction, and when `sentry_integrations` holds a `LitestarIntegration`, which gets dropped.
- `False`: the integration always.

Lean capture passes `LitestarIntegration` in `disabled_integrations` and adds a middleware and an
`after_exception` hook. The middleware gives each request its own Sentry scope, and its own
release-health session when `sentry_auto_session_tracking` is on. It continues an incoming
`sentry-trace` and `baggage`, and attaches the request to every event sent while the request runs.

The request data follows the same [`data_collection`](../introduction/configuration.md#sentry-data-collection)
settings the integration reads. Method, URL, query string, headers and cookies are filtered by
their denylists. The client address and `scope["user"]` are attached only when `user_info` is on.
A body is attached only when `http_bodies` includes `"incoming_request"` and the handler has
already read it, because lean capture never reads the stream itself. The integration reads every
non-GET body before the handler runs.

An exception is reported only when its response is a 5xx, so one that your `exception_handlers`
answer with a 404 is not reported. The integration reports every exception except an
`HTTPException` below 500. Litestar logs the exceptions it handles, and lean capture keeps the
`litestar` logger from turning them into a second event, as the integration does.

Measured in-process on a do-nothing handler, over the same app without Sentry:

| Sentry setup | sentry-sdk 2.73.0 | 3.0.0b2 |
|---|---:|---:|
| lean capture, the default | +7.3 µs | +8.3 µs |
| `sentry_lean_error_capture=False` | +70.7 µs | +59.5 µs |
| the same, request carries a sampled `sentry-trace` | +74.4 µs | +147.4 µs |

sentry-sdk records installed integrations for the whole process, and `disabled_integrations`
cannot remove one that an earlier `sentry_sdk.init` installed. If that happened, lite-bootstrap
warns that errors may be reported twice.

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

## Request body size limit

`LitestarBootstrapper` builds its app with `Litestar.from_config()`, which,
unlike `Litestar(...)`, passes every `AppConfig` field explicitly and so
skips the 10 MB `request_max_body_size` default that `Litestar(...)` applies.
Left as-is, that means every handler that reads a request body returns `500:
'request_max_body_size' set to 'Empty' on all layers`
([litestar#4296](https://github.com/litestar-org/litestar/issues/4296)).

The bootstrapper works around this by filling `request_max_body_size` with
Litestar's own 10 MB default whenever your `AppConfig` leaves it unset. This
is not exposed as a `LitestarConfig` field. Set it on your own `AppConfig`
instead, the same way as every other Litestar app-level knob:

```python
from litestar.config.app import AppConfig

LitestarConfig(
    service_name="microservice",
    application_config=AppConfig(request_max_body_size=5_000_000),  # 5 MB limit
)
```

Pass `request_max_body_size=None` for no limit. Any value you set, including
`None`, is left untouched; the bootstrapper only fills it in when it is
unset.
