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
- `sentry_auto_session_tracking` - whether every request opens and closes a Sentry release-health `Session` (default: `True`), measured at ~7.7 µs per request. Set it to `False` if you do not use Sentry release health.
- `sentry_integrations` - list of integrations to enable
- `sentry_logging_breadcrumb_level` - the minimum standard-library log level recorded as a breadcrumb (default: `logging.INFO`). Passed as `LoggingIntegration(level=...)`; see below.
- `sentry_tags` - key/value string pairs that are both indexed and searchable
- `sentry_additional_params` - additional params, which will be passed to `sentry_sdk.init`, overriding any of the above that map to the same keyword
- `sentry_default_integrations` - whether to use sentry's default integrations (default: `True`)
- `sentry_before_send` - optional callback chained after the built-in structlog enricher, passed to `sentry_sdk.init(before_send=...)`

Read more about sentry_sdk params [here](https://docs.sentry.io/platforms/python/configuration/options/).

Sentry is the second most expensive instrument in the stack, and the settings that actually move
the number are not the ones most people reach for. See [Performance](performance.md).

### Sentry logging integration

Unless `sentry_integrations` already contains a `LoggingIntegration`, lite-bootstrap appends one built
as `LoggingIntegration(level=sentry_logging_breadcrumb_level, sentry_logs_level=None)`. Its event
handler keeps the sentry-sdk default (`ERROR`), so the only departure from sentry-sdk's own default
integration is `sentry_logs_level`.

Turning `sentry_logs_level` off is free. lite-bootstrap never sets `enable_logs`, so Sentry Logs is
off, but `SentryLogsHandler.emit` formats the record *before* it checks whether logs are enabled
([getsentry/sentry-python#7402](https://github.com/getsentry/sentry-python/issues/7402)) - it formats
every `INFO`+ record and discards the result. Dropping breadcrumbs as well, with
`sentry_logging_breadcrumb_level=None`, saves more but costs you log breadcrumbs on error events, so
it stays on by default. Both are measured on the [performance page](performance.md#where-the-time-goes).

Two ways to opt out of the appended integration: supply your own `LoggingIntegration` in
`sentry_integrations`, which lite-bootstrap leaves untouched, or set
`sentry_default_integrations=False`, which suppresses it along with every other default integration.
Under either, `sentry_logging_breadcrumb_level` is ignored and lite-bootstrap warns.


## Prometheus

Prometheus is the cheapest of the three non-logging instruments; see [Performance](performance.md).

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

To bootstrap Prometheus for FastStream, you must provide at least one of:

- `prometheus_middleware_cls` - the broker metrics middleware, e.g.
  `faststream.redis.prometheus.RedisPrometheusMiddleware`. It is constructed with the instrument's
  registry and added to the broker, when the application has one.
- `prometheus_collector_registry` - a `prometheus_client.CollectorRegistry` of your own, used in
  place of the fresh one the instrument would otherwise build.

With neither, nothing would populate the registry, so the metrics endpoint is not mounted and the
instrument is skipped. Unlike the other frameworks, FastStream serves a private registry rather than
`prometheus_client.REGISTRY`, so an endpoint with no middleware and no injected registry would have
nothing to report.

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
- `opentelemetry_sampler` - an `opentelemetry.sdk.trace.sampling.Sampler` deciding which traces are recorded. Unset, the SDK's own default applies: `parentbased_always_on`, which records every trace that is not the child of a non-recording remote parent, unless `OTEL_TRACES_SAMPLER` / `OTEL_TRACES_SAMPLER_ARG` say otherwise.
- `opentelemetry_generate_health_check_spans` - generate spans for health check handlers if `True`.
- `opentelemetry_excluded_urls` - extra URLs excluded from tracing; the metrics path and (unless health-check spans are enabled) the health-check path are excluded automatically.

Sampling is the cheapest way to cut what tracing costs: on a benchmark endpoint returning a constant,
`ParentBased(TraceIdRatioBased(0.01))` saved ~55 µs per request against the always-on default.
OpenTelemetry is the most expensive instrument in the stack; see [Performance](performance.md).

```python
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

config = FastAPIConfig(
    service_name="my-service",
    opentelemetry_endpoint="otl",
    opentelemetry_sampler=ParentBased(TraceIdRatioBased(0.01)),
)
```

For FastAPI there is additionally:

- `opentelemetry_exclude_spans` - drops the ASGI `receive` and/or `send` spans, leaving only the
  server span. Empty by default, which records all three. `["receive", "send"]` is worth ~34 µs per
  request on the benchmark endpoint, at the cost of two thirds of the spans disappearing from your
  trace view.

For FastStream there is additionally:

- `opentelemetry_middleware_cls` - the broker telemetry middleware, e.g.
  `faststream.redis.opentelemetry.RedisTelemetryMiddleware`. You must provide it to trace broker
  messages. Without it the rest of the configuration above still applies: the exporter is built, the
  health-check span is recorded unless `opentelemetry_generate_health_check_spans` is False, and any
  `opentelemetry_instrumentors` are applied.


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

Configuring it costs almost nothing; the cost arrives per log record, and most of it is Sentry's.
See [Performance](performance.md).

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

`logging_record_filters` attaches `logging.Filter` instances to loggers by name. A filter sees every
record its logger emits, before any handler renders it, and may rewrite the record or return `False`
to drop it — useful for demoting a third-party error you already handle:

```python
import logging

from lite_bootstrap import FreeBootstrapper, FreeConfig


class ExpectedFailureFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno == logging.ERROR and "expected failure" in record.getMessage():
            record.levelno = logging.WARNING
            record.levelname = "WARNING"
        return True


bootstrapper = FreeBootstrapper(
    bootstrap_config=FreeConfig(
        logging_record_filters={"some_library.worker": (ExpectedFailureFilter(),)},
    ),
)
```

- **Set both `levelno` and `levelname`** when changing a level: handlers read them independently.
- **The logger name is exact.** A filter on `some_library` never sees `some_library.worker`, and
  `""` is the root logger, matching only records logged through root itself. That is standard
  `logging` behaviour: a logger consults its own filters, then its ancestors' *handlers*.
- **Teardown removes only what it attached**, leaving filters your application put on the same
  logger in place.

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

### Structlog FastAPI

FastAPI ships no access log of its own, so lite-bootstrap provides one. It is **off by default**:

- `fastapi_logging_middleware_enabled` - turn on the structured access log (default: `False`).

See [the FastAPI integration guide](../integrations/fastapi.md#logging) for what gets logged and why
it defaults to off.

### Structlog FastMCP

The per-MCP-message access log is **off by default**:

- `fastmcp_logging_middleware_enabled` - turn on the access log (default: `False`).
- `logging_turn_off_middleware` - superseded by the field above and warns when set. `False` turns the
  middleware on, `True` leaves it off, and if both are set the field above wins.

See [the FastMCP integration guide](../integrations/fastmcp.md#logging) for what gets logged.

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

1. **`is_configured(config)`** (classmethod, runs before instantiation) — returns False if the user's config indicates this instrument shouldn't run (e.g. `sentry_dsn` empty, `logging_enabled=False`, `pyroscope_endpoint` empty). When False, the instrument is **silently skipped** and recorded in `bootstrapper.skipped_instruments: list[tuple[type, str]]` — each entry is the instrument class plus its `not_configured_reason`.

2. **`dependencies_installed()`** — runs only if `is_configured()` returned True. If the instrument's optional package is missing, an `InstrumentDependencyMissingWarning` is emitted. This is a real "configured but dependency missing" deployment surprise.

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
