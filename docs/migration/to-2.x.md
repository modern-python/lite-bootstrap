# Migration guide: upgrading to lite-bootstrap 2.x

This guide covers changes since 1.16.0. Update dependency constraints, then follow
the sections for your frameworks and instruments. Snippets are independent examples;
use your service's DSN, application, exporter, and identity.

## Dependency constraints

Update lockfiles and any direct pins to match these supported versions:

| Dependency | 2.x constraint | Applies to |
| --- | --- | --- |
| `sentry-sdk` | `>=2.70,<3` | Sentry extras |
| `opentelemetry-api`, `opentelemetry-sdk`, OTLP exporters | `>=1.42` | `otl` and `otl-http` extras |
| `opentelemetry-instrumentation` and framework instrumentation | `>=0.63b0` | OpenTelemetry extras |
| `litestar` | `>=2.22` | All Litestar extras |
| `fastmcp` | `>=4.0,<5` | All FastMCP extras |

Sentry 3 is unsupported. For FastMCP 3, follow the
[FastMCP 4 upgrade guide](https://github.com/PrefectHQ/fastmcp/blob/main/docs/getting-started/upgrading/from-fastmcp-3.mdx).
FastMCP access logs now include notifications and pre-handler failures, increasing
log volume. Sources:
[#359](https://github.com/modern-python/lite-bootstrap/pull/359),
[#368](https://github.com/modern-python/lite-bootstrap/pull/368),
[#371](https://github.com/modern-python/lite-bootstrap/pull/371),
[#374](https://github.com/modern-python/lite-bootstrap/pull/374), and
[#379](https://github.com/modern-python/lite-bootstrap/pull/379).

## Removed names and config fields

Replace aliases deprecated in 1.x in imports, attributes, constructor arguments,
and settings keys ([#367](https://github.com/modern-python/lite-bootstrap/pull/367)):

| Removed name | Replacement |
| --- | --- |
| `FreeBootstrapperConfig` (package root or `bootstrappers.free_bootstrapper`) | `FreeConfig` |
| `OpentelemetryConfig` (`instruments.opentelemetry_instrument`) | `OpenTelemetryConfig` |
| `IGNORED_STRUCTLOG_ATTRIBUTES` (`instruments.sentry_instrument`) | `STRUCTLOG_META_KEYS` from `instruments.logging_factory` |
| `AddressProtocol`, `RequestProtocol`, `ScopeType` (logging modules) | Define the structural types your application needs |
| `prometheus_instrumentator_params` (FastAPI/FastMCP) | `prometheus_instrumentator_additional_params` |
| `prometheus_instrument_params` (FastAPI/FastMCP) | `prometheus_instrument_additional_params` |
| `prometheus_expose_params` (FastAPI) | `prometheus_expose_additional_params` |
| `swagger_extra_params` (Litestar) | `swagger_additional_params` |
| `fastapi_logging_middleware_enabled` | `logging_access_log_enabled` |
| `litestar_logging_middleware_enabled` | `logging_access_log_enabled` |
| `fastmcp_logging_middleware_enabled` | `logging_access_log_enabled` |
| Custom instrument `not_ready_message` | `not_configured_reason` |
| Custom instrument `check_dependencies` | `dependencies_installed` |

Removed imports raise `ImportError`, attributes raise `AttributeError`, and
constructor keywords raise `TypeError`. `from_dict()` and `from_object()` ignore
unknown keys, so rename settings keys to avoid silently using defaults. Update both
custom instrument members: the old dependency method no longer prevents construction
when a package is missing.

For example, replace `FreeBootstrapperConfig(...)` with:

```python
from lite_bootstrap import FreeConfig

config = FreeConfig(logging_enabled=False)
```

### Missing-dependency warning category

Replace `InstrumentSkippedWarning` imports and filters with
`InstrumentDependencyMissingWarning`, now a direct subclass of `UserWarning`
([#427](https://github.com/modern-python/lite-bootstrap/pull/427)):

```python
import warnings

from lite_bootstrap import InstrumentDependencyMissingWarning

warnings.filterwarnings("error", category=InstrumentDependencyMissingWarning)
```

Unconfigured instruments skip silently; configured instruments with missing
dependencies warn. Without `prometheus_client`, the default metrics path also skips
silently, even an explicit `/metrics` on FastAPI, Litestar, or FastMCP. Custom paths
still warn. Install your framework's metrics extra if you expect a scrape route
([#428](https://github.com/modern-python/lite-bootstrap/pull/428)).

### Custom bootstrappers

Change `BaseBootstrapper[MyApp]` to `BaseBootstrapper[MyApp, MyConfig]`.
The old form raises `TypeError` at class definition
([#376](https://github.com/modern-python/lite-bootstrap/pull/376)):

```python
from lite_bootstrap import FreeConfig
from lite_bootstrap.bootstrappers.base import BaseBootstrapper


class MyBootstrapper(BaseBootstrapper[object, FreeConfig]):
    pass
```

## Service identity and debug mode

`service_debug=False` disables debug tracebacks on FastAPI apps created by
lite-bootstrap and on Litestar apps. Set `service_debug=True` for development.
Litestar also preserves `AppConfig(debug=True)`
([#369](https://github.com/modern-python/lite-bootstrap/pull/369)).

`service_name` and `service_version` now default to `None`
([#373](https://github.com/modern-python/lite-bootstrap/pull/373)):

- OpenTelemetry resolves an unset name from `OTEL_SERVICE_NAME`, then
  `service.name` in `OTEL_RESOURCE_ATTRIBUTES`, otherwise the SDK fallback
  `unknown_service` (with an executable suffix when available), instead of
  `micro-service`. An explicit `opentelemetry_service_name` still takes precedence
  over `service_name`.
- An unset version is omitted from the OpenTelemetry resource unless supplied by
  `OTEL_RESOURCE_ATTRIBUTES`.
- An explicit `service_version` becomes Sentry's release, overriding SDK discovery,
  including `SENTRY_RELEASE`. Use `sentry_additional_params["release"]` to override it.
- Code reading the config can receive `None`. Use `service_name_or_default` and
  `service_version_or_default` for the previous fallback values. Health responses
  and framework metadata continue to use these fallbacks.

Set explicit identity fields to retain the old telemetry resource values:

```python
from lite_bootstrap import FreeConfig

config = FreeConfig(service_name="micro-service", service_version="1.0.0")
```

## Logging

### Immediate output and root propagation

Delete `logging_buffer_capacity` and `logging_flush_level` from constructors and
settings. Structlog lines now appear immediately, in order with stdlib lines
([#378](https://github.com/modern-python/lite-bootstrap/pull/378)).

Remove uses of `MemoryLoggerFactory` and `LoggingInstrument.memory_logger_factory`.
Structlog uses the stdlib factory, propagates to root, and inherits root's level.
Stdlib records on structlog logger names and their children now render as JSON.
Litestar and FastStream loggers also propagate to root while bootstrapped
([#405](https://github.com/modern-python/lite-bootstrap/pull/405)).

Check parent and root handlers for duplicate output. Set named-logger levels
explicitly when they should differ from `logging_log_level`.

### Teardown preserves application logging

Teardown removes its own root handler, preserves other handlers, and restores the
previous root level. Close application handlers or set root to `WARNING` yourself
if needed. `logging_unset_handlers` removals remain permanent
([#415](https://github.com/modern-python/lite-bootstrap/pull/415)).

### Trace context in JSON logs

Treat JSON log `tracing` as optional. It contains `span_id` and `trace_id` inside a
recording OpenTelemetry span and is absent elsewhere, replacing the empty object
([#425](https://github.com/modern-python/lite-bootstrap/pull/425)).

## Sentry

### Data collection and request bodies

An explicit `data_collection` policy bypasses Sentry's general event scrubber;
collection denylists filter headers, cookies, query parameters, and frame locals.
Review custom scrubbing. User information and HTTP bodies default to off;
`send_default_pii=True` alone no longer enables them
([#359](https://github.com/modern-python/lite-bootstrap/pull/359)).

To collect user information or incoming bodies, override those policy entries:

```python
from lite_bootstrap import FastAPIConfig
from lite_bootstrap.instruments.sentry_instrument import DEFAULT_DATA_COLLECTION

config = FastAPIConfig(
    sentry_additional_params={
        "data_collection": {
            **DEFAULT_DATA_COLLECTION,
            "user_info": True,
            "http_bodies": ["incoming_request"],
        },
        "max_request_body_size": "small",
    },
)
```

Lean capture attaches bodies only after the handler reads them; FastAPI and
FastMCP require the complete body. Raw bodies become text. Body size limits apply
([#410](https://github.com/modern-python/lite-bootstrap/pull/410)). See
[Sentry data collection](../introduction/configuration.md#sentry-data-collection)
for the full default policy.

Structured log events and breadcrumbs are normalized and redacted before callbacks
run. Structlog events omit frame locals, and `skip_sentry` drops recognized records
before `before_send` or `before_breadcrumb` runs. This ordering also applies to
`sentry_additional_params["before_send"]`, which previously replaced built-in
processing. Update callbacks that relied on the original payload
([#408](https://github.com/modern-python/lite-bootstrap/pull/408)).
FastStream isolates message scopes. Set tags and breadcrumbs per message
([#409](https://github.com/modern-python/lite-bootstrap/pull/409)).

### Sessions and breadcrumbs

Session tracking defaults to off; HTTP crash-free session/user rates stop.
Log breadcrumbs start at `WARNING`, omitting INFO records. Restore the 1.x defaults:

```python
import logging

from lite_bootstrap import FreeConfig

config = FreeConfig(
    sentry_auto_session_tracking=True,
    sentry_logging_breadcrumb_level=logging.INFO,
)
```

Request sessions apply only to HTTP frameworks, not FastStream or Free
([#360](https://github.com/modern-python/lite-bootstrap/pull/360)).

### Lean request error capture

FastAPI, Litestar, and FastMCP use lean capture when tracing is unrequested and no
replaced framework integration is supplied. It creates no request transaction;
update code that reads one. Litestar no longer reports exceptions handled as 4xx.
FastAPI/FastMCP report escaping exceptions and handled exceptions with their own
integer 5xx `status_code`; a handler returning 503 alone does not qualify.

Set `sentry_lean_error_capture=False` to keep Sentry's framework integrations.
With the default `None`, any tracing option, even a zero sample rate, selects them.
Avoid initializing them earlier: lean capture cannot undo global
patches and warns about possible duplicate events
([#361](https://github.com/modern-python/lite-bootstrap/pull/361),
[#362](https://github.com/modern-python/lite-bootstrap/pull/362)).

### Auto-enabling integrations

Auto-enabling integrations default to off without tracing (on HTTP frameworks,
while lean capture is on). SQL, Redis, httpx, aiohttp, and FastMCP's `MCPIntegration`
may stop adding breadcrumbs and event context. Restore them with `sentry_auto_enabling_integrations=True`
or select integrations through `sentry_integrations`
([#363](https://github.com/modern-python/lite-bootstrap/pull/363)).

## OpenTelemetry

### Fewer ASGI and health-check spans

FastAPI, Litestar, and FastMCP omit per-message `receive` and `send` spans. Set
`opentelemetry_exclude_spans=[]` to restore them
([#364](https://github.com/modern-python/lite-bootstrap/pull/364)).

`opentelemetry_generate_health_check_spans` defaults to `False`. Set it to `True`
to include health checks in traces and, where OpenTelemetry instruments HTTP
requests, in HTTP metrics. On FastStream, it controls only the health-check span
([#366](https://github.com/modern-python/lite-bootstrap/pull/366)).

### OTLP transport security

`opentelemetry_insecure=None` lets OTLP insecure environment variables apply.
Without an override, schemeless gRPC endpoints such as `collector:4317` use TLS.
For plaintext, use `http://` or `opentelemetry_insecure=True`. Unix sockets need
explicit `True`; `https://` keeps TLS. Check trace and metric endpoints
([#372](https://github.com/modern-python/lite-bootstrap/pull/372)).

```python
from lite_bootstrap import FreeConfig

config = FreeConfig(
    opentelemetry_endpoint="http://localhost:4317",
    opentelemetry_metrics_endpoint="http://localhost:4317",
)
```

### Metrics-only tracing and external providers

Without a configured span processor, bootstrap reuses a preinstalled tracer
provider or gives instrumentors a no-op provider. The same rule applies if the
trace exporter is missing and no other processor is configured. The warning still
appears. JSON logs include `tracing` only inside a recording span.

Install your SDK provider and processors before bootstrap. A provider installed
later cannot activate instrumentors bound to a no-op provider. Your application
owns provider shutdown and must uninstrument any libraries it instrumented before
bootstrap
([#430](https://github.com/modern-python/lite-bootstrap/pull/430),
[#444](https://github.com/modern-python/lite-bootstrap/pull/444)):

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

from lite_bootstrap import FreeBootstrapper, FreeConfig

provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
trace.set_tracer_provider(provider)
bootstrapper = FreeBootstrapper(
    FreeConfig(logging_enabled=False, opentelemetry_metrics_endpoint="http://localhost:4317"),
)
bootstrapper.bootstrap()
try:
    with trace.get_tracer(__name__).start_as_current_span("work"):
        pass
finally:
    bootstrapper.teardown()
    provider.shutdown()
```

This example needs the `otl` extra and a local collector for metric export.
Configurations with a working trace exporter, stdout span logging, or Pyroscope
span correlation continue to use an SDK tracer provider.

### URL exclusion validation

FastAPI and FastMCP raise `ConfigurationError` for commas in
`opentelemetry_excluded_urls`, which their integrations join with commas. Split
alternatives into entries, use `\x2c` for a literal comma, and rewrite bounded
repetitions such as `a{1,3}` as `aa?a?`. Litestar accepts commas
([#417](https://github.com/modern-python/lite-bootstrap/pull/417)).

## CORS methods on FastAPI and Litestar

`cors_allowed_methods` defaults to `["*"]`. Configuring origins without a method
list now allows preflight for all standard HTTP methods, including POST. Set an
explicit list such as `["GET", "POST"]` to restrict methods.
`cors_allowed_headers` remains `[]`; both frameworks permit their built-in CORS
headers, including `Content-Type`. Add `Authorization` explicitly when needed
([#423](https://github.com/modern-python/lite-bootstrap/pull/423)).

## Prometheus

### FastMCP custom registry

When `prometheus_instrumentator_additional_params["registry"]` supplies a custom
registry, FastMCP's Prometheus HTTP and tool metrics use that registry. The
metrics endpoint exposes its collectors. Register any application collectors you
want to expose in that same registry. FastMCP uses the global registry by default
([#451](https://github.com/modern-python/lite-bootstrap/issues/451)).

### Unknown FastMCP tools

Calls to unresolved tool names no longer create `fastmcp_tool_calls_total` or
`fastmcp_tool_call_duration_seconds` series. These calls still return errors, but
are omitted from tool metrics to bound retained series. Calls to resolved tools
still count successes and failures. Hashed app-tool aliases now share the label
`<hash>_<resolved tool name>`. Update dashboard and alert selectors that match
the raw requested name used in 1.16.0
([#433](https://github.com/modern-python/lite-bootstrap/issues/433)).

### HTTP metrics alongside OpenTelemetry

On FastAPI, Litestar, and FastMCP, configuring OpenTelemetry HTTP metrics suppresses
the additional Prometheus HTTP series by default. Scrapes can lose series such as
`http_requests_total` or `litestar_requests_total`. Set
`prometheus_http_metrics_enabled=True` to keep both. Other collectors remain
available ([#365](https://github.com/modern-python/lite-bootstrap/pull/365)).

### Infrastructure requests

Health requests and scrapes are excluded from Prometheus HTTP request metrics on
FastAPI, Litestar, and FastMCP. User exclusions still apply. Review dashboards and
alert thresholds: totals can fall and latency percentiles can change. Enabling
`prometheus_http_metrics_enabled` does not restore infrastructure requests
([#424](https://github.com/modern-python/lite-bootstrap/pull/424)).

### FastStream opt-in and registry

FastStream's metrics path defaults to `""`, disabling the scrape route and broker
middleware even with `prometheus_middleware_cls` set. Supply a path:

```python
from lite_bootstrap import FastStreamConfig

config = FastStreamConfig(prometheus_metrics_path="/metrics")
```

Keep your application and middleware settings. Scrapes use the default registry,
including process/platform and other global collectors. Check for duplicate
registrations. For isolation, pass your own `CollectorRegistry` through
`prometheus_collector_registry`
([#375](https://github.com/modern-python/lite-bootstrap/pull/375)).

## Health and metrics routes

Unhealthy health checks return **503** instead of **500**. Update probes and
load-balancer rules that matched exactly 500; match 503 or any 5xx
([#370](https://github.com/modern-python/lite-bootstrap/pull/370)).

Invalid non-empty health or metrics paths raise `ConfigurationError` at config
construction, even for skipped instruments. Use a leading slash and non-empty
segments of letters, digits, `.`, `_`, or `-`; a trailing slash is allowed.
`/` works only for health checks. `""` disables either route
([#419](https://github.com/modern-python/lite-bootstrap/pull/419)):

```python
from lite_bootstrap import FastAPIConfig

config = FastAPIConfig(health_checks_path="/health", prometheus_metrics_path="/metrics")
disabled = FastAPIConfig(health_checks_path="", prometheus_metrics_path="")
```

FastStream serves `/health` and `/health/`, and `/metrics` and `/metrics/`, directly.
Existing probes keep working. Check for custom routes using the alternate spelling
([#420](https://github.com/modern-python/lite-bootstrap/pull/420)).

## FastStream middleware protocols

`FastStreamTelemetryMiddlewareProtocol` and `FastStreamPrometheusMiddlewareProtocol`
are now for static typing. Runtime checks with `isinstance()` or `issubclass()`
raise `TypeError`. If you need runtime validation, define your own
`@runtime_checkable` protocol or check the required methods directly
([#427](https://github.com/modern-python/lite-bootstrap/pull/427)).

## Framework lifecycle and offline docs

FastAPI and FastMCP teardown runs after user lifespan shutdown, preserving shutdown
spans and logs. Keep exporters open until that work finishes
([#412](https://github.com/modern-python/lite-bootstrap/pull/412),
[#413](https://github.com/modern-python/lite-bootstrap/pull/413)).

FastStream's ASGI lifespan runs teardown after broker shutdown and user lifespan
cleanup, including when startup or shutdown fails. If you drive FastStream with
`start()` and `stop()` or use `async with application`, explicitly call
`bootstrapper.teardown()` in an outer `finally` block
([#434](https://github.com/modern-python/lite-bootstrap/issues/434)).

Failed bootstrap rolls back successfully started instruments and cannot be reused. Retry with
a fresh application and bootstrapper ([#406](https://github.com/modern-python/lite-bootstrap/pull/406)).

FastAPI offline docs respect `docs_url=None` and `redoc_url=None` independently.
To serve a disabled route again, give it a URL ([#418](https://github.com/modern-python/lite-bootstrap/pull/418)):

```python
from fastapi import FastAPI

from lite_bootstrap import FastAPIConfig

config = FastAPIConfig(application=FastAPI(docs_url="/docs", redoc_url=None))
```
