# Performance

Turning on the observability stack is not free, and the ordering of what costs what is not the one
most people expect. This page is the short version of
[the benchmark write-up](https://github.com/modern-python/lite-bootstrap/blob/main/benchmarks/README.md),
which has the method, the full ablations and the commands to reproduce everything here.

The first sections measure FastAPI on macOS. From [FastAPI on Linux](#fastapi-on-linux) on, the
numbers come from a 2-CPU Linux container on the same machine and cover all four frameworks.

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

- **OpenTelemetry costs about twice what Sentry does**, and is the dominant cost of the stack.
- **Structlog costs nothing until you actually log.** `LoggingInstrument` adds ~0.1 µs per request
  when configured. The cost arrives per record, not per request, and most of it is Sentry's two
  log handlers: on a three-record endpoint Sentry costs 12.3 µs per record, of which those
  handlers are 9.6.
- **`sentry_traces_sample_rate=1.0` costs a further +353 µs per request.** If you set it, set it
  next to a sample rate you actually want.
- **The Sentry knobs people reach for do nothing.**

--8<-- "benchmarks/README.md:sentryablation"

`attach_stacktrace`, `max_breadcrumbs` and dropping the default integrations all measure inside
noise. Essentially the entire cost is the ASGI integration, and over half of that is a `Transaction`
built and discarded because `sentry_traces_sample_rate` is unset. That table configures
sentry-sdk directly. Since 2.0, lite-bootstrap leaves the framework integration out while tracing
is off and reports request errors itself, which costs about 6 µs per request on FastAPI
([FastAPI: Sentry](../integrations/fastapi.md#sentry)).

## If you are RPS-constrained, start here

In rough order of what they return:

| setting | saves | what you give up |
|---|---|---|
| [`opentelemetry_sampler`](configuration.md#opentelemetry), 1% ratio | ~55 µs/req | 99% of your traces |
| `http_methods_to_capture=()` on the Sentry ASGI integrations | ~35 µs/req | Sentry-side trace correlation |
| [`opentelemetry_exclude_spans=["receive", "send"]`](configuration.md#opentelemetry), the default since 2.0 | ~34 µs/req | the two ASGI event spans |
| [`sentry_auto_session_tracking=False`](configuration.md#sentry), the default since 2.0 | ~7.7 µs/req | Sentry release health |
| [`sentry_logging_breadcrumb_level=None`](configuration.md#sentry-logging-integration) | ~7 µs per log record | log breadcrumbs on errors |

Together those are worth ~132 µs per request against the ~136 µs the tuned row actually recovers,
so there is nothing else material hiding in it. That configuration is:

--8<-- "benchmarks/README.md:tuned"

One thing to leave off rather than turn on: the FastAPI access log
([`logging_access_log_enabled`](../integrations/fastapi.md#logging)) is off by default, and
turning it on makes every request emit a log record. On a service that otherwise logs nothing per
request, every request then pays the per-record cost measured here:

--8<-- "benchmarks/README.md:logging"

lite-bootstrap already applies six savings for you. It turns Sentry Logs off in the logging
integration, because it never enables them and on 2.x the handler formats every record before
checking whether they are enabled; that one costs nothing. Since 2.0 it also leaves release-health
sessions off and starts breadcrumbs at `WARNING`, so an `INFO` record skips the breadcrumb handler.
Those two cost you release health and `INFO` breadcrumbs on error events; set
`sentry_auto_session_tracking=True` or `sentry_logging_breadcrumb_level=logging.INFO` to get them
back. And while Sentry tracing is off it reports request errors without sentry-sdk's framework
integration, which costs you request transactions and bodies the handler never read; set `sentry_lean_error_capture=False` to keep the integration. With tracing off it also turns
sentry-sdk's [auto-enabling integrations](configuration.md#sentry-auto-enabling-integrations) off,
which costs you their SQL, Redis and outgoing-HTTP breadcrumbs; set
`sentry_auto_enabling_integrations=True` to keep them. On FastAPI, Litestar and FastMCP it also
records no span for the ASGI `receive` and `send` events, which costs you those spans; set
`opentelemetry_exclude_spans=[]` to get them back. The numbers on this page were measured before
2.0, against the old defaults.

## What each saving costs you

Speed alone does not settle whether a setting is worth changing. Measured by capturing a real error
event with an incoming `sentry-trace` header and inspecting the envelope:

--8<-- "benchmarks/README.md:tradeoffs"

The row that needs a decision is `http_methods_to_capture=()`: the error event gets a fresh
`trace_id` and no `parent_span_id`, so errors stop correlating across services in Sentry. Take it
when OpenTelemetry owns distributed tracing and Sentry is only an error sink, which is the case in
any service running `OpenTelemetryInstrument`. Do not take it otherwise.

## FastAPI on Linux

The same instruments one at a time, in-process, in the Linux container:

--8<-- "benchmarks/README.md:fastapilinux"

The ordering matches macOS: OpenTelemetry first, then Sentry, then Prometheus, with logging free
until something logs. Since 2.0, Sentry with tracing off drops from about +59 to about +6 µs per
request, below Prometheus ([FastAPI: Sentry](../integrations/fastapi.md#sentry)).

## Litestar

In-process, one setting at a time:

--8<-- "benchmarks/README.md:litestarinprocess"

The same app on Granian, over real sockets:

--8<-- "benchmarks/README.md:litestargranian"

**Before 2.0, Sentry cost more on Litestar than on FastAPI**, and all of it was `LitestarIntegration`.
Since 2.0, lite-bootstrap reports Litestar request errors itself while Sentry tracing is off, which
brings Sentry from about +71 to about +7 µs per request in-process
([Litestar: Sentry](../integrations/litestar.md#sentry)). The access log
([`logging_access_log_enabled`](../integrations/litestar.md#logging)) is the largest opt-in item
left, at about 70 µs per request in-process.

## FastStream

Per consumed message:

--8<-- "benchmarks/README.md:faststreamconsume"

Per publish:

--8<-- "benchmarks/README.md:faststreampublish"

At the default `faststream_log_level=WARNING` the happy path logs nothing, which is why lite-bootstrap's
logging is cheaper than FastStream's own. Lowering it to INFO costs about 35 µs per message.

## FastMCP

Per tool call, through the stateless JSON HTTP app:

--8<-- "benchmarks/README.md:fastmcp"

The baseline is large, so the instruments are a smaller share here than on the HTTP frameworks.
OpenTelemetry is still the largest item. Since 2.0, Sentry with tracing off drops from about +82 to
about +21 µs per tool call ([FastMCP: Sentry](../integrations/fastmcp.md#sentry)).

## Unsampled OpenTelemetry is not free

--8<-- "benchmarks/README.md:otelfloor"

If you sample down to save CPU, this floor is what you keep paying. Excluding the `receive` and `send`
spans lowers it: Litestar's 1% row with them excluded sits below its 0% row with them kept. Since 2.0
they are excluded by default.

## Reproducing on macOS

--8<-- "benchmarks/README.md:macos"

## The caveat that matters most

These ratios are an upper bound. The endpoint measured here does nothing, so the fixed per-request
cost of the stack is compared against an unrealistically small denominator. A service that does real
work per request, a database round trip or a downstream call, pays the same absolute cost against a
much larger one.

**Read the µs columns, not the percentages.** A stack that costs 70% of a do-nothing handler's
throughput costs a few percent of a handler that waits 5 ms on a database.

Numbers are machine-specific and move a few percent between runs. The ordering and ratios are
stable across runs.
