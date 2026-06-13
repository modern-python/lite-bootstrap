# lite-bootstrap — Bug & Refactor Audit

**Date:** 2026-05-31
**Scope:** Full read of `lite_bootstrap/` and `tests/`
**Deliverable:** Prioritized findings report. No code changes.

Findings are grouped by severity. Each entry cites the source location, explains
what's wrong, and notes the linked test gap (if any). IDs are stable so a follow-up
plan can reference them.

---

## 1. Critical bugs (real, observable, untested)

### CRIT-1 · `enable_offline_docs` redoc URL ignores `root_path`

**File:** `lite_bootstrap/helpers/fastapi_helpers.py:48-58`

The redoc handler builds `redoc_js_url=f"{static_path}/redoc.standalone.js"`
with no `request.scope["root_path"]` prefix. The swagger handler above it
(lines 37-46) correctly prepends `root_path`. Result: behind a reverse proxy
or mount, swagger works and redoc 404s on its assets.

Reinforcing test gap: `tests/test_fastapi_offline_docs.py:32-43`
(`test_fastapi_offline_docs_root_path`) asserts on swagger asset URLs but
never on redoc. The bug is invisible because the regression suite never looks.

**Fix shape:** turn `redoc_html` into a function that takes a `Request`
(matching the swagger handler), read `root_path` from scope, prepend to the
redoc JS URL and the OpenAPI URL. Add an assertion to the existing root_path
test.

### CRIT-2 · `OpenTelemetryInstrument.teardown()` doesn't shut down the tracer provider

**File:** `lite_bootstrap/instruments/opentelemetry_instrument.py:92-135`

`bootstrap()` creates a `TracerProvider`, registers `BatchSpanProcessor` /
`SimpleSpanProcessor`, and stores nothing on `self`. The local `tracer_provider`
goes out of scope. `teardown()` only calls `uninstrument()` on the
instrumentors — it never calls `tracer_provider.shutdown()` or `force_flush()`.

Consequence: spans buffered in the `BatchSpanProcessor` are not flushed on
graceful shutdown. Trace data loss.

**Fix shape:** store the `TracerProvider` on the instance (requires either
dropping `frozen=True` for this field or using `object.__setattr__`, matching
the pattern already used elsewhere — see REF-6), and add
`tracer_provider.shutdown()` to `teardown()`. Add a test that exercises a
flushable processor and asserts on shutdown behavior.

### CRIT-3 · Litestar double-teardown not guarded

**File:** `lite_bootstrap/bootstrappers/litestar_bootstrapper.py:283-286`

`__init__` does `self.bootstrap_config.application_config.on_shutdown.append(self.teardown)`.
A user who manually wraps `bootstrap()` / `teardown()` (e.g. in a `try/finally`,
or in tests) will trigger two teardowns when Litestar then fires its shutdown
event. The base `teardown()` (`bootstrappers/base.py:82-93`) is not idempotent
— it iterates `self.instruments` and calls `teardown()` on each. Many
instruments are not idempotent themselves: `LoggingInstrument.teardown()` will
try to close already-closed handlers; the `OpenTelemetryInstrument` (once
CRIT-2 is fixed) will double-shutdown a tracer provider, etc.

FastAPI sidesteps this because its `lifespan_manager` is a single-shot
asynccontextmanager whose `finally` runs once. FastStream has the same
pattern as Litestar (`faststream_bootstrapper.py:191-193`) — also at risk.

**Fix shape:** make `BaseBootstrapper.teardown()` idempotent by checking
`if not self.is_bootstrapped: return` at the top, before any work. The flag
is already set to `False` at the start. Re-order so the guard fires first.
Add a regression test.

---

## 2. High-priority design issues

### DES-1 · Per-framework instrument subclasses are pure type-annotation boilerplate

**Files:** all three framework bootstrappers
(`fastapi_bootstrapper.py`, `litestar_bootstrapper.py`, `faststream_bootstrapper.py`)

There are roughly 12 subclasses of the form:

```python
@dataclasses.dataclass(kw_only=True, frozen=True)
class FastAPILoggingInstrument(LoggingInstrument):
    bootstrap_config: FastAPIConfig
```

