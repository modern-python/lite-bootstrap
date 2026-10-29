# What the observability stack costs a lite-bootstrap service

Sections 1 to 7 measure FastAPI on macOS. Section 4d and section 8 add Linux measurements for
FastAPI, Litestar, FastStream and FastMCP, and section 8h explains why a Mac misranks some of them.

## 1. The short answer

On a do-nothing endpoint through uvicorn, the full stack costs **70% of throughput**
(7698 → 2313 RPS). Roughly a third of that is recoverable without giving up observability, and
**OpenTelemetry costs twice what Sentry does** - not the ordering most people expect.

Two published figures about the Sentry half look contradictory and are both correct.
[getsentry/sentry-python#2116](https://github.com/getsentry/sentry-python/issues/2116), open
since 2023, reports a Starlette app dropping from ~2000 to ~1000 RPS after adding the SDK;
Sentry's own docs claim
[under 1 ms of instrumentation overhead per request](https://docs.sentry.io/product/insights/performance-overhead/).
Both hold at once, because the added cost is a fixed ~70 µs: small in absolute terms, and
enormous next to a handler that does nothing.

That is also the caveat on everything below. These ratios are an upper bound. A service that
does real work per request - a database round trip, a downstream call - pays the same absolute
cost against a much larger denominator, so read the µs columns rather than the percentages.

## 2. Method

Two suites - `sentry` (one `sentry_sdk.init()` knob at a time) and `stack` (the lite-bootstrap
instruments, configured through `FastAPIBootstrapper`) - measured three ways:

- **In-process** (`run.py`) - drives the ASGI app directly (`await app(scope, receive, send)`), no
  sockets, no HTTP parsing. Isolates library cost; overstates the *relative* impact because the
  baseline is unrealistically fast.
- **Real server** (`run_http.py`) - uvicorn, single worker, access log off, loaded with
  `ab -k -c 16 -n 20000`. Verified the load generator is not the ceiling (baseline plateaus at
  ~8.4k RPS by c=64, vs 7.7k measured at c=16).
- **Micro** (`micro.py`, `verify.py`, `profile_one.py`) - per-operation costs, what each
  configuration actually gives up, and cProfile.

Each scenario runs in its own process. `sentry_sdk.init()` monkeypatches `Starlette.__call__`,
`Middleware.__init__` and `logging.Logger.callHandlers`; `set_tracer_provider` is set-once per
process; the Prometheus registry is global. None of it can be undone in-process.

Sentry events go to a null transport that still serializes the envelope, so transport CPU is
counted but network is not. OTLP spans go to a stub HTTP sink in a separate process that returns
200, so the exporter succeeds instead of spinning on retry backoff.

Environment: Apple M2 (8 cores), macOS 26.6.2, CPython 3.14.7, sentry-sdk 2.67.1, fastapi 0.141.1,
starlette 1.6.0, uvicorn 0.52.1, opentelemetry-sdk 1.44.0,
opentelemetry-instrumentation-fastapi 0.65b0, prometheus-fastapi-instrumentator 8.1.0,
structlog 26.1.0. Endpoint: `async def` returning `{"ok": True}`. Median of 5 rounds.

## 3. Headline numbers

<!-- --8<-- [start:headline] -->
Real server, uvicorn + `ab -k`, trivial async endpoint:

| config | RPS | µs/req | vs bare |
|---|---:|---:|---|
| bare FastAPI | 7698 | 129.9 | - |
| full lite-bootstrap stack (otel + prometheus + structlog + sentry) | 2313 | 432.3 | **−70%** |
| same stack, tuned (§6) | 4164 | 240.2 | −46% |

Same endpoint plus three structlog records per request:

| config | RPS | µs/req | vs bare |
|---|---:|---:|---|
| bare | 5548 | 180.3 | - |
| full stack | 1944 | 514.5 | **−65%** |
| tuned | 3418 | 292.5 | −38% |

<!-- --8<-- [end:headline] -->

In-process (SDK cost isolated, baseline 16.2 µs/req): full stack 61667 → 4056 RPS, **15.2x**.
Tuned recovers it to 9061, **2.23x** over the untuned stack.

The tuning is worth **+80% RPS** on the real server, and in-process the untuned stack costs an
order of magnitude of a do-nothing handler's throughput.

## 4. Per-instrument breakdown

In-process, each instrument alone, baseline 16.2 µs/req:

<!-- --8<-- [start:perinstrument] -->
| instrument | RPS | +µs/req | share of full stack |
|---|---:|---:|---|
| `LoggingInstrument` (configured, no logs emitted) | 61133 | +0.1 | ~0% |
| `PrometheusInstrument` | 29470 | +17.7 | 8% |
| `SentryInstrument` (tracing off) | 13541 | +57.6 | 25% |
| `OpenTelemetryInstrument` | 7280 | **+121.1** | 53% |
| all four | 4056 | +230.3 | |
<!-- --8<-- [end:perinstrument] -->

Costs are roughly additive, with the combination 17% dearer than the parts
(0.1 + 17.7 + 57.6 + 121.1 = 196 vs 230 measured). **OpenTelemetry is
twice Sentry**, which was not the expected ordering, and structlog's instrument costs nothing
until you actually log.

A re-run on 2026-10-24 at 705d8a3, same machine and command, gave bare 16.4 µs, Prometheus +17.3,
Sentry +57.1, OpenTelemetry +122.4 and all four +228.2. The table holds.

### 4a. OpenTelemetry: the two knobs that pay

| scenario | RPS | µs/req | gain |
|---|---:|---:|---|
| `otel` as lite-bootstrap 1.x configured it | 7267 | 137.6 | - |
| `+ opentelemetry_exclude_spans=["receive", "send"]` | 9651 | 103.6 | −34.0 µs |
| `+ opentelemetry_sampler=ParentBased(TraceIdRatioBased(0.01))` | 12154 | 82.3 | −55.3 µs |
| both | 15518 | 64.4 | **2.14x** |

1. `FastAPIInstrumentor.instrument_app` accepts `exclude_spans: list[Literal["receive","send"]]`,
   which `FastAPIConfig.opentelemetry_exclude_spans` passes through. In 1.x it was empty by
   default, so every request produced three spans: the server span plus one each for the ASGI
   `receive` and `send` events. Those two were two thirds of the spans and a quarter of the cost.
   Since 2.0 it defaults to `["receive", "send"]` on FastAPI, Litestar and FastMCP.
2. `OpenTelemetryConfig.opentelemetry_sampler` is passed to the `TracerProvider`. Left unset, the
   SDK default `parentbased_always_on` applies and every request is recorded, serialized and
   shipped. A 1% ratio sampler is worth 55 µs/req here. The default stays always-on deliberately:
   sampling rate is a user decision, not something to pick on a service's behalf.

Rerun for 2.0 in-process on the M2 host (macOS, CPython 3.14.7, opentelemetry-sdk 1.45.1,
opentelemetry-instrumentation-asgi 0.66b1, fastapi 0.162.0, litestar 2.25.0, fastmcp 4.1.4),
100% sampling, with `bench.py <suite> bare,otel,otel_all_spans --repeat 3` (FastMCP with
`--ops 1500 --warmup 300`). `otel` is the 2.0 default and `otel_all_spans` sets
`opentelemetry_exclude_spans=[]`, the 1.x default:

| suite | `otel` | `otel_all_spans` | saved |
|---|---:|---:|---:|
| FastAPI, per request | +91.8 | +127.8 | 36.0 |
| Litestar, per request | +79.3 | +116.1 | 36.8 |
| FastMCP, per `tools/call` | +175.4 | +273.8 | 98.4 |

FastMCP's rounds differed by up to 9%, FastAPI's `otel` row by 17%.

### 4b. Sentry: the cost is one thing, and it is not the one people tune

In-process ablation, Sentry only, baseline 16.5 µs/req:

<!-- --8<-- [start:sentryablation] -->
| scenario | +µs | reading |
|---|---:|---|
| defaults (tracing off) | +64.2 | the number to beat |
| `attach_stacktrace=False` | +63.2 | no effect on the happy path |
| `max_breadcrumbs=0` | +63.4 | no effect - the crumb is still built |
| `disabled_integrations=[Stdlib, Modules, Dedupe, Excepthook, Threading]` | +63.8 | no effect |
| `default_integrations=False` (Starlette+FastAPI kept) | +63.8 | no effect |
| **`integrations=[]`, no framework integration** | **−0.1** | **all of it is the ASGI integration** |
| `auto_session_tracking=False` | +56.5 | sessions cost ~7.7 µs |
| `http_methods_to_capture=()` (no Transaction) | +29.2 | the Transaction costs ~35 µs |
| both of the above | +19.9 | |
<!-- --8<-- [end:sentryablation] -->

The first block is the useful negative result: **every knob people reach for first buys nothing.**
All the cost is in `SentryAsgiMiddleware._run_app`, and most of it is a `Transaction` built and
thrown away because tracing is disabled.

Micro-benchmarks (`micro.py`):

| operation | µs |
|---|---:|
| `Random(trace_id)` - seeding Mersenne Twister | 6.60 |
| `_generate_sample_rand(trace_id)` | 7.18 |
| `Transaction(op, name, source)` | 10.10 |
| `scope.continue_trace(headers)` | 11.28 |
| `start_transaction(txn)` + exit, tracing **off** | 19.25 |
| `scope.generate_propagation_context(headers)` | 0.64 |
| `isolation_scope()` enter/exit | 2.31 |
| `scope.fork()` | 0.62 |
| `get_client()` | 0.14 (×17 per request) |

`Transaction.__init__` unconditionally calls `_generate_sample_rand(self.trace_id)`, which does
`Random(trace_id)` - a full Mersenne Twister seed, 6.6 µs. It is 6.1 µs even for `Random(1)`, so
the cost is the MT init, not the string hashing; deriving the same value arithmetically
(`int(trace_id, 16) / 2**128`) takes **0.25 µs, 27x cheaper**. This runs on every request even
when `traces_sample_rate is None`.

With `traces_sample_rate=1.0` the SDK costs +353 µs/req on the real server: 1948 RPS against
this suite's own baseline of 6241, −69%. That baseline is Sentry-off on the same app, not §3's
bare FastAPI, so the two tables are not directly comparable.

### 4c. Logging: cost per record, not per request

<!-- --8<-- [start:logging] -->
Three records per request, in-process:

| scenario | +µs/req | delta |
|---|---:|---:|
| sentry-sdk defaults | +101.1 | |
| `sentry_logs_level=None` (lite-bootstrap's default since #186) | +93.8 | −2.4 µs/record |
| also `sentry_logging_breadcrumb_level=None` | +72.4 | −9.6 µs/record total |
<!-- --8<-- [end:logging] -->

Two handlers run per log record. `SentryLogsHandler.emit` calls `self.format(record)` *before* it
checks `has_logs_enabled(client.options)`, so with Sentry Logs disabled (the default, and
lite-bootstrap never sets `enable_logs`) every record is formatted an extra time for nothing.
lite-bootstrap passes `sentry_logs_level=None` by default, so a service gets the second row
without configuring anything.
`BreadcrumbHandler` then formats it again and builds a breadcrumb dict. `max_breadcrumbs=0` does
not help: the crumb is constructed before the deque drops it.

This hits lite-bootstrap directly because `LoggingInstrument` wires structlog through
`structlog.stdlib.BoundLogger`, so every structlog call goes through the patched
`logging.Logger.callHandlers` and pays both handlers.

### 4d. FastAPI on Linux, in-process

The same suite shape on Linux (section 8a has the method), from `frameworks/fastapi_suite.py`.
Each row is one setting on top of everything off, compared with that baseline.

<!-- --8<-- [start:fastapilinux] -->
Linux, a 2-CPU container on the same Apple M2 under OrbStack, CPython 3.14.9, fastapi 0.141.1,
starlette 1.6.0, sentry-sdk 2.67.1, opentelemetry-sdk 1.44.0,
opentelemetry-instrumentation-fastapi 0.65b0, prometheus-fastapi-instrumentator 8.1.0,
structlog 26.1.0. In-process, baseline 17.7 µs per request. The handler does nothing, so read the µs column: it is what a real service adds to its own work.

| scenario | +µs/req | note |
|---|---:|---|
| logging configured, no records | +0.1 | |
| `logging_access_log_enabled=True` | +18.3 | one access-log record per request, about 10 µs of it the record |
| Prometheus | +19.1 | |
| OpenTelemetry, 100% sampling | +147.9 | |
| OpenTelemetry, `opentelemetry_exclude_spans=["receive", "send"]` | +101.6 | -46.3 |
| OpenTelemetry, 10% ratio sampler | +79.0 | |
| 10% and exclude receive/send | +54.0 | |
| OpenTelemetry, 0% ratio sampler | +66.6 | the unsampled floor |
| OTel 0% + OTel HTTP metrics (`opentelemetry_metrics_endpoint`) | +78.9 | +12.3 over OTel 0% |
| OTel 0% + Prometheus | +91.5 | +24.9 over OTel 0% |
| OTel 0% + OTel HTTP metrics + Prometheus | +104.9 | +38.3 over OTel 0% |
| Sentry, lite-bootstrap 1.x defaults (tracing off) | +59.0 to +59.7 | two runs |
| Sentry, `sentry_auto_session_tracking=False` | +51.8 | |
| Sentry, `auto_enabling_integrations=False` | +0.1 | the Starlette and FastAPI integrations are auto-enabling, so nothing captures request errors |
| health check `/health/` | +22.6 | noisy, 16% spread |
| health check with OpenTelemetry, spans on (default) / off | +162.3 / +28.9 | noisy, 32 to 50% spread |
| CORS, request with a matching Origin | +3.8 | |
| full: OTel + Prometheus + logging + Sentry + health, defaults | +259.6 | |
<!-- --8<-- [end:fastapilinux] -->

Since 2.0, lite-bootstrap reports FastAPI request errors itself while Sentry tracing is off, without
`StarletteIntegration` and `FastApiIntegration`. Rerun in-process on the M2 host (macOS, CPython
3.14.7, fastapi 0.162.0, starlette 1.10.0,
`bench.py fastapi bare,sentry,sentry_sampled_trace,sentry_nointegration,sentry_integration,sentry_integration_sampled_trace --repeat 2`):

| scenario | sentry-sdk 2.73.0 | 3.0.0b2 |
|---|---:|---:|
| `sentry`: lean capture, the 2.0 default | +6.1 | +5.1 |
| `sentry_sampled_trace`: the same, request carries a sampled `sentry-trace` | +11.5 | +10.9 |
| `sentry_nointegration`: both integrations disabled, no request capture at all | +0.1 | -0.2 |
| `sentry_integration`: `sentry_lean_error_capture=False` | +57.1 | +47.0 |
| `sentry_integration_sampled_trace` | +59.2 | +113.2 |

The last row on 3.0.0b2 varied by 40% between rounds. The table above was measured before 2.0. Its
OpenTelemetry rows record the `receive` and `send` spans, which 2.0 leaves out by default (section
4a). Its `sentry_nosess` row now has the same config as `sentry`, and `sentry_noauto` no longer stops request
capture, because lean capture needs no auto-enabling integration.

FastAPI real-server runs under uvicorn in the container were unstable (bare repeat medians of 8235
and 6341 RPS, over 100% spread on the full stack), so the Linux real-server numbers below are
Litestar on Granian only.

## 5. What each saving actually costs you

Measured by capturing a real error event with an incoming `sentry-trace` header and inspecting the
envelope (`verify.py`):

<!-- --8<-- [start:tradeoffs] -->
| config | txn name | continues incoming trace | breadcrumbs |
|---|---|---|---|
| defaults | `/ping` | yes | yes |
| `http_methods_to_capture=()` | `/ping` | **no** | yes |
| `sentry_logging_breadcrumb_level=None` | `/ping` | yes | **no** |
| propagation kept, Transaction skipped (patched SDK) | `/ping` | yes | yes |
<!-- --8<-- [end:tradeoffs] -->

`http_methods_to_capture=()` is not free: the error event gets a fresh `trace_id` and no
`parent_span_id`, which breaks cross-service correlation of errors in Sentry. Acceptable when
distributed tracing is OpenTelemetry's job - as it is in any lite-bootstrap service that also runs
`OpenTelemetryInstrument` - and Sentry is only an error sink. Not acceptable otherwise.

The last row is the interesting one: replacing `Scope.continue_trace` with a version that keeps
`generate_propagation_context(headers)` and returns no Transaction loses **nothing** on the error
event and still saves ~32 µs/req. That is a pure upstream bug, not a trade-off.

Similarly, `opentelemetry_exclude_spans=["receive","send"]` costs you the ASGI event spans and
nothing else, and `sentry_logs_level=None` costs nothing at all while Sentry Logs is disabled -
which is why lite-bootstrap now applies it by default.

## 6. The tuned configuration

What "tuned" means in §3, all reachable through today's public API:

<!-- --8<-- [start:tuned] -->
```python
FastAPIConfig(
    # Sentry: OTel owns distributed tracing, Sentry is an error sink
    sentry_integrations=[
        StarletteIntegration(http_methods_to_capture=()),
        FastApiIntegration(http_methods_to_capture=()),
    ],
    sentry_logging_breadcrumb_level=None,
    # OpenTelemetry: sampling is the single biggest saving here
    opentelemetry_sampler=ParentBased(TraceIdRatioBased(0.01)),
)
```
<!-- --8<-- [end:tuned] -->

The tuned runs also set `sentry_auto_session_tracking=False` and
`opentelemetry_exclude_spans=["receive", "send"]`, which are the defaults since 2.0.

Trade-offs, in order of what you give up: log breadcrumbs on Sentry errors, Sentry release health,
Sentry-side trace correlation, 99% of OTel traces, ASGI event spans.

## 7. Filed issues

lite-bootstrap (all "possible improvement"):

- [#184](https://github.com/modern-python/lite-bootstrap/issues/184) OpenTelemetry sampler is not
  configurable (55 µs/req) - **implemented** as `opentelemetry_sampler`
- [#185](https://github.com/modern-python/lite-bootstrap/issues/185) `exclude_spans` is never passed
  to `FastAPIInstrumentor` (33 µs/req) - **implemented** as `opentelemetry_exclude_spans`
- [#186](https://github.com/modern-python/lite-bootstrap/issues/186) Sentry `sentry_logs_level`,
  breadcrumb level and `auto_session_tracking` are not exposed (~9 µs/req plus ~2 µs/log record) -
  **implemented**: `sentry_logs_level=None` is now the default, and the other two are
  `sentry_logging_breadcrumb_level` and `sentry_auto_session_tracking`
- [#187](https://github.com/modern-python/lite-bootstrap/issues/187) Document what the stack costs

sentry-python:

- [#7400](https://github.com/getsentry/sentry-python/issues/7400) A full `Transaction` is built and
  discarded per request when tracing is disabled (~35 µs)
- [#7401](https://github.com/getsentry/sentry-python/issues/7401) `_generate_sample_rand` seeds a
  Mersenne Twister per `Transaction`, eagerly, even when unsampled (6.6 µs; 27x cheaper
  arithmetically)
- [#7402](https://github.com/getsentry/sentry-python/issues/7402) `SentryLogsHandler.emit` formats
  the record before checking `has_logs_enabled` (~2.4 µs/record)
- Measurements added as a [comment on #2116](https://github.com/getsentry/sentry-python/issues/2116#issuecomment-5565265173),
  the long-open "SDK causes significant performance issue" report, rather than filing a duplicate.

Related existing reports: [#2303](https://github.com/getsentry/sentry-python/issues/2303),
[#668](https://github.com/getsentry/sentry-python/issues/668).

## 8. Litestar, FastStream and FastMCP on Linux

### 8a. Environment and method

Linux runs used an OrbStack container (Debian 13, kernel 7.2.12) limited to 2 CPUs with `--cpus 2`,
on the same Apple M2 as the macOS runs, with CPython 3.14.9. lite-bootstrap was at 705d8a3; `lite_bootstrap/` is
unchanged from there to 33b503e. Dependency versions: litestar 2.24.0, fastapi 0.141.1,
starlette 1.6.0, faststream 0.7.4, fastmcp 3.4.6, mcp 1.29.0, sentry-sdk 2.67.1,
opentelemetry-sdk 1.44.0, opentelemetry-instrumentation-asgi and -fastapi 0.65b0,
prometheus-client 0.26.0, prometheus-fastapi-instrumentator 8.1.0, structlog 26.1.0, orjson 3.11.9,
redis 8.1.0, granian 2.8.5, uvicorn 0.52.1.

The harness lives in `frameworks/`, one `<suite>_suite.py` per framework plus `logging_suite.py`.
It keeps the rules of section 2: one process per scenario, Sentry into the null transport from
`driver.py`, OTLP into `stub_otlp.py` in a separate process.

- In-process (`frameworks/bench.py`, which runs `frameworks/one.py` per scenario): the ASGI app is
  awaited directly with a fresh scope per request, after a real lifespan startup. 4000 operations per
  round, 5 rounds, 500 warm-up; the figure is the median round, and the scenario list is run 2 to 4
  times interleaved (`--repeat`), reporting the median of the repeat medians.
- Real server (`frameworks/run_http.py`): Granian, 1 worker, 1 runtime thread, the asyncio loop
  (uvloop was not installed), access log off, loaded with `ab -k -c 16 -n 20000`, 3 rounds after a
  3000-request warm-up, 2 repeats. ab runs in the same 2-CPU container as the server.
- FastStream: a real `RedisBroker` started against Redis 8, then the subscriber's own
  `process_message` on a prebuilt raw pub/sub message, in a loop. That is the call the consume loop
  makes for every message, so parsing, decoding, the middleware chain, the handler and FastStream's
  per-message log calls all run, and Redis is not touched inside the loop. `TestRedisBroker` is not
  used because it replaces the broker's logger with a `MagicMock`, which hides those log calls. The
  publish rows are `broker.publish` to Redis, one round trip each.
- FastMCP: a JSON-RPC `tools/call` POSTed in-process to
  `http_app(stateless_http=True, json_response=True)`. Stateless JSON mode makes one tool call one
  HTTP request with no session handshake. The tool adds two ints.

Other work shared the machine for part of the session. Treat differences under
about 3 µs in-process, and under about 10 µs on the real server, as noise; FastMCP is noisier still
(section 8e).

Every endpoint, message handler and tool does nothing. Read the µs columns: the absolute cost is
what a real service pays, and the percentages are large only because the handler is empty.

### 8b. Litestar, in-process

<!-- --8<-- [start:litestarinprocess] -->
Linux, a 2-CPU container on the same Apple M2 under OrbStack, CPython 3.14.9, litestar 2.24.0,
sentry-sdk 2.67.1, opentelemetry-sdk 1.44.0, opentelemetry-instrumentation-asgi 0.65b0,
prometheus-client 0.26.0, structlog 26.1.0. In-process, baseline 12.1 µs per request, everything off. The handler does nothing, so read the µs column: it is what a real service adds to its own work.

| scenario | +µs/req | note |
|---|---:|---|
| logging configured, no records | -0.1 | free until something logs |
| logging, 3 structlog records in the handler | +33.8 | 11.3 µs per record |
| `logging_access_log_enabled=True` | +70.7 | 2 records per request, each written twice; a second run gave +74.4 |
| Prometheus | +11.6 | |
| Prometheus, `prometheus_group_path=False` | +11.8 | |
| OpenTelemetry, 100% sampling | +145.4 | a second run gave +131.8 |
| OpenTelemetry, `opentelemetry_exclude_spans=["receive", "send"]` | +92.4 | a second run gave +90.8 |
| OpenTelemetry, 10% ratio sampler | +66.8 | |
| 10% and exclude receive/send | +46.7 | |
| 1% and exclude receive/send | +39.2 | |
| OpenTelemetry, 0% ratio sampler | +56.8 | a second run gave +60.7 |
| OTel 100% + OTel HTTP metrics (`opentelemetry_metrics_endpoint`) | +157.0 | +11.6 over OTel |
| OTel 0% + OTel HTTP metrics | +73.6 | +12.9 over OTel 0%, second run |
| OTel 0% + Prometheus | +76.5 | +15.8 over OTel 0%, second run |
| OTel 0% + OTel HTTP metrics + Prometheus | +90.2 | +29.5 over OTel 0%, second run |
| Sentry, lite-bootstrap 1.x defaults (tracing off) | +70.9 | LitestarIntegration |
| Sentry, `sentry_auto_session_tracking=False` | +63.7 | sessions cost 7.2 |
| Sentry, `auto_enabling_integrations=False` | -0.1 | LitestarIntegration is auto-enabling, so nothing captures request errors |
| Sentry, `sentry_default_integrations=False` | -0.2 | same reason |
| Sentry, LitestarIntegration disabled | -0.2 | lower bound: no Sentry work per request |
| CORS, request without Origin | +2.4 | |
| CORS, simple request with a matching Origin | +7.2 | against bare with the same header |
| Swagger (`/docs`), online or offline | -0.2 | registers routes only |
| health check `/health/`, against an equivalent `/ping` handler | +7.1 | `asyncio.gather` of one coroutine |
| health check with OpenTelemetry, spans on (default) | +134.0 | against health without OpenTelemetry |
| health check with OpenTelemetry, `opentelemetry_generate_health_check_spans=False` | +9.2 | |
| full: OTel + Prometheus + logging + Sentry + health, defaults | +297.7 | |
| full, 3 structlog records per request | +377.8 | |
<!-- --8<-- [end:litestarinprocess] -->

The "second run" rows come from a noisier re-check (spread between rounds up to 67% per row). The
first run's OTel 0% row is +56.8, the re-check's +60.7, and the deltas in the notes are against the
re-check.
Since 2.0, lite-bootstrap reports Litestar request errors itself while Sentry tracing is off, without
`LitestarIntegration`. Rerun in-process on the M2 host (macOS, CPython 3.14.7, litestar 2.25.0,
`bench.py litestar bare,sentry,sentry_sampled_trace,sentry_integration,sentry_integration_sampled_trace --repeat 2`):

| scenario | sentry-sdk 2.73.0 | 3.0.0b2 |
|---|---:|---:|
| `sentry`: lean capture, the 2.0 default | +7.3 | +8.3 |
| `sentry_sampled_trace`: the same, request carries a sampled `sentry-trace` | +9.7 | +10.1 |
| `sentry_integration`: `sentry_lean_error_capture=False` | +70.7 | +59.5 |
| `sentry_integration_sampled_trace` | +74.4 | +147.4 |

On 3.0 an incoming sampled `sentry-trace` makes `LitestarIntegration` record a real span even with
tracing off. `sentry_nointegration`, which disables `LitestarIntegration` and turns lean capture off,
so nothing captures request errors, measured +0.3 and +0.0 in a later run that put `sentry` at
+6.7 and +6.8. The table above was measured before 2.0. Its `sentry_nosess` scenario now has the same
config as `sentry`, because sessions are off by default since 2.0. Its OpenTelemetry rows record the
`receive` and `send` spans, which 2.0 leaves out by default (section 4a).

lite-bootstrap's Litestar defaults with no endpoint configured (Prometheus, health, logging and
Swagger on) cost +11.7 µs on `/ping`, all of it Prometheus. The access-log middleware writes each record
twice because Litestar's own stdlib logging config is applied at startup next to lite-bootstrap's.

### 8c. Litestar, real server

<!-- --8<-- [start:litestargranian] -->
Linux, a 2-CPU container on the same Apple M2 under OrbStack, CPython 3.14.9, litestar 2.24.0,
granian 2.8.5 (1 worker, 1 runtime thread, asyncio loop), `ab -k -c 16 -n 20000` in the same
container, sentry-sdk 2.67.1, opentelemetry-sdk 1.44.0, opentelemetry-instrumentation-asgi 0.65b0,
prometheus-client 0.26.0, structlog 26.1.0. Baseline 33350 RPS, 30.0 µs per request. The handler does nothing, so read the µs column: it is what a real service adds to its own work.

| scenario | RPS | +µs/req |
|---|---:|---:|
| bare | 33350 | 0 |
| OpenTelemetry, 100% | 5028 | +168.9 |
| OpenTelemetry, 100%, exclude receive/send | 7537 | +102.7 |
| OpenTelemetry, 10% | 8815 | +83.5 |
| OpenTelemetry, 10%, exclude receive/send | 11258 | +58.8 |
| Prometheus | 18823 | +23.1 |
| Litestar access log on | 6879 | +115.4 |
| Sentry, 1.x defaults | 8119 | +93.2 |
| Sentry, 1.x defaults, sessions off | 9184 | +78.9 |
| CORS (ab sends no Origin) | 30942 | +2.3 |
| health check | 28337 | +5.3 |
| health check with OpenTelemetry spans | 4600 | +187.4 |
| full, defaults | 2181 | +428.6 |
<!-- --8<-- [end:litestargranian] -->

Spread between rounds ran up to 20% on this table (access log 16%, CORS 20%), so differences under
about 10 µs are noise.

### 8d. FastStream

<!-- --8<-- [start:faststreamconsume] -->
Linux, a 2-CPU container on the same Apple M2 under OrbStack, CPython 3.14.9, faststream 0.7.4 on a
`RedisBroker` against Redis 8 (redis 8.1.0), sentry-sdk 2.67.1, opentelemetry-sdk 1.44.0,
prometheus-client 0.26.0, structlog 26.1.0. Per consumed message, baseline 37.4 µs with
lite-bootstrap logging on (its default) and nothing else; every row except the first keeps logging on. The handler does nothing, so read the µs column: it is what a real service adds to its own work.

| scenario | +µs/msg | note |
|---|---:|---|
| lite-bootstrap logging off | +18.9 | FastStream's default logger writes "Received" and "Processed" at INFO, 2 records per message |
| `faststream_log_level=logging.INFO` | +35.2 | the same 2 records through lite-bootstrap, each written twice |
| 3 structlog records in the handler | +42.2 | 14 per record |
| Prometheus middleware | +19.5 | |
| OpenTelemetry middleware, 100% | +60.0 | |
| OpenTelemetry, 10% | +40.6 | |
| OpenTelemetry, 0% | +25.4 | the unsampled floor |
| OTel 100% + OTel metrics | +66.4 | +6.4 |
| OTel 0% + OTel metrics | +30.6 | +5.2 |
| OTel 0% + Prometheus | +44.4 | +19.0 |
| OTel 100% + Prometheus | +80.4 | +20.4 |
| OTel 100% + OTel metrics + Prometheus | +86.7 | +26.7 over OTel |
| Sentry | -0.1 | no FastStream integration, and FastStream's log lines are filtered at WARNING |
| Sentry with lite-bootstrap logging off | +18.0 over logging off | breadcrumbs for FastStream's 2 INFO records |
| Sentry with `faststream_log_level=logging.INFO` | +17.6 over the INFO row | 8.8 per record |
| Sentry with 3 handler records | +25.2 over the 3-record row | 8.4 per record |
| Sentry, `auto_enabling_integrations=False` | -0.5 | |
| full: OTel + Prometheus + logging + Sentry | +78.9 | |
<!-- --8<-- [end:faststreamconsume] -->

FastStream's own `StreamHandler(stderr)` stays on the `faststream` logger next to lite-bootstrap's
handler, so a service that lowers `faststream_log_level` gets every FastStream line twice and pays
for both. At the default level of WARNING the happy path logs nothing.

<!-- --8<-- [start:faststreampublish] -->
Same environment, per `broker.publish` to Redis (one round trip each), baseline 42.3 µs with
lite-bootstrap logging on. The message triggers no work, so read the µs column: it is what a real service adds to its own work.

| scenario | +µs/publish | note |
|---|---:|---|
| Prometheus | +11.6 | |
| OpenTelemetry, 100% | +73.0 | producer span plus context injection |
| OpenTelemetry, 10% | +30.6 | |
| Sentry, 1.x defaults | +28.8 | RedisIntegration (auto-enabling) on the redis client |
| Sentry, `auto_enabling_integrations=False` | +0.0 | |
<!-- --8<-- [end:faststreampublish] -->

Since 2.0, lite-bootstrap leaves sentry-sdk's auto-enabling integrations off while Sentry tracing is
off. Rerun per publish on the M2 host (macOS, CPython 3.14.7, faststream 0.7.8, redis 8.1.0, Redis 8 in a local
container, `bench.py faststream log@pub,sentry@pub,sentry_auto@pub,sentry_noauto@pub --repeat 3`),
over a baseline of about 136 µs:

| scenario | sentry-sdk 2.73.0 | 3.0.0b2 |
|---|---:|---:|
| `sentry`: the 2.0 default | -3.0 | -1.7 |
| `sentry_auto`: `sentry_auto_enabling_integrations=True` | +27.1 | +9.5 |
| `sentry_noauto`: `auto_enabling_integrations=False` in `sentry_additional_params` | -1.6 | -1.4 |

The first round of the baseline ran 11% slower than the other two, so the negative rows are noise.
`sentry_noauto` now has the same config as `sentry`.

### 8e. FastMCP

<!-- --8<-- [start:fastmcp] -->
Linux, a 2-CPU container on the same Apple M2 under OrbStack, CPython 3.14.9, fastmcp 3.4.6,
mcp 1.29.0, starlette 1.6.0, sentry-sdk 2.67.1, opentelemetry-sdk 1.44.0,
opentelemetry-instrumentation-asgi 0.65b0, prometheus-client 0.26.0,
prometheus-fastapi-instrumentator 8.1.0, structlog 26.1.0. Per tool call, baseline 517 µs, most of
it FastMCP and the MCP SDK. Noise on this suite is about ±30 µs even with 3 repeats, so rows under
30 µs are unresolved. The tool does nothing, so read the µs column: it is what a real service adds to its own work.

| scenario | +µs/call | note |
|---|---:|---|
| logging configured | +15 | noise |
| `logging_access_log_enabled=True` | +51 | one record per MCP message |
| Prometheus (HTTP instrumentator and tool-call middleware) | +35 | the split between the two is within noise |
| OpenTelemetry, 100% | +272 | 3 ASGI spans plus FastMCP's own server span |
| OpenTelemetry, 100%, FastMCP's own spans replaced by a no-op tracer | +226 | FastMCP's spans cost 46 |
| OpenTelemetry, 10% | +120 | |
| Sentry, 1.x defaults | +100 | the Starlette integration |
| Sentry, MCPIntegration disabled | +99 | MCPIntegration costs nothing measurable with tracing off |
| Sentry, `auto_enabling_integrations=False` | +3 | no Starlette integration, so no request capture |
| full: OTel + Prometheus + logging + Sentry + health | +521 | |
<!-- --8<-- [end:fastmcp] -->

The no-op tracer row patches FastMCP to attribute the cost; it is not a configuration.

Since 2.0, lite-bootstrap reports errors in every application `http_app()` builds itself while
Sentry tracing is off, without `StarletteIntegration`. Rerun in-process on the M2 host (macOS,
CPython 3.14.7, fastmcp 4.1.4, starlette 1.10.0,
`bench.py fastmcp bare,sentry,sentry_sampled_trace,sentry_nointegration,sentry_integration,sentry_integration_sampled_trace --repeat 3 --ops 1500 --warmup 300`),
over a baseline of about 620 µs per tool call:

| scenario | sentry-sdk 2.73.0 | 3.0.0b2 |
|---|---:|---:|
| `sentry`: lean capture, the 2.0 default | +20.6 | +15.9 |
| `sentry_sampled_trace` | +16.1 | +18.9 |
| `sentry_nointegration`: `StarletteIntegration` disabled, no request capture at all | -0.3 | +1.8 |
| `sentry_integration`: `sentry_lean_error_capture=False` | +82.2 | +65.0 |
| `sentry_integration_sampled_trace` | +82.3 | +216.4 |

Rounds differed by up to 15%, so the lean rows are not resolved from each other.

The OpenTelemetry rows in the first table record the ASGI `receive` and `send` spans, which 2.0
leaves out by default: section 4a has the rerun.

### 8f. Logging, per call

The per-call chain is the same on every framework: structlog's stdlib `BoundLogger`, lite-bootstrap's
processors, `JSONRenderer` with orjson, stdlib `Logger.info`, `MemoryHandler(capacity=10)` and a
`StreamHandler`. What differs per framework is who logs per request: FastAPI's opt-in access log (1
record), Litestar's opt-in `LoggingMiddleware` (2 records), FastMCP's opt-in logging middleware (1
record per MCP message), FastStream's own "Received" and "Processed" (filtered at the default
`faststream_log_level=WARNING`).

Linux, a 2-CPU container on the same Apple M2 under OrbStack, CPython 3.14.9, structlog 26.1.0,
orjson 3.11.9, sentry-sdk 2.67.1, opentelemetry-sdk 1.44.0. Output to a real `/dev/null` file,
50000 calls per round, loop overhead (0.06 µs) subtracted.

| call | µs/call |
|---|---:|
| `log.info("did a thing", a=1)` through lite-bootstrap's chain | 9.5 |
| same with 5 keyword values | 10.4 |
| `log.debug(...)` at INFO, filtered | 1.1 |
| info, JSON through stdlib `json` (the fallback without orjson) | 11.5 |
| info, `logging_buffer_capacity=1` | 10.5 |
| info inside a recording OpenTelemetry span | 10.7 |
| info with Sentry's LoggingIntegration, breadcrumb level INFO (default) | 15.7 |
| info with Sentry, `sentry_logging_breadcrumb_level=None` | 10.5 |
| debug filtered, with Sentry | 1.1 |
| stdlib `logging.getLogger("lib").info(...)` through the root handler | 13.2 |
| same with Sentry | 19.7 |
| stdlib debug, filtered | 0.08 |
| structlog's own path: `make_filtering_bound_logger`, `BytesLoggerFactory`, orjson bytes (not lite-bootstrap) | 2.6 |
| same, filtered | 0.2 |

The log call does nothing else, so these are per-record costs a service pays on top of its own work.
Sentry's breadcrumb handler is the largest optional item at 6.2 µs per INFO record. The last two rows
are a reference point: the stdlib bridge is most of the gap, and it is also what lets Sentry see
structlog records.

### 8g. Unsampled OpenTelemetry is not free

<!-- --8<-- [start:otelfloor] -->
Lowering the sampling ratio does not take OpenTelemetry's cost to zero. Linux, in-process, with a
`ParentBased(TraceIdRatioBased(...))` sampler:

| framework | setting | +µs per request or message |
|---|---|---:|
| Litestar | 0% ratio, receive/send spans kept | +56.8 and +60.7 (two runs) |
| FastAPI | 0% ratio, receive/send spans kept | +66.6 |
| Litestar | 1% ratio, `opentelemetry_exclude_spans=["receive", "send"]` | +39.2 |
| FastStream | 0% ratio | +25.4 per message |

Against 100% sampling (Litestar +145.4, FastAPI +147.9, FastStream +60.0), sampling down buys the
difference and no more. lite-bootstrap leaves the sampler to the OpenTelemetry SDK
([ADR-0008](https://github.com/modern-python/lite-bootstrap/blob/main/docs/adr/0008-otel-sampling-is-a-sampler-object.md)), whose default records every root
trace unless `OTEL_TRACES_SAMPLER` says otherwise.
<!-- --8<-- [end:otelfloor] -->

### 8h. Reproducing on macOS

<!-- --8<-- [start:macos] -->
macOS inflates anything that yields to the event loop. One asyncio loop iteration costs about 12 µs
there, because `KqueueSelector.select(0)` is a 12.2 µs syscall, against 0.31 µs for
`EpollSelector.select(0)` in the Linux container. `asyncio.gather` on one coroutine costs 42 µs on
macOS and 5.0 µs on Linux. The health check pays for one `gather` per probe, and FastMCP's anyio task
groups also yield to the loop on every tool call: FastMCP's baseline is 670 µs per tool call on macOS against
517 µs on Linux. A Mac misranks those two items; run `frameworks/loop_cost.py` to see the numbers on
the machine at hand.
<!-- --8<-- [end:macos] -->

## 9. Reproducing

Everything runs from this directory against an interpreter that has `lite_bootstrap`, `fastapi`,
`uvicorn`, `structlog`, `sentry-sdk`, the OpenTelemetry SDK and
`prometheus-fastapi-instrumentator` importable - the repo's own `.venv` does. Each runner
re-invokes `sys.executable` once per scenario, because none of the patching these libraries do at
import or init time can be undone in-process.

```bash
cd benchmarks

# per-instrument breakdown and the tuned stack (section 4)
../.venv/bin/python run.py stack async bare,log,prom,sentry,otel,full,full_all_tuned

# the two OpenTelemetry knobs (section 4a)
../.venv/bin/python run.py stack async otel,otel_exclude_spans,otel_sampler,otel_tuned

# the Sentry ablation, where every familiar knob turns out to be a no-op (section 4b)
../.venv/bin/python run.py sentry async off,errors_only,errors_only_lean,errors_only_no_integrations,errors_only_no_txn

# cost per log record (section 4c)
../.venv/bin/python run.py sentry logging off,errors_only,errors_only_no_sentry_logs,errors_only_logging_lean

# the headline numbers, over real sockets - needs `ab` on PATH
../.venv/bin/python run_http.py stack async bare,full,full_all_tuned

# what a scenario gives up, and where the time goes inside one
../.venv/bin/python verify.py errors_only errors_only_no_txn errors_only_logging_lean errors_only_skip_txn
../.venv/bin/python micro.py
../.venv/bin/python profile_one.py sentry errors_only
../.venv/bin/python profile_one.py sentry errors_only --callers 'Random.seed'
```

`run.py <suite> --list` prints the scenario names; they are defined in `sentry_scenarios.py`
and `stack_scenarios.py`.
Scenarios whose name implies a fix that does not exist yet (`errors_only_skip_txn`,
`errors_only_lazy_sample_rand`) monkeypatch sentry-sdk to simulate it, so the value of a proposed
change can be measured before anyone writes it. The stack suite no longer patches anything: every
scenario there, `full_all_tuned` included, is reachable through `FastAPIConfig`.

`repro_sentry_txn.py` is deliberately standalone - it is the repro pasted into
[sentry-python#7400](https://github.com/getsentry/sentry-python/issues/7400) and imports nothing
from this directory.

Every number here was measured on sentry-sdk 2.67.1. The scripts also run on 3.x, which builds no
transaction while tracing is off, so the patched scenarios, `errors_only_txn_endpoint_style` and
`repro_sentry_txn.py --patched` exist only on 2.x. On 3.x, `micro.py` times `continue_trace` and
the root `start_span` in place of the `Transaction` calls. 3.x also leaves `LoggingIntegration` out
of its default integrations, so its `errors_only` records no log breadcrumbs.

Numbers are machine-specific and move a few percent run to run; the ratios and the ordering are
the durable part. Everything here was measured in one session on one idle machine, which is the
only way the columns are comparable to each other.

### The framework suites (sections 4d and 8)

These run from `frameworks/`. Each suite is a `<suite>_suite.py` whose `SCENARIOS` keys are the
scenario names, and the first scenario in a list is the baseline the rest are compared against.
`frameworks/common.py` loads `driver.py` from this directory by path, and the runners start
`stub_otlp.py` themselves.

The Linux numbers came from a container rather than the Mac, for the reason in section 8h. To build
an equivalent, start a Debian container with `--cpus 2`, install Python 3.14 and `ab` (Debian's
`apache2-utils`), copy the repository in and run `uv sync --all-extras` there. Granian is not a
project dependency, so add it to that environment with `uv pip install granian`; uvicorn already
comes in with the extras, through fastmcp. The FastStream suite needs a Redis 8 the container can reach, for example
a `redis:8` container on the same Docker network, and reads its address from `REDIS_URL` (default
`redis://127.0.0.1:6379`).

```bash
cd benchmarks/frameworks

# FastAPI and Litestar, in-process (sections 4d and 8b)
../../.venv/bin/python bench.py fastapi bare,log_mw,prom,otel,otel_excl,otel_0,sentry,health,full --repeat 2
../../.venv/bin/python bench.py litestar bare,log_log3,log_mw,prom,otel,otel_excl,otel_1_excl,otel_0,sentry,full --repeat 2
../../.venv/bin/python bench.py litestar health_ping,health,health_otel,health_otel_nospan --repeat 2

# Litestar on Granian, over real sockets (section 8c); needs granian in the environment and `ab` on PATH
../../.venv/bin/python run_http.py litestar bare,otel,otel_excl,prom,log_mw,sentry,health,full --repeat 2

# FastStream per consumed message, then per publish (section 8d)
REDIS_URL=redis://redis:6379 ../../.venv/bin/python bench.py faststream log,bare,prom,otel,otel_0,sentry,full --repeat 3
REDIS_URL=redis://redis:6379 ../../.venv/bin/python bench.py faststream log@pub,prom@pub,otel@pub,sentry@pub --repeat 3

# FastMCP per tool call (section 8e): fewer ops, each call is about half a millisecond
../../.venv/bin/python bench.py fastmcp bare,log_mw,prom,otel,otel_10,sentry,full --repeat 3 --ops 1500 --warmup 300

# cost per log call (section 8f); subtract the noop row
../../.venv/bin/python bench.py logging noop,info,debug_filtered,info_sentry,stdlib_info,native_bytes --repeat 2 --ops 50000

# the loop-iteration cost behind section 8h, and a cProfile of one scenario
../../.venv/bin/python loop_cost.py
../../.venv/bin/python one.py --suite litestar --scenario full --ops 3000 --profile
```

`bench.py` prints the median and the minimum of the repeat medians and the worst spread between
rounds; rerun a scenario whose spread is above about 20%.
