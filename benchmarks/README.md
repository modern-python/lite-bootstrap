# What the observability stack costs a lite-bootstrap FastAPI service

The question comes from the PyCon Russia 2026 talk
[«Делай это, чтобы увеличить RPS в 10 раз»](https://pycon.ru/delay_eto_chtoby_uvelichit_rps_v_10_raz)
by Maxim Sakhno: popular libraries, used per their documentation, quietly eat most of a FastAPI
service's RPS.

## 1. What the source material actually says

I could not validate the talk's claims against the talk itself. The only public material at the
time of measuring (September 2026) was the abstract on pycon.ru: the talk takes a typical FastAPI
app, finds bottlenecks in popular libraries, and removes them for a ~10x RPS gain "without
changing the stack or the architecture". No slides, no video, no article. PyCon RU publishes
recordings roughly a month after the event; the conference was 24-25 July 2026. **Nothing below is a quote from the talk.**
It is an independent measurement of the four libraries lite-bootstrap wires up, which is the
category of claim the talk makes.

The closest public corroboration for the Sentry part is
[getsentry/sentry-python#2116](https://github.com/getsentry/sentry-python/issues/2116)
(open since 2023): a Starlette app dropping from ~2000 to ~1000 RPS after adding the SDK, against
Sentry's own claim of
[under 1 ms of instrumentation overhead per request](https://docs.sentry.io/product/insights/performance-overhead/).
Both are true at once, and that is the whole story: the absolute cost is small, and it is
enormous relative to a handler that does nothing.

**Verdict on the 10x claim: credible, for a thin endpoint, once the whole documented stack is on.**
Measured below: 14.5x in-process, 3.3x through a real server, of which roughly half is recoverable
without giving up observability.

## 2. Method

Two suites - `sentry` (one `sentry_sdk.init()` knob at a time) and `stack` (the lite-bootstrap
instruments, configured through `FastAPIBootstrapper`) - measured three ways:

- **In-process** (`run.py`) - drives the ASGI app directly (`await app(scope, receive, send)`), no
  sockets, no HTTP parsing. Isolates library cost; overstates the *relative* impact because the
  baseline is unrealistically fast.
- **Real server** (`run_http.py`) - uvicorn, single worker, access log off, loaded with
  `ab -k -c 16 -n 20000`. Verified the load generator is not the ceiling (baseline plateaus at
  ~8.7k RPS by c=64, vs 7.9k measured at c=16).
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

Real server, uvicorn + `ab -k`, trivial async endpoint:

| config | RPS | µs/req | vs bare |
|---|---:|---:|---|
| bare FastAPI | 7978 | 125.3 | - |
| full lite-bootstrap stack (otel + prometheus + structlog + sentry) | 2389 | 418.6 | **−70%** |
| same stack, tuned (§6) | 4187 | 238.8 | −48% |

Same endpoint plus three structlog records per request:

| config | RPS | µs/req | vs bare |
|---|---:|---:|---|
| bare | 5716 | 175.0 | - |
| full stack | 2013 | 496.7 | **−65%** |
| tuned | 3476 | 287.7 | −39% |

In-process (SDK cost isolated, baseline 16.2 µs/req): full stack 61628 → 4268 RPS, **14.5x**.
Tuned recovers it to 9150, **2.14x** over the untuned stack.

So the tuning is worth **+75% RPS** on the real server and the untuned stack really does cost an
order of magnitude of a do-nothing handler's throughput.

## 4. Per-instrument breakdown

In-process, each instrument alone, baseline 15.8 µs/req:

| instrument | RPS | +µs/req | share of full stack |
|---|---:|---:|---|
| `LoggingInstrument` (configured, no logs emitted) | 62680 | +0.1 | ~0% |
| `PrometheusInstrument` | 29983 | +17.5 | 8% |
| `SentryInstrument` (tracing off) | 13449 | +58.5 | 27% |
| `OpenTelemetryInstrument` | 7356 | **+120.1** | 55% |
| all four | 4293 | +217.1 | |

Costs are close to additive (0.1 + 17.5 + 58.5 + 120.1 = 196 vs 217 measured). **OpenTelemetry is
twice Sentry**, which was not the expected ordering, and structlog's instrument costs nothing
until you actually log.

### 4a. OpenTelemetry: two knobs lite-bootstrap does not expose

| scenario | RPS | µs/req | gain |
|---|---:|---:|---|
| `otel` as lite-bootstrap configures it | 7375 | 135.6 | - |
| `+ exclude_spans=["receive", "send"]` | 9755 | 102.5 | −33.1 µs |
| `+ ParentBased(TraceIdRatioBased(0.01))` sampler | 12484 | 80.1 | −55.5 µs |
| both | 15922 | 62.8 | **2.16x** |

1. `FastAPIInstrumentor.instrument_app` accepts `exclude_spans: list[Literal["receive","send"]]`.
   lite-bootstrap passes only `app`, `tracer_provider` and `excluded_urls`, so **every request
   produces three spans** - the server span plus one each for the ASGI `receive` and `send`
   events. Two thirds of the spans, one quarter of the cost, and almost nobody looks at them.
2. `OpenTelemetryInstrument.bootstrap()` constructs `TracerProvider(resource=resource)` with no
   sampler, which means the SDK default `parentbased_always_on`. **There is no configuration
   surface for a sampler anywhere in lite-bootstrap**, so a service cannot head-sample its own
   traces at all; every request is recorded, serialized and shipped. A 1% ratio sampler is worth
   55 µs/req here. (Sampling rate is a user decision, not a default to change - the gap is that
   it cannot be expressed.)

### 4b. Sentry: the cost is one thing, and it is not the one people tune

In-process ablation, Sentry only, baseline 15.6 µs/req:

| scenario | +µs | reading |
|---|---:|---|
| defaults (tracing off) | +61.3 | the number to beat |
| `attach_stacktrace=False` | +61.5 | no effect on the happy path |
| `max_breadcrumbs=0` | +62.0 | no effect - the crumb is still built |
| `disabled_integrations=[Stdlib, Modules, Dedupe, Excepthook, Threading]` | +61.4 | no effect |
| `default_integrations=False` (Starlette+FastAPI kept) | +61.9 | no effect |
| **`integrations=[]`, no framework integration** | **+0.4** | **all of it is the ASGI integration** |
| `auto_session_tracking=False` | +54.4 | sessions cost ~7 µs |
| `http_methods_to_capture=()` (no Transaction) | +27.2 | the Transaction costs ~34 µs |
| both of the above | +19.2 | |

The first block is the useful negative result: **every knob people reach for first buys nothing.**
All the cost is in `SentryAsgiMiddleware._run_app`, and most of it is a `Transaction` built and
thrown away because tracing is disabled.

Micro-benchmarks (`micro.py`):

| operation | µs |
|---|---:|
| `Random(trace_id)` - seeding Mersenne Twister | 6.42 |
| `_generate_sample_rand(trace_id)` | 6.99 |
| `Transaction(op, name, source)` | 9.63 |
| `scope.continue_trace(headers)` | 11.02 |
| `start_transaction(txn)` + exit, tracing **off** | 18.54 |
| `scope.generate_propagation_context(headers)` | 0.61 |
| `isolation_scope()` enter/exit | 2.25 |
| `scope.fork()` | 0.62 |
| `get_client()` | 0.14 (×17 per request) |

`Transaction.__init__` unconditionally calls `_generate_sample_rand(self.trace_id)`, which does
`Random(trace_id)` - a full Mersenne Twister seed, 6.4 µs. It is 5.9 µs even for `Random(1)`, so
the cost is the MT init, not the string hashing; deriving the same value arithmetically
(`int(trace_id, 16) / 2**128`) takes **0.23 µs, 27x cheaper**. This runs on every request even
when `traces_sample_rate is None`.

With `traces_sample_rate=1.0` the SDK costs +274 µs/req on the real server (2486 RPS, −68%).

### 4c. Logging: cost per record, not per request

Three records per request, in-process:

| scenario | +µs/req | delta |
|---|---:|---:|
| Sentry defaults | +99.7 | |
| `LoggingIntegration(sentry_logs_level=None)` | +92.9 | −1.9 µs/record |
| `LoggingIntegration(level=None, sentry_logs_level=None)` | +73.3 | −8.4 µs/record total |

Two handlers run per log record. `SentryLogsHandler.emit` calls `self.format(record)` *before* it
checks `has_logs_enabled(client.options)`, so with Sentry Logs disabled (the default, and
lite-bootstrap never sets `enable_logs`) every record is formatted an extra time for nothing.
`BreadcrumbHandler` then formats it again and builds a breadcrumb dict. `max_breadcrumbs=0` does
not help: the crumb is constructed before the deque drops it.

This hits lite-bootstrap directly because `LoggingInstrument` wires structlog through
`structlog.stdlib.BoundLogger`, so every structlog call goes through the patched
`logging.Logger.callHandlers` and pays both handlers.

## 5. What each saving actually costs you

Measured by capturing a real error event with an incoming `sentry-trace` header and inspecting the
envelope (`verify.py`):

| config | txn name | continues incoming trace | breadcrumbs |
|---|---|---|---|
| defaults | `/ping` | yes | yes |
| `http_methods_to_capture=()` | `/ping` | **no** | yes |
| `LoggingIntegration(level=None)` | `/ping` | yes | **no** |
| propagation kept, Transaction skipped (patched SDK) | `/ping` | yes | yes |

`http_methods_to_capture=()` is not free: the error event gets a fresh `trace_id` and no
`parent_span_id`, which breaks cross-service correlation of errors in Sentry. Acceptable when
distributed tracing is OpenTelemetry's job - as it is in any lite-bootstrap service that also runs
`OpenTelemetryInstrument` - and Sentry is only an error sink. Not acceptable otherwise.

The last row is the interesting one: replacing `Scope.continue_trace` with a version that keeps
`generate_propagation_context(headers)` and returns no Transaction loses **nothing** on the error
event and still saves ~30 µs/req. That is a pure upstream bug, not a trade-off.

Similarly, `exclude_spans=["receive","send"]` costs you the ASGI event spans and nothing else, and
`sentry_logs_level=None` costs nothing at all while Sentry Logs is disabled.

## 6. The tuned configuration

What "tuned" means in §3, all reachable through today's public API except the two OTel knobs:

```python
FastAPIConfig(
    # Sentry: OTel owns distributed tracing, Sentry is an error sink
    sentry_integrations=[
        StarletteIntegration(http_methods_to_capture=()),
        FastApiIntegration(http_methods_to_capture=()),
        LoggingIntegration(level=None, sentry_logs_level=None),
    ],
    sentry_additional_params={"auto_session_tracking": False},
    # OpenTelemetry: not expressible today, see issues
    #   exclude_spans=["receive", "send"] on FastAPIInstrumentor.instrument_app
    #   sampler=ParentBased(TraceIdRatioBased(0.01)) on TracerProvider
)
```

Trade-offs, in order of what you give up: log breadcrumbs on Sentry errors, Sentry release health,
Sentry-side trace correlation, 99% of OTel traces, ASGI event spans.

## 7. Filed issues

lite-bootstrap (all "possible improvement", nothing implemented):

- [#184](https://github.com/modern-python/lite-bootstrap/issues/184) OpenTelemetry sampler is not
  configurable (55 µs/req)
- [#185](https://github.com/modern-python/lite-bootstrap/issues/185) `exclude_spans` is never passed
  to `FastAPIInstrumentor` (33 µs/req)
- [#186](https://github.com/modern-python/lite-bootstrap/issues/186) Sentry `sentry_logs_level`,
  breadcrumb level and `auto_session_tracking` are not exposed (~9 µs/req plus ~2 µs/log record)
- [#187](https://github.com/modern-python/lite-bootstrap/issues/187) Document what the stack costs

sentry-python:

- [#7400](https://github.com/getsentry/sentry-python/issues/7400) A full `Transaction` is built and
  discarded per request when tracing is disabled (~34 µs)
- [#7401](https://github.com/getsentry/sentry-python/issues/7401) `_generate_sample_rand` seeds a
  Mersenne Twister per `Transaction`, eagerly, even when unsampled (6.4 µs; 27x cheaper
  arithmetically)
- [#7402](https://github.com/getsentry/sentry-python/issues/7402) `SentryLogsHandler.emit` formats
  the record before checking `has_logs_enabled` (~1.9 µs/record)
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
../.venv/bin/python verify.py errors_only_no_txn
../.venv/bin/python micro.py
../.venv/bin/python profile_one.py sentry errors_only
../.venv/bin/python profile_one.py sentry errors_only --callers 'Random.seed'
```

`run.py <suite> --list` prints the scenario names; they are defined in `sentry_scenarios.py`
and `stack_scenarios.py`.
Scenarios whose name implies a fix that does not exist yet (`errors_only_skip_txn`,
`otel_sampler`, `full_all_tuned`) monkeypatch the library to simulate it, so the value of a
proposed change can be measured before anyone writes it.

`repro_sentry_txn.py` is deliberately standalone - it is the repro pasted into
[sentry-python#7400](https://github.com/getsentry/sentry-python/issues/7400) and imports nothing
from this directory.

Numbers are machine-specific and move a few percent run to run; the ratios and the ordering are
the durable part. Everything here was measured in one session on one idle machine, which is the
only way the columns are comparable to each other.