They exist solely to narrow the `bootstrap_config` field's type so the
framework-specific bootstrap code can call `self.bootstrap_config.application`
without type-checker complaints. They contribute zero behavior. The same
trick repeats for Sentry, Logging, OpenTelemetry, etc., across all three
bootstrappers.

**Refactor shape:** make `BaseInstrument` generic in its config type:

```python
class BaseInstrument(Generic[ConfigT]):
    bootstrap_config: ConfigT
```

Then `LoggingInstrument(BaseInstrument[LoggingConfig])`, and at the
bootstrapper level instantiate `LoggingInstrument[FastAPIConfig]`. Only
instruments that *also* do framework-specific work (CORS middleware install,
healthcheck route registration, OTel middleware wiring) need real subclasses.

Estimated reduction: ~150 lines of cargo-cult. Improves discoverability
because the only subclasses that remain are the ones that matter.

### DES-2 · `opentelemetry_service_name` / `opentelemetry_namespace` duplicated across two configs

**Files:** `instruments/opentelemetry_instrument.py:36-49`,
`instruments/pyroscope_instrument.py:12-19`

Commit `7137776` added these fields to `PyroscopeConfig` so the pyroscope
instrument can be used standalone (without inheriting from
`OpentelemetryConfig`). They already exist on `OpentelemetryConfig`. In
`FreeBootstrapperConfig(LoggingConfig, OpentelemetryConfig, PyroscopeConfig, SentryConfig)`
this works only because both declarations have identical type and default —
MRO resolves to `OpentelemetryConfig`'s version. If anyone ever changes a
default on one side without the other, the inconsistency will be silent.
Python's dataclass machinery does not warn on duplicate field declarations
across MRO.

**Fix shape:** extract a small mixin
(e.g. `OpenTelemetryServiceFieldsConfig`) that holds the two fields and have
both `OpentelemetryConfig` and `PyroscopeConfig` inherit from it. Alternative:
push the fields onto `BaseConfig` if they're broadly useful.

### DES-3 · `BaseConfig.from_object` semantics differ from `from_dict` and aren't documented

**File:** `instruments/base.py:16-29`

- `from_dict` includes any key present in the dict regardless of value
  (including `None`).
- `from_object` filters with `value is not None` — an attribute explicitly set
  to `None` on the source object is dropped and the dataclass default kicks
  in.

Test coverage (`tests/test_config.py:32-51`) only exercises the
"all populated" case. The asymmetry is either intentional (and undocumented)
or an oversight. Either way, a user migrating between `from_dict` and
`from_object` will hit surprising behavior.

**Fix shape:** decide the contract, document it on the methods, add tests
that pin the chosen semantics, and consider unifying.

### DES-4 · `skip_sentry` leaks into Sentry `contexts.structlog`

**File:** `instruments/sentry_instrument.py:19-21, 56-69`

`IGNORED_STRUCTLOG_ATTRIBUTES` strips `event`/`level`/`logger`/`tracing`/
`timestamp`/`exception` before attaching the rest of the structlog payload to
`event["contexts"]["structlog"]`. It does **not** include `skip_sentry`. The
function returns `None` when `loaded_formatted_log.get("skip_sentry")` is
truthy (suppressing the event), but for any falsy value (`False`, missing
key, empty string) the flag isn't stripped and ends up as Sentry context
noise.

**Fix shape:** add `"skip_sentry"` to `IGNORED_STRUCTLOG_ATTRIBUTES`. One-line
change. Add a test asserting the field is not present in attached context.

### DES-5 · Dead `is_X_installed` checks in `is_ready()`

**Files:** `instruments/sentry_instrument.py:100-101`,
`instruments/logging_instrument.py:139-140`,
`instruments/opentelemetry_instrument.py:82-86`,
`instruments/pyroscope_instrument.py:28-29`

Each `is_ready()` ends with `and import_checker.is_X_installed`. But
`_register_or_skip` in `bootstrappers/base.py:44-55` calls
`check_dependencies()` first; if that returns False, the instrument is
skipped and `is_ready` is never called. By the time `is_ready` runs, the
`and is_X_installed` conjunct is provably True.

