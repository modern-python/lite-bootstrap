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
    └── Instrument subclasses: lifecycle via bootstrap() / teardown() / is_ready()

BaseBootstrapper (abc.ABC)
    ├── FastAPIBootstrapper
    ├── LitestarBootstrapper
    ├── FastStreamBootstrapper
    └── FreeBootstrapper
```

### Key design decisions

- **Optional dependencies**: Each instrument checks for its optional package via `import_checker.py` (`importlib.util.find_spec`). Instruments are skipped silently if the package is absent. Optional packages are imported inside `if import_checker.is_X_installed:` blocks; static analyzers that don't model this guard will report spurious "possibly unbound" diagnostics — the project uses `ty` which handles the pattern correctly.
- **Frozen configs, non-frozen instruments**: All `*Config` classes are `@dataclasses.dataclass(kw_only=True, frozen=True)`. All `*Instrument` classes lose `frozen=True` because two instruments (`LoggingInstrument`, `OpenTelemetryInstrument`) cache mutable runtime state (`_logger_factory`, `_tracer_provider`); Python's dataclass rules require the whole hierarchy to be non-frozen. `from_dict()` and `from_object()` filter unknown keys before constructing.
- **`FastAPIConfig.application` uses an `UnsetType` sentinel**: shared in `lite_bootstrap/types.py` as `UnsetType` + `UNSET` (singleton). `FastAPIConfig.__post_init__` checks `isinstance(self.application, UnsetType)` and replaces with a constructed `FastAPI()` via `object.__setattr__` (config stays frozen for user-facing immutability). A one-line comment in `__post_init__` documents the freeze bypass.
- **Instrument registry**: `BaseBootstrapper` holds a list of instrument instances; it calls `bootstrap()` on each in order and `teardown()` in reverse during shutdown.
- **Idempotent teardown**: `BaseBootstrapper.teardown()` returns immediately if `not self.is_bootstrapped`. Cached runtime state in `LoggingInstrument` and `OpenTelemetryInstrument` is reset inside `try/finally` so a raised shutdown leaves no stale references.
- **Logging ↔ Sentry integration**: `logging_instrument.py` injects structlog context into Sentry events. `sentry_instrument.py` chains `before_send` callbacks via `wrap_before_send_callbacks()`. The `skip_sentry` flag in log context suppresses events; the flag is also stripped from the Sentry context payload (added to `IGNORED_STRUCTLOG_ATTRIBUTES`).
- **OTel ↔ Logging integration**: The logging instrument injects span/trace IDs from the active OpenTelemetry context into every log record.

### Module layout

- `lite_bootstrap/bootstrappers/` — framework-specific bootstrappers and their config classes
- `lite_bootstrap/instruments/` — individual instrument implementations (one file per tool)
- `lite_bootstrap/helpers/` — utility functions (`fastapi_helpers.py` serves offline Swagger UI assets)
- `lite_bootstrap/import_checker.py` — detects installed optional packages
- `lite_bootstrap/types.py` — shared TypeVars and `UnsetType` / `UNSET` sentinel
- `lite_bootstrap/instruments/logging_factory.py` — `MemoryLoggerFactory`, factory config, structlog serializer, ASGI protocols

### Optional dependency groups

Install via `pip install lite-bootstrap[<group>]` or `uv add lite-bootstrap[<group>]`:

| Group | Contents |
|-------|----------|
| `fastapi-all` | fastapi + sentry + otl + logging + metrics |
| `litestar-all` | litestar + sentry + otl + logging |
| `faststream-all` | faststream + sentry + otl + logging |
| `free-all` | sentry + otl + logging |
| `pyroscope` | pyroscope-io (add to any group) |

## Code style

- Line length: 120 characters (ruff enforced)
- Ruff ALL rules enabled; notable ignores: D1 (missing docstrings), S101 (assert), TCH (type-checking imports), FBT (boolean args)
- Type annotations required; checked with `ty`

### Conventions (from prior audit work)

- **No `# noqa: PLR2004`**: extract magic values to named locals. Example: `expected_max_age = 600; assert config.cors_max_age == expected_max_age` (not `assert config.cors_max_age == 600  # noqa: PLR2004`).
- **Backward-compat aliases for renames**: when renaming a public class, add a silent module-level alias (`OldName = NewName`) at the end of the file. Re-export both names from `__init__.py` if the old name was publicly exported. Aliases are class assignments, not subclasses — same class object, so `isinstance` behavior is preserved.
- **Frozen-config bypass in `__post_init__`**: it's acceptable to use `object.__setattr__(self, "field", value)` inside a frozen config's `__post_init__` to set a field that requires other config values to construct. Document with a one-line comment naming the trade-off (user-facing immutability vs. construction-time mutation).
- **Optional-import guard pattern**: top-level conditional imports (`if import_checker.is_X_installed: import X`) keep optional dependencies actually optional. Code that references `X` is only reached when `check_dependencies()` has already returned True; the runtime invariant is maintained by `BaseBootstrapper._register_or_skip`. See "Type checking" below for why Pyright dislikes this pattern.

### Type checking

The project uses **`ty`** (Astral's type checker), enforced via `just lint`. No other type checker is supported; the codebase patterns (conditional imports for optional dependencies, covariant `bootstrap_config` narrowing in framework instrument subclasses, TypedDict optional-key access guarded by `.get()` truthiness checks) require a checker that models them correctly. Pyright is not used.
