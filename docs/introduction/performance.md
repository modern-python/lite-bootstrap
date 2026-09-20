# Performance

Turning on the observability stack is not free, and the ordering of what costs what is not the one
most people expect. This page is the short version of
[the benchmark write-up](https://github.com/modern-python/lite-bootstrap/blob/main/benchmarks/README.md),
which has the method, the full ablations and the commands to reproduce everything here.

## The short answer

Measured on a trivial `async def` endpoint returning `{"ok": True}`, uvicorn with a single worker,
loaded with `ab -k -c 16 -n 20000`:

--8<-- "benchmarks/README.md:headline"

Tuning is worth **+80% RPS** on the real server, and every setting behind it is a documented
[configuration](configuration.md) field.

## Where the time goes

Each instrument alone, driving the ASGI app in-process so only library cost shows:

--8<-- "benchmarks/README.md:perinstrument"

Four things here are worth knowing before you tune anything:

- **OpenTelemetry costs about twice what Sentry does**, and is the dominant cost of the stack. Most
  people assume Sentry is the expensive one.
- **Structlog is free until you actually log.** `LoggingInstrument` adds ~0.1 µs per request when
  configured. The cost is per record, not per request, and it lands mostly in Sentry's two log
  handlers.
- **`sentry_traces_sample_rate=1.0` costs a further +353 µs per request.** If you set it, set it
  next to a sample rate you actually want.
- **The Sentry knobs people reach for do nothing.** This is the useful negative result:

--8<-- "benchmarks/README.md:sentryablation"

`attach_stacktrace`, `max_breadcrumbs` and dropping the default integrations all measure inside
noise. Essentially the entire cost is the ASGI integration, and over half of that is a `Transaction`
built and discarded because `sentry_traces_sample_rate` is unset.

## If you are RPS-constrained, start here

In rough order of what they return:

| field | saves | documented at |
|---|---|---|
| [`opentelemetry_sampler`](configuration.md#opentelemetry) | ~55 µs/req at a 1% ratio | Opentelemetry |
| [`opentelemetry_exclude_spans`](configuration.md#opentelemetry) | ~34 µs/req, FastAPI only | Opentelemetry |
| [`sentry_auto_session_tracking`](configuration.md#sentry) | ~7.7 µs/req | Sentry |
| [`sentry_logging_breadcrumb_level`](configuration.md#sentry-logging-integration) | ~7 µs per log record | Sentry |

Put together, that is the configuration the "tuned" row above measures:

--8<-- "benchmarks/README.md:tuned"

lite-bootstrap already applies one saving for you: it passes `sentry_logs_level=None` by default,
because it never enables Sentry Logs and the handler formats every record before checking whether
they are enabled. That one costs nothing, which is why it is a default rather than a knob.

## What each saving costs you

Speed alone does not settle whether a setting is worth changing. Measured by capturing a real error
event with an incoming `sentry-trace` header and inspecting the envelope:

--8<-- "benchmarks/README.md:tradeoffs"

In words: `http_methods_to_capture=()` gives the error event a fresh `trace_id` and no
`parent_span_id`, which breaks cross-service correlation of errors in Sentry. That is acceptable
when OpenTelemetry owns distributed tracing, as it does in any service that also runs
`OpenTelemetryInstrument`, and Sentry is only an error sink. It is not acceptable otherwise.
Dropping breadcrumbs costs you the log lines attached to error events. Sampling costs you the
traces that were sampled away.

## The caveat that matters most

These ratios are an upper bound. The endpoint measured here does nothing, so the fixed per-request
cost of the stack is compared against an unrealistically small denominator. A service that does real
work per request, a database round trip or a downstream call, pays the same absolute cost against a
much larger one.

**Read the µs columns, not the percentages.** A stack that costs 70% of a do-nothing handler's
throughput costs a few percent of a handler that waits 5 ms on a database.

Numbers are machine-specific and move a few percent between runs. The ordering and the ratios are
the durable part.
