# Instruments

An instrument is one observability or middleware concern (logging, tracing,
metrics, …). Each lives in its own file under `lite_bootstrap/instruments/`.
A bootstrapper owns a list of instrument instances and drives their lifecycle.

## BaseInstrument

`BaseInstrument[ConfigT]` (`lite_bootstrap/instruments/base.py`) is a generic,
**non-frozen** `@dataclasses.dataclass(kw_only=True, slots=True)` holding a
single `bootstrap_config: ConfigT`. Subclasses implement:

- `bootstrap()` / `teardown()` — lifecycle hooks, called in order / reverse by
  the bootstrapper.
- `is_configured(cls, bootstrap_config) -> bool` (classmethod) — return False
  when the user's config means this instrument should not run. Default: always
  True. Drives the silent-skip path.
- `check_dependencies() -> bool` (staticmethod) — return False when the
  optional package is absent. Default: always True.
- class attributes `not_ready_message` and `missing_dependency_message` —
  human-readable reasons surfaced in skip reporting and warnings.

## Instrument catalog

One file per instrument:

- `logging_instrument.py` — structlog setup (`LoggingInstrument`), skipped when
  `logging_enabled=False`.
- `opentelemetry_instrument.py` — OTel tracer provider + span export.
- `sentry_instrument.py` — Sentry SDK init, skipped when `sentry_dsn` empty.
- `prometheus_instrument.py` — Prometheus metrics; framework variants wrap it.
- `pyroscope_instrument.py` — continuous profiling, skipped when
  `pyroscope_endpoint` empty.
- `cors_instrument.py` — CORS headers, requires an origins/regex setting.
- `swagger_instrument.py` — Swagger / offline docs.
- `healthchecks_instrument.py` — health-check route, gated by
  `health_checks_enabled`.

`logging_factory.py` was split out of `logging_instrument.py` to keep each file
scoped to one job. It holds `MemoryLoggerFactory`, `_MemoryLoggerFactoryConfig`,
the orjson structlog serializer, and the ASGI `AddressProtocol` /
`RequestProtocol` typing protocols.

## Optional-dependency guard

Optional packages stay optional. `lite_bootstrap/import_checker.py` exposes
booleans computed once at import via `importlib.util.find_spec`
(`is_opentelemetry_installed`, `is_sentry_installed`, `is_fastapi_installed`,
`is_pyroscope_installed`, …). Optional imports sit behind
`if import_checker.is_X_installed:` blocks. Code that references the optional
symbol is only reached after `check_dependencies()` has already returned True,
so the runtime invariant holds even though static analyzers that don't model the
guard may report spurious "possibly unbound" diagnostics. The project uses `ty`,
which handles the pattern correctly.

**Guarding dotted `find_spec` checks.** `find_spec` imports a dotted name's
parent package first, so a present-but-incomplete namespace — e.g.
`opentelemetry-api` installed without `opentelemetry-instrumentation` — raised
`ModuleNotFoundError` instead of returning `False`, crashing `import
lite_bootstrap`. `import_checker._safe_find_spec` wraps `find_spec` for dotted
names and treats that exception as absent; `is_fastapi_opentelemetry_installed`
and `is_litestar_opentelemetry_installed` both route through it.

**OpenTelemetry resolves as three independent distributions: api, sdk, exporter.**
`opentelemetry-api` (the `opentelemetry.trace`/`.metrics`/`.context` namespace),
`opentelemetry-sdk` (`opentelemetry.sdk.*`), and each OTLP exporter package are
separate PyPI distributions — a real environment can have any subset. Three
`import_checker` flags mirror that:

- **`is_opentelemetry_installed`** (`find_spec("opentelemetry")`) — the api. The
  six api-only consumers (logging trace-injection, framework
  `get_tracer_provider`, faststream health-check spans) import only
  `opentelemetry.trace`/`.metrics` and gate on this.
- **`is_opentelemetry_sdk_installed`** (`_safe_find_spec("opentelemetry.sdk")`) —
  the sdk. `opentelemetry_instrument.py` imports `opentelemetry.sdk.*`, so its
  module-level import block gates on this, and `check_dependencies()` requires
  **both** api and sdk. Without the split, bare `opentelemetry-api` (e.g.
  `lite-bootstrap[fastmcp]`, which pulls it transitively without the sdk) crashed
  `import lite_bootstrap` at `from opentelemetry.sdk import resources`.
