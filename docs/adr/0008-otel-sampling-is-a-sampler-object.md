# OpenTelemetry sampling takes a `Sampler`, not a sample-rate float

`opentelemetry_sampler` is handed straight to `TracerProvider(sampler=...)`. Left `None` — the
default — the SDK picks its own sampler, which honours `OTEL_TRACES_SAMPLER` / `OTEL_TRACES_SAMPLER_ARG`,
so both the default behaviour and the existing environment-variable path are unchanged; the
pass-through needs no conditional, because `TracerProvider(sampler=None)` is identical to omitting
the argument at the declared 1.28 floor and at 1.44 alike.

A `float` sample rate mirroring `sentry_traces_sample_rate` was rejected. It buys no dependency
independence — `opentelemetry_instrumentors` already carries `BaseInstrumentor`, and
`sentry_integrations` / `sentry_before_send` carry Sentry types, all as quoted annotations over
`TYPE_CHECKING` imports that never run — and it closes only part of the gap, leaving `ALWAYS_OFF`, a
bare `TraceIdRatioBased` and vendor samplers unreachable behind an instrument that owns provider
construction and offers no `*_additional_params` escape hatch. A float can still be layered on top
later, which is what a settings object mapping one env var would want.
