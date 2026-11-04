# Migration guide for lite-bootstrap 2.x

## CORS methods on FastAPI and Litestar

In 2.x, `cors_allowed_methods` defaults to `["*"]`. If you configure allowed
origins and omit the method list, preflight requests can now succeed for all
standard HTTP methods, including POST.

Set `cors_allowed_methods` explicitly to restrict cross-origin requests to the
methods your application supports, such as `["GET", "POST"]`.

`cors_allowed_headers` defaults to `[]`. Both frameworks allow their built-in
CORS headers, including `Content-Type`. Add headers such as `Authorization`
explicitly if your application needs them.

## Prometheus HTTP metrics on FastAPI, FastMCP, and Litestar

Health checks and metrics scrapes are excluded from Prometheus HTTP request
metrics. Existing user-defined exclusions still apply. Dashboards and alerts
that previously included these requests may show lower request totals and
different latency percentiles. Review thresholds that were based on the old
traffic mix.

## Trace context in JSON logs

JSON log lines include `tracing` only when emitted inside a recording
OpenTelemetry span. The object contains `span_id` and `trace_id`.
Update log parsers to treat `tracing` as optional.

## Missing-dependency warning category

`InstrumentSkippedWarning` has been removed. Importing it from `lite_bootstrap`
now raises `ImportError`. Replace imports and warning filters with
`InstrumentDependencyMissingWarning`, which now derives directly from `UserWarning`:

```python
import warnings

from lite_bootstrap import InstrumentDependencyMissingWarning

warnings.filterwarnings("error", category=InstrumentDependencyMissingWarning)
```

Unconfigured instruments continue to be skipped silently. A configured instrument
with a missing optional dependency emits `InstrumentDependencyMissingWarning`.

## Metrics-only OpenTelemetry tracing

Metrics-only configuration no longer installs an SDK `TracerProvider` or records
unexported framework spans. The same applies when a trace endpoint's exporter is
missing and no other span processor is configured; the missing-exporter warning remains.
JSON logs from these requests omit `tracing` unless external tracing records a span.

If you add span processors yourself, create an SDK tracer provider, attach your
processors, and install it with `opentelemetry.trace.set_tracer_provider()` before
bootstrap. lite-bootstrap preserves that external provider and leaves its shutdown
to your application. Installing a provider after bootstrap does not activate tracing
for framework and custom instrumentors already given a no-op provider.

Configurations with a working trace exporter, stdout span logging, or Pyroscope
span correlation continue to use an SDK tracer provider.