- **`is_otlp_grpc_exporter_installed`**
  (`_safe_find_spec("opentelemetry.exporter.otlp.proto.grpc.trace_exporter")`) —
  the gRPC OTLP exporter. Its import and its use in `bootstrap()` sit behind this
  guard; importing it unconditionally under the api flag previously crashed
  `import lite_bootstrap` the same way. When `opentelemetry_endpoint` is set but
  the exporter package is absent, `bootstrap()` emits an
  `InstrumentDependencyMissingWarning` ("…spans will not be exported. Install
  lite-bootstrap[otl].") rather than silently omitting the span processor — the
  standard configured-but-missing signal.

## Why instruments are not frozen

All `*Config` classes are frozen, but `*Instrument` classes drop `frozen=True`
because two of them cache mutable runtime state: `LoggingInstrument` caches a
`_logger_factory` (`MemoryLoggerFactory | None`) and `OpenTelemetryInstrument`
caches `_tracer_provider`. Python's dataclass rules require the whole hierarchy
to be non-frozen, so `BaseInstrument` is non-frozen too. Both caches are reset
to `None` inside a `try/finally` during `teardown()`, so a raised shutdown
leaves no stale references.

## Prometheus path-label cardinality (Litestar)

Litestar's `PrometheusConfig` defaults `group_path=False`, so the `path` metric
label holds the raw URL; parameterized routes then mint one series per distinct
value and grow the registry unbounded (memory growth — see
[litestar#4891](https://github.com/litestar-org/litestar/issues/4891)).
`LitestarConfig.prometheus_group_path` defaults to `True` to bind the label to
the route template (`/users/{id}`). `LitestarPrometheusInstrument.bootstrap`
merges `{"group_path": <field>, **prometheus_additional_params}`, so precedence
is `prometheus_additional_params["group_path"]` > `prometheus_group_path` >
Litestar's own default. Set `prometheus_group_path=False` for raw paths. FastAPI
is unaffected: `prometheus_fastapi_instrumentator` already labels by route
template.

## Cross-instrument integrations

**Logging ↔ Sentry.** `logging_instrument.py` renders every structlog line to a
flat JSON object via the shared serializer in `logging_factory.py`. The seam
between the two instruments is `StructuredLogPayload` (also in
`logging_factory.py`): its `parse` classmethod reconstructs that line into
`message` / `extra` / `skip_sentry`, owning the meta-key vocabulary
(`STRUCTLOG_META_KEYS`) and stripping it from `extra` — so neither the parsing
detail nor the key set lives in `sentry_instrument.py`. The Sentry side's
`enrich_sentry_event_from_structlog_log` (chained after the user's `before_send`
via `wrap_before_send_callbacks()`) only maps the parsed payload onto the Sentry
event: a truthy `skip_sentry` suppresses the event (checked before the
message-presence test), otherwise it lifts `message` and attaches `extra` under
`contexts.structlog`. `IGNORED_STRUCTLOG_ATTRIBUTES` remains in
`sentry_instrument.py` as a back-compat alias of `STRUCTLOG_META_KEYS`.

**OTel ↔ Logging.** The logging instrument injects span/trace IDs from the
active OpenTelemetry context into every log record, so logs and traces correlate.

**Pyroscope ↔ OTel.** When both are enabled, a `PyroscopeSpanProcessor` is added
to the tracer provider so traces and profiles link in Grafana.

## OpenTelemetry single-instance-per-process

`OpenTelemetryInstrument.bootstrap()` calls
`opentelemetry.trace.set_tracer_provider(...)`, which the OTel SDK enforces as
**set-once**. A second instance's call is ignored (the SDK logs "Overriding of
current TracerProvider is not allowed"). `teardown()` calls `shutdown()` on the
cached provider — flushing batched spans and closing exporters — and resets
`_tracer_provider = None`, but it **cannot** reset the process-global pointer.
Construct exactly one `OpenTelemetryInstrument` per process; do not bootstrap a
second.
