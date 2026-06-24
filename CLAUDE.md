# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
just install        # Update lock file and sync all extras + lint group
just lint           # Format and lint (eof-fixer, ruff format, ruff check --fix, ty check)
just lint-ci        # CI lint in check-only mode (no auto-fix)
just test           # Run pytest with coverage
just test -- -k "test_name"  # Run a single test
just test-branch    # Run tests with branch coverage
```

All commands use `uv run` — do not invoke tools directly (e.g., use `uv run pytest`, not `pytest`).

## Architecture

**lite-bootstrap** bootstraps Python microservices with pre-configured observability instruments.

### Core pattern

```
BaseConfig (frozen dataclass, kw_only)
    └── Framework configs compose multiple instrument configs via multiple inheritance

BaseInstrument[ConfigT] (generic, non-frozen dataclass with slots)
    └── Instrument subclasses: lifecycle via bootstrap() / teardown(); skip check via is_configured() classmethod

BaseBootstrapper (abc.ABC)
    ├── FastAPIBootstrapper
    ├── LitestarBootstrapper
    ├── FastStreamBootstrapper
    ├── FastMcpBootstrapper
    └── FreeBootstrapper
```

### Key design decisions

Recent design context, bugs, and convention rationale: see the bug-audit findings in `planning/audits/` and the post-work reflections in `planning/retros/` (the audit arcs themselves are bundled under `planning/changes/`).

- **Optional dependencies**: Each instrument checks for its optional package via `import_checker.py` (`importlib.util.find_spec`). Instruments are skipped silently if the package is absent. Optional packages are imported inside `if import_checker.is_X_installed:` blocks; static analyzers that don't model this guard will report spurious "possibly unbound" diagnostics — the project uses `ty` which handles the pattern correctly.
- **Instrument skip ordering**: `BaseBootstrapper.__init__` runs `instrument_type.is_configured(config)` first (silent skip if the user's config indicates the instrument shouldn't run — populates `bootstrapper.skipped_instruments: list[tuple[type, str]]`); then `check_dependencies()` (emits `InstrumentDependencyMissingWarning` only for configured-but-dep-missing — the genuine deployment surprise); then instantiates. One `logger.info` summary line at the end lists configured + skipped instruments via `BaseBootstrapper.build_summary()`; that method is also publicly callable for post-construction debugging. Uses stdlib `logging` so it composes cleanly with the user's logging setup and with pytest's `caplog`.
- **Frozen configs, non-frozen instruments**: All `*Config` classes are `@dataclasses.dataclass(kw_only=True, frozen=True)`. All `*Instrument` classes lose `frozen=True` because two instruments (`LoggingInstrument`, `OpenTelemetryInstrument`) cache mutable runtime state (`_logger_factory`, `_tracer_provider`); Python's dataclass rules require the whole hierarchy to be non-frozen. `from_dict()` and `from_object()` filter unknown keys before constructing.
- **`FastAPIConfig.application` uses an `UnsetType` sentinel**: shared in `lite_bootstrap/types.py` as `UnsetType` + `UNSET` (singleton). `FastAPIConfig.__post_init__` checks `isinstance(self.application, UnsetType)` and replaces with a constructed `FastAPI()` via `object.__setattr__` (config stays frozen for user-facing immutability). A one-line comment in `__post_init__` documents the freeze bypass.
- **Instrument registry**: `BaseBootstrapper` holds a list of instrument instances; it calls `bootstrap()` on each in order and `teardown()` in reverse during shutdown.
- **Idempotent teardown**: `BaseBootstrapper.teardown()` returns immediately if `not self.is_bootstrapped`. Cached runtime state in `LoggingInstrument` and `OpenTelemetryInstrument` is reset inside `try/finally` so a raised shutdown leaves no stale references.
- **Logging ↔ Sentry integration**: `logging_instrument.py` renders structlog lines to JSON; the seam is `StructuredLogPayload.parse` in `logging_factory.py`, which reconstructs a line into `message`/`extra`/`skip_sentry` and owns the meta-key vocabulary (`STRUCTLOG_META_KEYS`, stripped from `extra`). `sentry_instrument.py`'s `enrich_sentry_event_from_structlog_log` (chained after the user's `before_send` via `wrap_before_send_callbacks()`) only maps the parsed payload onto the Sentry event — a truthy `skip_sentry` suppresses the event (checked before the message-presence test), else it lifts `message` and attaches `extra` under `contexts.structlog`. `IGNORED_STRUCTLOG_ATTRIBUTES` stays as a back-compat alias of `STRUCTLOG_META_KEYS`. The value object holds no Sentry-event-shape knowledge; adding a custom top-level meta-processor to the logging chain means extending `STRUCTLOG_META_KEYS` (cross-referenced at `tracer_injection`).
- **OTel ↔ Logging integration**: The logging instrument injects span/trace IDs from the active OpenTelemetry context into every log record.
- **`OpenTelemetryInstrument` is single-instance per process**: `bootstrap()` calls `opentelemetry.trace.set_tracer_provider(...)`, which the OTel SDK enforces as set-once via `_TRACER_PROVIDER_SET_ONCE.do_once(...)` (subsequent calls log `"Overriding of current TracerProvider is not allowed"` and have no effect). `teardown()` calls `shutdown()` on the provider (flushes batched spans, closes exporters) but cannot reset the process-global pointer. Construct one `OpenTelemetryInstrument` per process; do not bootstrap a second instance. Verified against `opentelemetry/trace/__init__.py:548-556`.

### Module layout

One file per instrument under `lite_bootstrap/instruments/`, one per framework under `lite_bootstrap/bootstrappers/`. Non-obvious files worth knowing:

- `lite_bootstrap/types.py` — `UnsetType` + `UNSET` singleton used as the "user did not supply this" sentinel (notably for `FastAPIConfig.application`).
- `lite_bootstrap/instruments/logging_factory.py` — `MemoryLoggerFactory`, factory config, structlog serializer, ASGI protocols. Split out of `logging_instrument.py` to keep each file scoped to one job.

### Optional dependency groups

See `[project.optional-dependencies]` in `pyproject.toml` for the full extras matrix.

## Workflow

Per-feature: brainstorming → spec in `planning/changes/YYYY-MM-DD.NN-<slug>/design.md` → writing-plans → plan in `planning/changes/YYYY-MM-DD.NN-<slug>/plan.md` → executing-plans / subagent-driven-development → requesting-code-review → finishing-a-development-branch. Each change is a folder bundle; `<slug>` is a kebab-case description, not a story ID; `.NN` is a zero-padded intra-day counter that breaks same-date ties so the timeline sorts stably. The implementing PR sets `status: shipped` and fills `pr` / `outcome` in the branch, alongside the code and promotes its conclusions into the affected `architecture/<capability>.md` — that hand-edit keeps `architecture/` true and is the only ship-time step; there is no folder move. The change listing is generated — run `just index`. A design decision taken without a code change — especially a candidate rejected with a load-bearing reason — is recorded as `planning/decisions/YYYY-MM-DD-<slug>.md` (the `decision.md` template, frontmatter `status: accepted|superseded`), each with a **Revisit trigger** so future reviews don't re-litigate it; listed by `just index`. See [`planning/README.md`](planning/README.md) for the conventions and [`planning/_templates/`](planning/_templates/) for copy-and-fill starting points.

**Spec** (`design.md`) captures the *thinking* — why, what the design is, trade-offs, scope. Written before code; rarely revised after merge. **Plan** (`plan.md`) captures the *sequencing* — the ordered checklist an executor walks; references the spec for the "why". **`architecture/`** captures the *invariants* of shipped systems — the living truth, promoted in the implementing PR alongside the code. A plan paragraph that would still read correctly with all task numbers and checkboxes removed is design content and belongs in the spec.

**Three lanes.** Scale the artifact to the change. **Full** — a `design.md` + `plan.md` bundle — for real design judgment, a new file/module, a public-API change, cross-cutting/multi-file work, or non-trivial test design. **Lightweight** — a single `change.md` — for small-but-real changes (≲30 LOC net, ≤2 files, no new file, no public-API change, a single straightforward test). **Tiny** — no bundle, just a conventional commit — for a typo, dep bump, linter/formatter/CI tweak, a mechanical rename, or a single-line config change. Heavier lane wins on ambiguity; a `change.md` that outgrows its lane splits into `design.md` + `plan.md`.

Design docs and implementation plans live under `planning/` (not under `docs/`, so they're excluded from the mkdocs site automatically). When superpowers skills default to `docs/superpowers/specs/` or `docs/superpowers/plans/`, use the change bundle under `planning/changes/` here instead.

## Code style

- Line length: 120 characters (ruff enforced)
- Ruff ALL rules enabled; notable ignores: D1 (missing docstrings), S101 (assert), TCH (type-checking imports), FBT (boolean args)
- Type annotations required; checked with `ty`

### Conventions (from prior audit work)

- **No `# noqa: PLR2004`**: extract magic values to named locals. Example: `expected_max_age = 600; assert config.cors_max_age == expected_max_age` (not `assert config.cors_max_age == 600  # noqa: PLR2004`).
- **Backward-compat aliases for renames**: when renaming a public class, add a silent module-level alias (`OldName = NewName`) at the end of the file. Re-export both names from `__init__.py` if the old name was publicly exported. Aliases are class assignments, not subclasses — same class object, so `isinstance` behavior is preserved.
- **Frozen-config bypass in `__post_init__`**: it's acceptable to use `object.__setattr__(self, "field", value)` inside a frozen config's `__post_init__` to set a field that requires other config values to construct. Document with a one-line comment naming the trade-off (user-facing immutability vs. construction-time mutation).
- **Optional-import guard pattern**: top-level conditional imports (`if import_checker.is_X_installed: import X`) keep optional dependencies actually optional. Code that references `X` is only reached when `check_dependencies()` has already returned True; the runtime invariant is maintained by the inline `is_configured → check_dependencies → instantiate` flow in `BaseBootstrapper.__init__`. See "Type checking" below.
- **`from_dict` vs `from_object` accept different shapes for `None`**: `BaseConfig.from_dict({"service_name": None})` succeeds and explicitly overrides the default with `None`. `BaseConfig.from_object(obj)` where `obj.service_name is None` filters the attribute out and the dataclass default takes over. The asymmetry is documented in both methods' docstrings (`instruments/base.py:17, 23`) and pinned by tests in `tests/test_config.py:54-94`. Pick `from_dict` if explicit-None override is the load-bearing semantic.
- **`__post_init__` cascade invariant**: every config-class `__post_init__` must call `super().__post_init__()` so MRO chains terminate cleanly. `BaseConfig` has a no-op `__post_init__` as the chain terminator. Required because `OpenTelemetryConfig.__post_init__` (SEC-2 warning), `CorsConfig.__post_init__` (SEC-3 validation), and `FastAPIConfig.__post_init__` (UnsetType app construction) all sit on the same MRO for `FastAPIConfig`/`LitestarConfig`/`FastStreamConfig`/`FreeConfig`; without the cascade, a class that returns early before `super()` blocks the rest of the chain. `FastAPIConfig` uses the explicit `super(FastAPIConfig, self).__post_init__()` form because `@dataclass(slots=True)` replaces the class object after the body compiles and breaks bare `super()`.
- **`_lite_bootstrap_*` prefix for sentinels on user-supplied app instances**: when the bootstrapper needs to tag a user-supplied framework app (FastAPI, FastMCP, Litestar, FastStream) with internal state, store it as a direct attribute on the instance with a `_lite_bootstrap_` prefix. The canonical example is the `_lite_bootstrap_teardown_attached` marker that gates the double-attach guard, set once by the shared `BaseBootstrapper._attach_teardown_once(target, attach)` and applied uniformly across all four app-bearing bootstrappers (FastAPI tags the app, Litestar tags its `AppConfig`, FastStream/FastMCP tag the app). Read with `getattr(target, "_lite_bootstrap_<name>", False)` (no SLF violation); write with `setattr`/`target._lite_bootstrap_<name> = value  # noqa: SLF001`. Don't squat in framework-provided user namespaces like Starlette's `application.state`. See `architecture/bootstrappers.md`.

### Type checking

The project uses **`ty`** (Astral's type checker), enforced via `just lint`. No other type checker is supported; the codebase patterns (conditional imports for optional dependencies, covariant `bootstrap_config` narrowing in framework instrument subclasses, TypedDict optional-key access guarded by `.get()` truthiness checks) require a checker that models them correctly. Pyright is not used.
