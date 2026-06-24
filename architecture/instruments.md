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

## Why instruments are not frozen

All `*Config` classes are frozen, but `*Instrument` classes drop `frozen=True`
because two of them cache mutable runtime state: `LoggingInstrument` caches a
`_logger_factory` (`MemoryLoggerFactory | None`) and `OpenTelemetryInstrument`
caches `_tracer_provider`. Python's dataclass rules require the whole hierarchy
to be non-frozen, so `BaseInstrument` is non-frozen too. Both caches are reset
to `None` inside a `try/finally` during `teardown()`, so a raised shutdown
leaves no stale references.

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
