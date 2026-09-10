# lite-bootstrap

Bootstraps a Python microservice with pre-configured observability: a frozen config declares what
the service wants, one instrument owns each observability concern, and a per-framework bootstrapper
decides which instruments apply and drives their lifecycle around the user's application.

## Language

A term is listed only when there is a synonym to reject, or a meaning subtle enough that code and
docs must agree on it. General programming vocabulary does not belong here, however heavily this
project uses it.

**Bootstrapper**:
The user-facing entry point, one class per framework. It owns exactly one application for the life
of the process — not a builder you can run twice. A second bootstrapper on the same application (or,
for Litestar, the same `AppConfig`) warns at construction and raises `ConfigurationError` from
`bootstrap()`.

**Instrument**:
One observability or middleware concern — logging, tracing, metrics, profiling, CORS, Swagger,
health checks. A framework subclass such as `FastAPIPrometheusInstrument` is the *same* instrument
bound to a framework, not a second instrument.
_Avoid_: instrumentation — reserve that for OpenTelemetry's own `opentelemetry-instrumentation-*`
packages and the middleware named after them; integration — that is the docs section of
per-framework guides, and Sentry's word for its own `Integration` objects.

**Configured**:
An instrument is configured when the user's config asks for it — `is_configured(config)`, a
classmethod evaluated before anything is instantiated. Unconfigured is the normal case, not a fault:
an empty `sentry_dsn` means the user did not want Sentry.
_Avoid_: enabled — `logging_enabled` and `health_checks_enabled` are two config fields among the
several inputs `is_configured` reads; most instruments have no enabled flag at all.

**Ready**:
A *bootstrapper* is ready when its framework package is importable — `is_ready()`, checked once in
`__init__`, raising `BootstrapperNotReadyError` when false. It is about the environment, never about
the config, and it is a different question from whether an instrument is **configured**.
_Avoid_: configured, for this sense. (Instruments carry a `not_ready_message` that is really the
not-configured reason; the attribute name predates the split and the two senses still meet there.)

**Skipped**:
An instrument the bootstrapper decided not to instantiate. Two paths, deliberately different
signals: not configured is silent and lands in `skipped_instruments`, so it shows in
`build_summary()`; configured but with its optional package missing is a deployment surprise, so it
raises `InstrumentDependencyMissingWarning` plus a `logger.warning` and lands in neither list. The
quiet skip is the one you have to go looking for; the loud one finds you.

**Free**:
Without a web framework — `FreeBootstrapper`, `FreeConfig`, the `free-all` extra. It has no
application, so nothing to attach teardown to and no double-bootstrap guard.
_Avoid_: bare "free" for PEP 703 free-threaded CPython, which this project also supports. Write
"free-threaded" in full.

**Rendered line**:
The complete JSON string the logging instrument produces for one event — message, level, metadata
and traceback together. One event is one rendered line is one physical line of stdout; the three
never diverge.
_Avoid_: formatted message — reserve that for Sentry's own `logentry.formatted` field, which holds
a rendered line only until the seam lifts the message out of it.
