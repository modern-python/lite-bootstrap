# Migration guide: upgrading to lite-bootstrap 2.x

This guide covers changes since 1.16.0. Upgrade your dependency constraints first,
then review the sections for the instruments and frameworks your service uses.
The [2.0.0 release notes](https://github.com/modern-python/lite-bootstrap/releases/tag/2.0.0)
provide the release checklist. Configuration snippets below are independent examples;
use your own DSN, application, exporter, and service identity where applicable.

## Dependency constraints

Update lockfiles and any direct pins to match these supported versions:

| Dependency | 2.x constraint | Applies to |
| --- | --- | --- |
| `sentry-sdk` | `>=2.70,<3` | Sentry extras |
| `opentelemetry-api`, `opentelemetry-sdk`, OTLP exporters | `>=1.42` | `otl` and `otl-http` extras |
| `opentelemetry-instrumentation` and framework instrumentation | `>=0.63b0` | OpenTelemetry extras |
| `litestar` | `>=2.22` | All Litestar extras |
| `fastmcp` | `>=4.0,<5` | All FastMCP extras |

Sentry 3 is not supported. FastMCP 3 pins must move to 4; see its
[upgrade guide](https://github.com/PrefectHQ/fastmcp/blob/main/docs/getting-started/upgrading/from-fastmcp-3.mdx)
for changes in FastMCP itself. With access logging configured, notifications and
pre-handler failures now produce records too; review log-volume assumptions.
These constraints come from
[#359](https://github.com/modern-python/lite-bootstrap/pull/359),
[#368](https://github.com/modern-python/lite-bootstrap/pull/368),
[#371](https://github.com/modern-python/lite-bootstrap/pull/371),
[#374](https://github.com/modern-python/lite-bootstrap/pull/374), and
[#379](https://github.com/modern-python/lite-bootstrap/pull/379).

## Removed names and config fields

Aliases deprecated in 1.x have been removed
([#367](https://github.com/modern-python/lite-bootstrap/pull/367)). Update imports,
attribute access, config constructor arguments, and keys in external settings sources:

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

Removed imports fail with `ImportError`; removed attributes fail with `AttributeError`.
Removed constructor keywords fail with `TypeError`. `from_dict()` and `from_object()`
still ignore unknown keys, so old settings keys can silently fall back to defaults.
Rename those keys before upgrading. Custom instruments using the old dependency
method can be instantiated despite a missing package; update both class members.

For example, replace `FreeBootstrapperConfig(...)` with:

```python
from lite_bootstrap import FreeConfig

config = FreeConfig(logging_enabled=False)
```

### Missing-dependency warning category

`InstrumentSkippedWarning` has also been removed
([#427](https://github.com/modern-python/lite-bootstrap/pull/427)). Replace imports
and warning filters with `InstrumentDependencyMissingWarning`, which derives directly
from `UserWarning`:

```python
import warnings

from lite_bootstrap import InstrumentDependencyMissingWarning

warnings.filterwarnings("error", category=InstrumentDependencyMissingWarning)
```

Unconfigured instruments are skipped silently. A configured instrument with a missing
optional dependency warns. With `prometheus_client` missing, the default metrics path
now skips silently too, including an explicitly supplied `/metrics` on FastAPI,
Litestar, or FastMCP. A custom path still warns; install the framework's metrics extra
if you expect a scrape route
([#428](https://github.com/modern-python/lite-bootstrap/pull/428)).

### Custom bootstrappers

`BaseBootstrapper` now takes the application and config types. Change
`BaseBootstrapper[MyApp]` to `BaseBootstrapper[MyApp, MyConfig]`; the old form raises
`TypeError` when the class is defined
([#376](https://github.com/modern-python/lite-bootstrap/pull/376)). For example:

```python
from lite_bootstrap import FreeConfig
from lite_bootstrap.bootstrappers.base import BaseBootstrapper


class MyBootstrapper(BaseBootstrapper[object, FreeConfig]):
    pass
```

## Service identity and debug mode

`service_debug` defaults to `False`. FastAPI apps created by lite-bootstrap and
Litestar apps no longer show debug tracebacks unless explicitly requested. Set
`service_debug=True` for development; Litestar also preserves an explicit
`AppConfig(debug=True)`
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

Review Sentry release grouping when setting a version explicitly.

## Logging

### Immediate output and root propagation

`logging_buffer_capacity` and `logging_flush_level` were removed. Delete those
constructor arguments and settings keys. Structlog lines are written immediately,
in order with stdlib lines, rather than waiting for a buffer flush
([#378](https://github.com/modern-python/lite-bootstrap/pull/378)).

`MemoryLoggerFactory` and `LoggingInstrument.memory_logger_factory` were removed.
Structlog uses the standard-library logger factory and propagates to root. Loggers
used by structlog inherit root's level instead of receiving their own. Stdlib records
on those names and their children are now JSON lines. Litestar and FastStream loggers
also propagate to root while bootstrapped
([#405](https://github.com/modern-python/lite-bootstrap/pull/405)).

Remove code inspecting the old factory or per-logger handlers. Review your parent
and root handlers for duplicate output, and set explicit named-logger levels if you
need them to differ from `logging_log_level`.

### Teardown preserves application logging

Logging teardown now removes only its own root handler and restores the root level
from before bootstrap. Other root handlers survive. If your application relied on
teardown to close its handlers or set root to `WARNING`, do that explicitly.
Removals requested through `logging_unset_handlers` remain permanent
([#415](https://github.com/modern-python/lite-bootstrap/pull/415)).

### Trace context in JSON logs

JSON log lines include `tracing` only inside a recording OpenTelemetry span; the
object contains `span_id` and `trace_id`. Outside one, the key is absent instead of
an empty object. Update log parsers to treat `tracing` as optional
([#425](https://github.com/modern-python/lite-bootstrap/pull/425)).

## Sentry

### Data collection and request bodies

lite-bootstrap passes an explicit `data_collection` policy. Sentry's general event
scrubber is bypassed by the SDK for that policy; headers, cookies, query parameters,
and frame locals instead use collection denylists. `send_default_pii=True` alone no
longer opts into collection. User information and HTTP bodies are off by default
([#359](https://github.com/modern-python/lite-bootstrap/pull/359)).

Review any custom scrubbing and opt-ins. To collect user information or incoming
request bodies, replace the relevant policy entries while retaining the others:

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

Enable only the data your service intends to collect. Lean capture attaches a body
only after the handler reads it; FastAPI and FastMCP require the complete body.
Raw bodies are text rather than a raw-data annotation. Request body size policy is
also enforced by lean capture
([#410](https://github.com/modern-python/lite-bootstrap/pull/410)). See
[Sentry data collection](../introduction/configuration.md#sentry-data-collection)
for the full default policy.

Structured log events and breadcrumbs are now normalized and redacted before user
callbacks. Recognized structlog events omit frame locals, which can retain the
original unredacted line. Update callbacks that relied on those locals or raw JSON
messages ([#408](https://github.com/modern-python/lite-bootstrap/pull/408)).
FastStream message scopes are isolated: set tags and breadcrumbs for each message
instead of relying on context left by a previous one
([#409](https://github.com/modern-python/lite-bootstrap/pull/409)).

### Sessions and breadcrumbs

Release-health session tracking defaults to off, and logging breadcrumbs start at
`WARNING` instead of `INFO`. HTTP crash-free session/user rates stop and INFO log
breadcrumbs disappear. To restore both defaults from 1.x:

```python
import logging

from lite_bootstrap import FreeConfig

config = FreeConfig(
    sentry_auto_session_tracking=True,
    sentry_logging_breadcrumb_level=logging.INFO,
)
```

Only HTTP frameworks opened request sessions; FastStream and Free do not gain
request sessions from this option
([#360](https://github.com/modern-python/lite-bootstrap/pull/360)).

### Lean request error capture

FastAPI, Litestar, and FastMCP now use lean error capture when tracing is not
requested and no replaced framework integration is supplied. Request transactions
are no longer created, so code reading the current transaction must change.
Litestar exceptions handled as 4xx are no longer reported. FastAPI/FastMCP report
escaping exceptions and handled exceptions whose own integer `status_code` is 5xx;
a handler returning 503 alone does not make its exception reportable.

Set `sentry_lean_error_capture=False` to retain Sentry's framework integrations.
Setting a tracing option, including an explicit sample rate of zero, selects the
integration path under the default `None` policy. Avoid initializing those framework
integrations earlier in the same process: lean capture cannot undo their global
patches and warns about possible duplicate events
([#361](https://github.com/modern-python/lite-bootstrap/pull/361),
[#362](https://github.com/modern-python/lite-bootstrap/pull/362)).

### Auto-enabling integrations

Auto-enabling integrations default to off while tracing is off (for HTTP frameworks,
while lean capture is on). SQL, Redis, httpx, aiohttp, and FastMCP's `MCPIntegration`
may therefore stop contributing breadcrumbs and event context. Set
`sentry_auto_enabling_integrations=True` to restore them, or list only the desired
integrations in `sentry_integrations`
([#363](https://github.com/modern-python/lite-bootstrap/pull/363)).

## OpenTelemetry

### Fewer ASGI and health-check spans

FastAPI, Litestar, and FastMCP omit per-message `receive` and `send` spans. Set
`opentelemetry_exclude_spans=[]` to restore them
([#364](https://github.com/modern-python/lite-bootstrap/pull/364)).

`opentelemetry_generate_health_check_spans` defaults to `False`. Health requests
are omitted from traces and OpenTelemetry HTTP metrics. Set it to `True` to observe
probe latency and restore those metrics
([#366](https://github.com/modern-python/lite-bootstrap/pull/366)).

### OTLP transport security

`opentelemetry_insecure` defaults to `None`, allowing OTLP insecure environment
variables to take effect. Without an override, schemeless gRPC endpoints such as
`collector:4317` now use TLS. For a plaintext collector, use an `http://` endpoint
or explicitly set `opentelemetry_insecure=True`. Unix sockets also need an explicit
`True`; `https://` retains TLS. Check both trace and metric endpoints
([#372](https://github.com/modern-python/lite-bootstrap/pull/372)).

```python
from lite_bootstrap import FreeConfig

config = FreeConfig(
    opentelemetry_endpoint="http://localhost:4317",
    opentelemetry_metrics_endpoint="http://localhost:4317",
)
```

### Metrics-only tracing and external providers

Metrics-only configuration no longer installs an SDK `TracerProvider` or records
unexported framework spans. The same applies when a trace exporter is missing and
no other span processor is configured; the missing-exporter warning remains. JSON
logs from these requests omit `tracing` unless external tracing records a span.

If you add span processors yourself, create and install an SDK provider before
bootstrap. lite-bootstrap preserves that provider and leaves its shutdown to your
application. Installing one later does not activate framework or custom instrumentors
already given a no-op provider
([#430](https://github.com/modern-python/lite-bootstrap/pull/430)):

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

FastAPI and FastMCP reject commas in `opentelemetry_excluded_urls` patterns with
`ConfigurationError`, because their integrations join patterns with commas.
Split alternatives into separate entries. For a literal comma use `\x2c`; for a
bounded repetition such as `a{1,3}` rewrite it without a comma, such as `aa?a?`.
Litestar accepts comma-containing patterns
([#417](https://github.com/modern-python/lite-bootstrap/pull/417)).

## CORS methods on FastAPI and Litestar

`cors_allowed_methods` defaults to `["*"]`. Configuring origins without a method
list now allows preflight for all standard HTTP methods, including POST. Set an
explicit list such as `["GET", "POST"]` to restrict methods.
`cors_allowed_headers` remains `[]`; both frameworks permit their built-in CORS
headers, including `Content-Type`. Add `Authorization` explicitly when needed
([#423](https://github.com/modern-python/lite-bootstrap/pull/423)).

## Prometheus

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

`FastStreamConfig.prometheus_metrics_path` defaults to `""`. Supplying only
`prometheus_middleware_cls` no longer installs the broker middleware or mounts a
scrape route. Set the path explicitly:

```python
from lite_bootstrap import FastStreamConfig

config = FastStreamConfig(prometheus_metrics_path="/metrics")
```

Keep your existing application and middleware class settings. Scrapes now use the
default registry, so they include process/platform collectors and other globally
registered metrics alongside broker metrics. Review duplicate collector registrations
and any assumptions about an isolated registry. Set
`prometheus_collector_registry` to your own `CollectorRegistry` for isolation
([#375](https://github.com/modern-python/lite-bootstrap/pull/375)).

## Health and metrics routes

Unhealthy health checks return **503** instead of **500**. Update probes and
load-balancer rules that matched exactly 500; match 503 or any 5xx
([#370](https://github.com/modern-python/lite-bootstrap/pull/370)).

Invalid non-empty `health_checks_path` and `prometheus_metrics_path` now raise
`ConfigurationError` during config construction, even when the instrument would
otherwise be skipped. Paths need a leading slash and non-empty segments using
letters, digits, `.`, `_`, or `-`; a trailing slash is allowed. `/` is supported
only for health checks. Use `""` to disable either route
([#419](https://github.com/modern-python/lite-bootstrap/pull/419)):

```python
from lite_bootstrap import FastAPIConfig

config = FastAPIConfig(health_checks_path="/health", prometheus_metrics_path="/metrics")
disabled = FastAPIConfig(health_checks_path="", prometheus_metrics_path="")
```

FastStream now serves both slash spellings directly, such as `/health` and
`/health/`, or `/metrics` and `/metrics/`. Existing probes work without changes;
review custom routes that use the alternate spelling for another purpose
([#420](https://github.com/modern-python/lite-bootstrap/pull/420)).

## Framework lifecycle and offline docs

FastAPI and FastMCP teardown now runs after user lifespan shutdown. Shutdown spans
and logs can still be exported. Move any manual observability shutdown out of the
user lifespan if it closes exporters before that work finishes
([#412](https://github.com/modern-python/lite-bootstrap/pull/412),
[#413](https://github.com/modern-python/lite-bootstrap/pull/413)).

A failed bootstrap rolls back successfully started instruments and is terminal.
Create a fresh application and bootstrapper to retry; do not reuse the failed
instance ([#406](https://github.com/modern-python/lite-bootstrap/pull/406)).

FastAPI offline docs now respect `docs_url=None` and `redoc_url=None` independently.
If you relied on offline mode recreating a disabled route, give that route a URL
explicitly ([#418](https://github.com/modern-python/lite-bootstrap/pull/418)):

```python
from fastapi import FastAPI

from lite_bootstrap import FastAPIConfig

config = FastAPIConfig(application=FastAPI(docs_url="/docs", redoc_url=None))
```
