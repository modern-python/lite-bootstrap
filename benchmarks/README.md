# What the observability stack costs a lite-bootstrap FastAPI service

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

### 4a. OpenTelemetry: the two knobs that pay

| scenario | RPS | µs/req | gain |
|---|---:|---:|---|
| `otel` as lite-bootstrap configures it | 7267 | 137.6 | - |
| `+ opentelemetry_exclude_spans=["receive", "send"]` | 9651 | 103.6 | −34.0 µs |
| `+ opentelemetry_sampler=ParentBased(TraceIdRatioBased(0.01))` | 12154 | 82.3 | −55.3 µs |
| both | 15518 | 64.4 | **2.14x** |

1. `FastAPIInstrumentor.instrument_app` accepts `exclude_spans: list[Literal["receive","send"]]`,
   which `FastAPIConfig.opentelemetry_exclude_spans` passes through. It is empty by default, so
   **every request still produces three spans** - the server span plus one each for the ASGI
   `receive` and `send` events. Two thirds of the spans, one quarter of the cost, and almost
   nobody looks at them. Set it to `["receive", "send"]` to drop the two event spans.
2. `OpenTelemetryConfig.opentelemetry_sampler` is passed to the `TracerProvider`. Left unset, the
   SDK default `parentbased_always_on` applies and every request is recorded, serialized and
   shipped. A 1% ratio sampler is worth 55 µs/req here. The default stays always-on deliberately:
   sampling rate is a user decision, not something to pick on a service's behalf.

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

Three records per request, in-process:

| scenario | +µs/req | delta |
|---|---:|---:|
| sentry-sdk defaults | +101.1 | |
| `sentry_logs_level=None` (lite-bootstrap's default since #186) | +93.8 | −2.4 µs/record |
| also `sentry_logging_breadcrumb_level=None` | +72.4 | −9.6 µs/record total |

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
    sentry_auto_session_tracking=False,
    # OpenTelemetry: sampling is the single biggest saving here
    opentelemetry_exclude_spans=["receive", "send"],
    opentelemetry_sampler=ParentBased(TraceIdRatioBased(0.01)),
)
```
<!-- --8<-- [end:tuned] -->

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

## 8. Reproducing

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

Numbers are machine-specific and move a few percent run to run; the ratios and the ordering are
the durable part. Everything here was measured in one session on one idle machine, which is the
only way the columns are comparable to each other.
