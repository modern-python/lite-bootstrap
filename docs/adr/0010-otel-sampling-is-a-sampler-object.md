# OpenTelemetry sampling takes a `Sampler`, not a sample-rate float

**Decision:** `OpenTelemetryConfig.opentelemetry_sampler` takes an `opentelemetry.sdk.trace.sampling.Sampler`
and is handed to `TracerProvider(sampler=...)` unconditionally. Left `None` — the default — the SDK
picks its own sampler, which honours `OTEL_TRACES_SAMPLER` / `OTEL_TRACES_SAMPLER_ARG`, so the
default behaviour and the existing environment-variable path are both unchanged.

## Context

`OpenTelemetryInstrument.bootstrap()` built the provider without a sampler, so `parentbased_always_on`
applied unless the environment said otherwise. #184 measured always-on tracing at ~55 µs/request over
`ParentBased(TraceIdRatioBased(0.01))` on an endpoint whose bare cost is 16 µs, and the instrument
owns provider construction, so there was no way to express a sampler from Python.

`TracerProvider(sampler=None)` is identical to omitting the argument: the SDK does
`if not sampler: sampler = sampling._get_from_env_or_default()`, at the declared 1.28 floor and at
1.44 alike. The pass-through therefore needs no conditional and no sentinel default.

## Rejected alternatives

**`opentelemetry_traces_sample_rate: float | None`, mapped internally to `ParentBased(TraceIdRatioBased(rate))`.**
Mirrors `sentry_traces_sample_rate` and keeps `opentelemetry.sdk` out of the config's annotations. Two
problems. The annotation argument does not hold: `opentelemetry_instrumentors` already carries
`BaseInstrumentor`, and `sentry_integrations` / `sentry_before_send` carry Sentry types, all as quoted
annotations over `TYPE_CHECKING` imports that never run. And a float closes only part of the gap:
`ALWAYS_OFF`, a bare `TraceIdRatioBased` without the `ParentBased` wrapper, and vendor samplers all
stay unreachable, and this config has no `opentelemetry_additional_params` escape hatch to reach them
through. A float can still be layered on the `Sampler` field later; the reverse ordering would have
shipped a second field to finish the job.

**Documenting `OTEL_TRACES_SAMPLER` and adding nothing.** It is a real surface and it keeps working,
but it is the only one, and it cannot express a custom sampler at all. Every other instrument takes
its configuration from the config object; tracing's sample rate should not be the exception that lives
in the environment.

**Validating the sampler in `__post_init__`.** Nothing to validate: `TraceIdRatioBased` already
rejects a rate outside [0.0, 1.0] at construction, which is where a float field would have needed a
range check of our own.

**Revisit trigger:** a request to drive the sampler from a settings object (pydantic-settings and
friends map an env var to a float, not to a `Sampler`), which is when the float becomes sugar worth
adding alongside — with this field winning where both are set.
