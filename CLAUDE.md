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
BaseConfig (dataclass, frozen, kw_only)
    └── Framework configs compose multiple instrument configs via multiple inheritance

BaseInstrument (abstract)
    └── Instrument subclasses: lifecycle via bootstrap() / teardown() / is_ready()

BaseBootstrapper (abstract)
    ├── FastAPIBootstrapper
    ├── LitestarBootstrapper
    ├── FastStreamBootstrapper
    └── FreeBootstrapper
```

### Key design decisions

- **Optional dependencies**: Each instrument checks for its optional package via `import_checker.py` (`importlib.util.find_spec`). Instruments are skipped silently if the package is absent.
- **Frozen dataclass configs**: All configs are `@dataclasses.dataclass(kw_only=True, frozen=True)`. `from_dict()` and `from_object()` filter unknown keys before constructing.
- **Instrument registry**: `BaseBootstrapper` holds a list of instrument instances; it calls `bootstrap()` on each in order and `teardown()` in reverse during shutdown.
- **Logging ↔ Sentry integration**: `logging_instrument.py` injects structlog context into Sentry events. `sentry_instrument.py` chains `before_send` callbacks via `wrap_before_send_callbacks()`. The `skip_sentry` flag in log context suppresses events.
- **OTel ↔ Logging integration**: The logging instrument injects span/trace IDs from the active OpenTelemetry context into every log record.

### Module layout

- `lite_bootstrap/bootstrappers/` — framework-specific bootstrappers and their config classes
- `lite_bootstrap/instruments/` — individual instrument implementations (one file per tool)
- `lite_bootstrap/helpers/` — utility functions (`fastapi_helpers.py` serves offline Swagger UI assets)
- `lite_bootstrap/import_checker.py` — detects installed optional packages
- `lite_bootstrap/types.py` — shared TypeVars

### Optional dependency groups

Install via `pip install lite-bootstrap[<group>]` or `uv add lite-bootstrap[<group>]`:

| Group | Contents |
|-------|----------|
| `fastapi-all` | fastapi + sentry + otl + logging + metrics |
| `litestar-all` | litestar + sentry + otl + logging |
| `faststream-all` | faststream + sentry + otl + logging |
| `free-all` | sentry + otl + logging |

## Code style

- Line length: 120 characters (ruff enforced)
- Ruff ALL rules enabled; notable ignores: D1 (missing docstrings), S101 (assert), TCH (type-checking imports), FBT (boolean args)
- Type annotations required; checked with `ty`
