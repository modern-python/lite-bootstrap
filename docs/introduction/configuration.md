# Configuration

## Sentry

Sentry integration uses `sentry_sdk` package under the hood.

To bootstrap Sentry, you must provide at least:

- `sentry_dsn` - tells sentry-sdk where to send the events.

Additional parameters can also be supplied through the settings object:

- `sentry_traces_sample_rate` - in the range of 0.0 to 1.0, the percentage chance a given transaction will be sent 
- `sentry_sample_rate` - in the range of 0.0 to 1.0, the sample rate for error events
- `sentry_max_breadcrumbs` - the total amount of breadcrumbs
- `sentry_max_value_length` - the max event payload length
- `sentry_attach_stacktrace` - if True, stack traces are automatically attached to all messages logged
- `sentry_integrations` - list of integrations to enable
- `sentry_tags` - key/value string pairs that are both indexed and searchable
- `sentry_additional_params` - additional params, which will be passed to `sentry_sdk.init`
- `sentry_default_integrations` - whether to use sentry's default integrations (default: `True`)
- `sentry_before_send` - optional callback chained after the built-in structlog enricher, passed to `sentry_sdk.init(before_send=...)`

Read more about sentry_sdk params [here](https://docs.sentry.io/platforms/python/configuration/options/).


## Prometheus

To bootstrap Prometheus, you must provide at least:

- `prometheus_metrics_path`.

Additional parameters:

- `prometheus_metrics_include_in_schema`.

### Prometheus Litestar

Prometheus's integration for Litestar requires `prometheus_client` package.

Additional parameters for Litestar integration:

- `prometheus_group_path` - defaults to `True` so the `path` metric label uses the route template (`/users/{id}`) instead of the raw URL, bounding metric cardinality. Set to `False` to record raw paths.
- `prometheus_additional_params` - passed to `litestar.plugins.prometheus.PrometheusConfig`.

### Prometheus FastStream

Prometheus's integration for FastStream requires `prometheus_client` package.

To bootstrap Prometheus for FastStream, you must provide additionally:

- `prometheus_middleware_cls`.

### Prometheus FastAPI

Prometheus's integration for FastAPI uses `prometheus_fastapi_instrumentator` package.

Additional parameters for FastAPI integration:

- `prometheus_instrumentator_params` - passed to `prometheus_fastapi_instrumentator.Instrumentator`
- `prometheus_instrument_params` - passed to `method Instrumentator(...).instrument`
- `prometheus_expose_params` - passed to `method Instrumentator(...).expose`.


## Opentelemetry

To bootstrap Opentelemetry, you must provide at least:

- `opentelemetry_endpoint`.

Additional parameters:

- `opentelemetry_service_name` - if provided, will be passed to the `Resource` instead of `service_name`.
- `opentelemetry_container_name` - will be passed to the `Resource`.
- `opentelemetry_endpoint` - will be passed to `OTLPSpanExporter` as endpoint. Under `opentelemetry_exporter_protocol="http"` this is a full URL (e.g. `http://collector:4318/v1/traces`).
- `opentelemetry_namespace` - will be passed to the `Resource`.
- `opentelemetry_exporter_protocol` - OTLP exporter transport: `"grpc"` (default, needs the `otl` extra) or `"http"` (needs the `otl-http` extra, no `grpcio` - installable on free-threaded Python).
- `opentelemetry_insecure` - whether the gRPC OTLP connection is insecure (gRPC only; for `http` the endpoint URL scheme carries security).
- `opentelemetry_instrumentors` - a list of extra instrumentors.
- `opentelemetry_log_traces` - traces will be logged to stdout.
- `opentelemetry_generate_health_check_spans` - generate spans for health check handlers if `True`.
- `opentelemetry_excluded_urls` - extra URLs excluded from tracing; the metrics path and (unless health-check spans are enabled) the health-check path are excluded automatically.

For FastStream you must provide additionally:

- `opentelemetry_middleware_cls`


## Pyroscope

Pyroscope integration uses `pyroscope-io` package under the hood. Install it with the `pyroscope` extra, e.g. `lite-bootstrap[fastapi-all,pyroscope]`.

To bootstrap Pyroscope, you must provide at least:

- `pyroscope_endpoint` - the Pyroscope server address (e.g. `http://pyroscope:4040`).

Additional parameters:

- `pyroscope_sample_rate` - CPU profiling sample rate in Hz (default: `100`).
- `pyroscope_tags` - key/value string pairs attached to all profiles.
- `pyroscope_additional_params` - additional params passed directly to `pyroscope.configure`.

When OpenTelemetry is also enabled, a `PyroscopeSpanProcessor` is automatically added to the tracer provider. It tags root spans with a `pyroscope.profile.id` attribute and sets Pyroscope thread tags so that traces and profiles can be linked in the Grafana UI.

## Structlog

Structlog is bootstrapped by default. To opt out, set `logging_enabled=False`.

Additional parameters:

- `logging_enabled` - whether to configure structlog (default: `True`).
- `logging_log_level`
- `logging_flush_level`
- `logging_buffer_capacity`
- `logging_extra_processors`
- `logging_unset_handlers`
- `logging_record_filters` - standard-library `logging.Filter` instances to attach to named loggers (see below).
- `logging_time_stamper` - a `structlog.processors.TimeStamper` instance controlling timestamp format (default: `TimeStamper(fmt="iso")`). Pass a custom instance to change the format or enable UTC:

```python
import structlog
from lite_bootstrap import FastAPIConfig

config = FastAPIConfig(
    logging_time_stamper=structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S", utc=True),
)
```

### Filtering standard-library log records

`logging_record_filters` maps a logger name to the filters to attach to it. Each filter is a plain
`logging.Filter`, run on every record that logger emits — before any handler renders it and before
Sentry turns it into an issue. A filter may leave the record alone, rewrite it, or return `False` to
drop it entirely.

Use it to demote a third-party failure you already handle, without touching that library's code:

```python
import logging

from lite_bootstrap import FreeBootstrapper, FreeConfig


class ExpectedThirdPartyFailureFilter(logging.Filter):
    """Demote the one failure this service already retries; leave every other error alone."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno == logging.ERROR and "RequestTimedOutError" in record.getMessage():
            record.levelno = logging.WARNING
            record.levelname = "WARNING"
        return True


bootstrapper = FreeBootstrapper(
    bootstrap_config=FreeConfig(
        logging_record_filters={
            "some_library.internal.worker": (ExpectedThirdPartyFailureFilter(),),
        },
    ),
)
```

Both `levelno` and `levelname` must be set: handlers and Sentry read them independently.

Two properties come from the standard library, not from `lite-bootstrap`:

- **The logger name must be exact.** A filter on `some_library` does *not* see records from
  `some_library.internal.worker`. `logging.Logger.handle` consults its own filters and then walks
  its ancestors' *handlers*, never their filters. Name every logger you want filtered.
- **`""` is the root logger**, and it too only sees records logged through the root logger itself —
  not records that propagate up to it from a named logger.

Teardown removes only the filters `lite-bootstrap` attached; anything your application or another
library put on the same logger stays.

### Structlog Litestar

When using Litestar, the `StructlogPlugin` is automatically registered, which enables `request.logger` inside route handlers:

```python
from litestar import Litestar, Request, get
from lite_bootstrap import LitestarConfig, LitestarBootstrapper


@get("/")
async def handler(request: Request) -> dict[str, str]:
    request.logger.info("handling request")
    return {"status": "ok"}
```

Additional parameters for Litestar's access-log middleware:

- `litestar_logging_middleware_enabled` - turn on request/response access logging (default: `False`).
- `litestar_logging_middleware_config` - a caller-supplied `LoggingMiddlewareConfig` that replaces the built-in defaults wholesale.

See [the Litestar integration guide](../integrations/litestar.md#logging) for what gets logged and why access logging defaults to off.

### Structlog FastStream

When using FastStream, the structlog logger is automatically injected into the broker so that all broker
service messages (e.g. "Received", "Processed") are routed through structlog.

The broker log level is controlled independently from the application log level:

- `faststream_log_level` - log level for FastStream broker service messages (default: `logging.WARNING`).

This allows you to suppress broker noise while keeping your application logs at a lower level:

```python
import logging
from lite_bootstrap import FastStreamConfig

config = FastStreamConfig(
    logging_log_level=logging.INFO,  # your application logs
    faststream_log_level=logging.WARNING,  # broker "Received"/"Processed" messages (default)
)
```

## CORS

To bootstrap CORS headers, you must provide `cors_allowed_origins` or `cors_allowed_origin_regex`.

Additional params:

- `cors_allowed_methods`
- `cors_allowed_headers`
- `cors_exposed_headers`
- `cors_allowed_credentials`
- `cors_max_age`

## Swagger

To bootstrap swagger, you have the following parameters:

- `swagger_static_path` - path for offline docs static
- `swagger_path`
- `swagger_offline_docs` - option to turn on offline docs.

For Litestar `swagger_path` is required to bootstrap swagger instrument.

## Health checks

To bootstrap Health checks, you must provide set `health_checks_enabled` to True.

Additional params:

- `health_checks_path`
- `health_checks_include_in_schema`

## Skipped instruments

When a bootstrapper is constructed, each registered instrument is checked twice:

1. **`is_configured(config)`** (classmethod, runs before instantiation) — returns False if the user's config indicates this instrument shouldn't run (e.g. `sentry_dsn` empty, `logging_enabled=False`, `pyroscope_endpoint` empty). When False, the instrument is **silently skipped** and recorded in `bootstrapper.skipped_instruments: list[tuple[type, str]]` — each entry is the instrument class plus its `not_ready_message`.

2. **`check_dependencies()`** — runs only if `is_configured()` returned True. If the instrument's optional package is missing, an `InstrumentDependencyMissingWarning` is emitted. This is a real "configured but dependency missing" deployment surprise.

After the loop, the bootstrapper emits one INFO-level summary log listing configured + skipped instruments. Default Python logging suppresses INFO; opt in via `logging.basicConfig(level=logging.INFO)`.

Filter the dep-missing warning the same way as any `UserWarning`:

```python
import warnings
from lite_bootstrap import InstrumentDependencyMissingWarning

warnings.filterwarnings("ignore", category=InstrumentDependencyMissingWarning)
```

`InstrumentSkippedWarning` is kept as the base class for forward-compatibility (additional skip categories may emerge); today, `InstrumentDependencyMissingWarning` is its only concrete subclass.

To inspect skipped instruments programmatically:

```python
bootstrapper = FastAPIBootstrapper(bootstrap_config=config)
for cls, reason in bootstrapper.skipped_instruments:
    print(f"{cls.__name__}: {reason}")
```

To get a human-readable view of the same information at any later point (e.g. for debugging from a REPL or a health endpoint), call `bootstrapper.build_summary()`. It returns the multi-line string that the INFO summary log emits — useful when log levels are filtered or when you want to render the bootstrapper state inline.