Not a bug — just confusing dead code that makes the lifecycle harder to
reason about. (`_register_or_skip` runs `check_dependencies()` first; only on
True does it instantiate and call `is_ready()`. See `bootstrappers/base.py:44-64`.)

**Fix shape:** delete the redundant conjuncts. Document somewhere
(`BaseInstrument` docstring or a CONTRIBUTING note) that `is_ready` is
called *after* `check_dependencies` has already passed.

---

## 3. Refactor opportunities

### REF-1 · Duplicated `_build_excluded_urls()` in FastAPI and Litestar OTel instruments

**Files:** `bootstrappers/fastapi_bootstrapper.py:120-126`,
`bootstrappers/litestar_bootstrapper.py:181-187`

The two methods are character-for-character identical. Hoist to
`OpenTelemetryInstrument` (the base in `instruments/`) and let framework
subclasses inherit. Combined with DES-1, the framework subclass might not
be needed at all.

### REF-2 · Dead defensive check in `LitestarLoggingInstrument.bootstrap()`

**File:** `bootstrappers/litestar_bootstrapper.py:157-174`

`if import_checker.is_structlog_installed and import_checker.is_litestar_installed:`
cannot be False: the instrument would not have been registered without
structlog (its base `is_ready` requires it), and `litestar` is installed by
the time `LitestarBootstrapper` could exist at all. Remove the branch and
unindent.

### REF-3 · `BaseInstrument` uses `abc.ABC` but defines no abstract methods

**File:** `instruments/base.py:32-47`

`bootstrap`, `teardown`, `is_ready`, `check_dependencies` all have concrete
defaults (no-op or `return True`). The `abc.ABC` parent serves no purpose,
and the `# noqa: B027` markers exist only to silence ruff complaints about
empty-method-on-abstract-base. Either:

- Drop `abc.ABC` and the noqa markers — it's a plain base class.
- Or genuinely make at least one method abstract.

The first is simpler given how the class is actually used.

### REF-4 · `logging_instrument.py` is 212 lines doing four jobs

**File:** `instruments/logging_instrument.py`

The module mixes: tracer injection function (lines 21-40), protocol
definitions (43-55), `MemoryLoggerFactory` and serializer (57-101),
`LoggingConfig` (104-114), and `LoggingInstrument` (117-211). It also has
three separate `if import_checker.is_structlog_installed:` blocks at
module scope defining different symbols (lines 17, 57, 100).

**Refactor shape:** split into `logging_factory.py` (MemoryLoggerFactory +
serializer + the protocols only it cares about) and `logging_instrument.py`
(config + instrument + tracer injection). Each file has one
`if is_structlog_installed:` gate.

### REF-5 · `swagger_instrument.py` and `prometheus_instrument.py` base classes carry almost no logic

**Files:** `instruments/swagger_instrument.py`, `instruments/prometheus_instrument.py`

`SwaggerInstrument` has no methods at all. `PrometheusInstrument` has only
`is_ready` + `not_ready_message`. The real behavior is in framework
subclasses. Once DES-1 lands and type-only subclasses go away, these base
files could:

- Collapse into the bootstrapper modules that consume them, or
- Stay as pure config holders with a one-line docstring explaining the
  split (config in instruments, behavior in bootstrappers).

Either is fine; the current state is mildly confusing.

### REF-6 · `frozen=True` + `object.__setattr__` workaround for caches

**Files:** `instruments/logging_instrument.py:160-169`,
`bootstrappers/fastapi_bootstrapper.py:57-72`

`LoggingInstrument._logger_factory` and `FastAPIConfig.application` both use
`object.__setattr__` to mutate "frozen" dataclasses. The frozen claim is
partly false, and the workaround obscures mutable state. Pick a model:

- **Truly immutable:** factory and application are built outside the
  dataclass and passed in. Defaults are computed at the call site, not in
  `__post_init__` or property accessor.
- **Pragmatic:** drop `frozen=True` for these specific dataclasses.

