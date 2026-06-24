# Bootstrappers

A bootstrapper takes one framework config, decides which instruments apply,
and drives their lifecycle. It is the user-facing entry point.

## The hierarchy

`BaseBootstrapper` (`lite_bootstrap/bootstrappers/base.py`) is an `abc.ABC`,
generic over `ApplicationT`. Five concrete bootstrappers exist:

- `FastAPIBootstrapper`
- `LitestarBootstrapper`
- `FastStreamBootstrapper`
- `FastMcpBootstrapper`
- `FreeBootstrapper` — no web framework; just the instruments.

Each declares `instruments_types: ClassVar[list[type[BaseInstrument]]]` (the
instruments it can run) and implements `_prepare_application()`, `is_ready()`,
and the `not_ready_message` property. (`FreeBootstrapperConfig` exists as a
backward-compat alias for `FreeConfig`.)

## Skip ordering at construction

`BaseBootstrapper.__init__` loops over `instruments_types` and decides each
instrument's fate in a fixed order:

1. **`is_configured(config)`** runs first. If False, the user's config indicates
   the instrument should not run — it is **silently skipped** and appended to
   `skipped_instruments: list[tuple[type[BaseInstrument], str]]` (the class plus
   its `not_ready_message`). No warning. This runs before instantiation so a
   missing optional dependency can't blow up in a dataclass default before we
   even decide the user opted out.
2. **`check_dependencies()`** runs only for configured instruments. If the
   optional package is missing, this is a genuine deployment surprise: the
   bootstrapper emits an `InstrumentDependencyMissingWarning` (and a
   `logger.warning`) and skips the instrument.
3. Otherwise it **instantiates** the instrument and appends it to `instruments`.

`InstrumentDependencyMissingWarning` is a `UserWarning` subclass (under the base
`InstrumentSkippedWarning`); filter it like any warning category.

## Instrument registry and teardown

The bootstrapper holds `instruments` (live instances) and runs them as a
registry:

- `bootstrap()` calls `bootstrap()` on each instrument **in order**, then
  returns the prepared application. It is idempotent: if already bootstrapped it
  re-runs `_prepare_application()` without re-bootstrapping instruments.
- `teardown()` calls `teardown()` on each instrument **in reverse**. It is
  idempotent via the `is_bootstrapped` guard — it returns immediately when not
  bootstrapped. Per-instrument teardown errors are collected and re-raised as a
  `TeardownError` after all instruments have been attempted, so one failure does
  not strand the rest. Cached runtime state in `LoggingInstrument` and
  `OpenTelemetryInstrument` is reset inside `try/finally`.

## Summary logging

After the construction loop, `__init__` emits one INFO-level summary line listing
configured + skipped instruments. It uses stdlib `logging` (composes with the
user's logging setup and with pytest's `caplog`); default Python logging
suppresses INFO, so opt in via `logging.basicConfig(level=logging.INFO)`.

The same string is produced by the public `build_summary()` method, callable at
any later point (REPL, health endpoint) regardless of log-level filtering. To
inspect skips programmatically, iterate `bootstrapper.skipped_instruments`.

## Teardown-on-shutdown attach

Each app-bearing bootstrapper wires its `teardown` into the framework's shutdown
lifecycle from `__init__`, through one shared seam:
`BaseBootstrapper._attach_teardown_once(target, attach)`. That method owns the
double-attach guard — it tags the attach target with a
`_lite_bootstrap_teardown_attached` marker, so a second bootstrapper on the same
app warns and skips rather than stacking a second teardown hook. Only the `attach`
thunk is framework-specific:

- **FastAPI** — merge a lifespan context manager (`_wrap_lifespan`); target is the app.
- **Litestar** — append to `application_config.on_shutdown`; target is the
  `AppConfig` (the built `Litestar` app is slotted and is never tagged).
- **FastStream** — register via `application.on_shutdown(...)`; target is the app.
- **FastMCP** — add a `_TeardownProvider` whose async lifespan runs teardown; target
  is the app (FastMCP exposes no `on_shutdown` API).
- **Free** — no app, no shutdown lifecycle; not wired.

The guard is uniform: the same marker and warning apply to all four app-bearing
frameworks. `attach` is typed `Callable[[], object]` because some hooks (FastStream's
`on_shutdown`) return the callback.

## App-tagging sentinel convention

When a bootstrapper must tag a user-supplied framework app (FastAPI, FastMCP,
Litestar, FastStream) with internal state, it stores a direct attribute prefixed
`_lite_bootstrap_` rather than squatting in framework namespaces like Starlette's
`application.state`. The canonical example is the teardown guard's
`_lite_bootstrap_teardown_attached` marker, read via
`getattr(target, BaseBootstrapper._TEARDOWN_MARKER, False)` (no SLF violation) and
written via `setattr` inside `_attach_teardown_once`.