Mixing the two patterns is the worst case.

### REF-7 · Hardcoded `timeout=5` in FastStream health check

**File:** `bootstrappers/faststream_bootstrapper.py:100-104`

`broker.ping(timeout=5)` is hardcoded. For users with slow brokers (large
Redis clusters under load, message queues with cold connections), this is
a footgun. Add a config field: `health_check_broker_timeout: float = 5.0`
on `HealthChecksConfig` (or a FastStream-specific config field if
`HealthChecksConfig` shouldn't carry broker concepts).

---

## 4. Test coverage gaps

The most consequential gaps are the ones letting the critical bugs hide.

### TEST-1 · Redoc + `root_path` untested (hides CRIT-1)

**File:** `tests/test_fastapi_offline_docs.py:32-43`

`test_fastapi_offline_docs_root_path` asserts swagger asset URLs include
`/some-root-path/` but never inspects redoc output. Adding two `assert
"/some-root-path/static/redoc.standalone.js" in response.text` lines
(and the redoc fetch) would catch CRIT-1 immediately.

### TEST-2 · OTel span flush on teardown untested (hides CRIT-2)

No test in `tests/instruments/test_opentelemetry_instrument.py` exercises
shutdown semantics. Write a test that:

1. Sets `opentelemetry_endpoint` so a `BatchSpanProcessor` is added.
2. Records spans inside `bootstrap()`/`teardown()`.
3. Uses an `InMemorySpanExporter` to verify spans were flushed before
   teardown returned.

Or, more narrowly: assert that `tracer_provider.shutdown()` is called.

### TEST-3 · Litestar double-teardown untested (hides CRIT-3)

`tests/test_litestar_bootstrap.py` doesn't exercise the case of manual
`bootstrapper.teardown()` followed by Litestar's `on_shutdown` firing.
Add a test that calls teardown twice and asserts no exception.

### TEST-4 · No standalone test files for CORS / HealthChecks / Prometheus / Swagger instruments

These are only covered transitively via the bootstrapper integration tests.
A regression in (say) `CorsInstrument.is_ready()` would surface as a noisy
FastAPI bootstrap test failure. Standalone test files would localize
diagnosis.

### TEST-5 · `BaseConfig.from_object` edge cases untested

Related to DES-3. Not tested:

- Source attribute = `None` (filtered out today, default wins).
- Source attribute missing entirely (`getattr(obj, field, None)` returns
  None — filtered).
- Falsy values like `False` / `""` / `[]` (these *do* go through today
  because `is not None` accepts them).

Pin whichever semantics you choose with tests.

### TEST-6 · `BaseConfig.from_dict` "unknown key dropped" not explicitly asserted

`tests/test_config.py:8-29` passes `"extra_key": "extra_value"` but only
verifies the kept keys (and that `cls(**...)` didn't raise). A regression
to "raise on unknown key" would pass.

### TEST-7 · `is_valid_path` has zero negative tests

`helpers/path.py:5` regex is enforced for `prometheus_metrics_path` and
`swagger_path`. No test exercises invalid inputs: empty string, `"foo"`
(no leading slash), `"/path with space"`, `"../escape"`. A regression to
the regex would land silently.

### TEST-8 · `LoggingInstrument` lifecycle replay untested

`bootstrap → teardown → bootstrap` cycle is never run. Related to the
`_unset_handlers` permanence issue (see LOW-8 below).

---

## 5. Low-priority / cosmetic

### LOW-1 · `wrap_before_send_callbacks` `if not callback:` should be `if callback is None`

**File:** `instruments/sentry_instrument.py:81-82`

Idiomatically callables are always truthy unless they define `__bool__`.
`if not callback` is sloppy.

### LOW-2 · `SentryConfig.sentry_before_send` typing is degenerate

**File:** `instruments/sentry_instrument.py:36`

`Callable[[Any, Any], Any | None] | None` collapses to `Callable[..., Any] | None`
because `Any | None == Any`. The intended type is sentry's `EventProcessor`
(already imported under `TYPE_CHECKING` in the same file). Replace.

### LOW-3 · `_format_span` uses `os.linesep`

**File:** `instruments/opentelemetry_instrument.py:25-26`

On Windows that's `\r\n`. OTel SDK convention is `\n`. Use `"\n"` literal.

### LOW-4 · `FastAPIConfig.application` inconsistent default pattern

**File:** `bootstrappers/fastapi_bootstrapper.py:50, 57-65`

Declares `default=None` with a `# ty: ignore[invalid-assignment]` and patches
the field in `__post_init__` via `object.__setattr__`. Litestar's equivalent
(`bootstrappers/litestar_bootstrapper.py:111`) uses
`default_factory=lambda: AppConfig()`. Pick one pattern. Related to REF-6.

### LOW-5 · `LitestarOpenTelemetryInstrumentationMiddleware._otel_apps` keys by `id(next_app)`

**File:** `bootstrappers/litestar_bootstrapper.py:75-97`

Python object IDs can be reused after GC. ASGI apps are stable in practice,
so this is theoretical. Add a one-line comment acknowledging the assumption.
The recent commit (`5578f63`) added this cache — it's an explicit perf
trade-off, just under-documented.

### LOW-6 · `MemoryLoggerFactory.__init__` takes 5 logging-config kwargs

**File:** `instruments/logging_instrument.py:60-73`

Could accept a small config dataclass for readability. Cosmetic; the long
list is annotated and clear enough.

### LOW-7 · `FreeBootstrapperConfig` naming inconsistency

**File:** `bootstrappers/free_bootstrapper.py:12`

Has the `Bootstrapper` infix; siblings are `FastAPIConfig` / `LitestarConfig` /
`FastStreamConfig`. Rename to `FreeConfig` (with a deprecation alias) or
rename the siblings (more invasive). Trivial.

### LOW-8 · `LoggingInstrument._unset_handlers` permanently mutates target loggers

**File:** `instruments/logging_instrument.py:146-148`

Sets `logging.getLogger(name).handlers = []` for each entry in
`logging_unset_handlers`. There's no symmetric restoration in `teardown()`.
On `bootstrap → teardown → bootstrap`, the second bootstrap sees the loggers
already cleared (no problem); but other code in the same process that
relies on those loggers after teardown will see broken loggers. Probably
acceptable for the intended "microservice runs until process exit" model;
worth a docstring.

### LOW-9 · `LoggingInstrument.teardown()` forces root logger to WARNING

**File:** `instruments/logging_instrument.py:202-211`

Unconditionally resets root logger level to WARNING after closing handlers.
If a user had configured a different default outside the bootstrapper,
this is destructive. Acceptable for the intended use case, but undocumented.

### LOW-10 · `OpentelemetryConfig` capitalization inconsistency

**File:** `instruments/opentelemetry_instrument.py:36`

`OpentelemetryConfig` (lowercase `t`) doesn't match the conventional
`OpenTelemetry` capitalization. PR6 introduced
`OpenTelemetryServiceFieldsConfig` (uppercase `T`) as a mixin parent,
making the inconsistency more visible — same module, two casings for the
same product name. Backfilled from PR6's code review and tracked into
PR15 alongside LOW-7. Rename with a silent backward-compat alias
(`OpentelemetryConfig = OpenTelemetryConfig`) to preserve existing
imports.

---

## Appendix — Notes on scope

A handful of additional observations didn't make the cut:

- `FastStreamBootstrapper`'s `_define_health_status` returns `False` when
  `application` is falsy — `application` will never be falsy in practice
  (it's always an `AsgiFastStream` instance from `_make_asgi_faststream`).
  Defensive code that never fires.
- `set_tracer_provider` is process-global. Two bootstrappers in the same
  process would conflict. This is an OTel SDK constraint, not a
  lite-bootstrap issue.
- `_register_or_skip` uses `stacklevel=4` for `warnings.warn`. The number
  is fragile (depends on call depth from user code through bootstrapper
  `__init__` → base `__init__` → `_register_or_skip`). It happens to be
  correct today. Worth a comment in the code if not already there.

These were noted but not surfaced as actionable findings because the cost
of acting on them outweighs the cost of leaving them.
