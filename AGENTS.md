# AGENTS.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

`just --list` is the source of truth. Non-obvious "which to use when":

- `just lint` auto-fixes; `just lint-ci` is check-only (CI) and also runs the
  planning validator (`planning/index.py --check`). `just check-planning` runs
  just that validator.
- `just test -- -k "test_name"` runs a single test; `just test-branch` adds
  branch coverage.

All commands use `uv run` — do not invoke tools directly (e.g., use `uv run pytest`, not `pytest`).

## Architecture

**lite-bootstrap** bootstraps Python microservices with pre-configured
observability instruments: a frozen `BaseConfig` hierarchy describes what the
user wants, `BaseInstrument[ConfigT]` subclasses each own one observability
concern, and a `BaseBootstrapper` per framework decides which instruments apply
and drives their lifecycle.

The authoritative, code-current account of each capability lives in
[`architecture/`](architecture/). **When a change alters a capability's
behavior, update the matching `architecture/<capability>.md` in the same PR** —
that promotion is what keeps `architecture/` true.

Invariants (what must not break) — see the capability page for the full account:

- **Frozen configs, non-frozen instruments.** All `*Config` are frozen for
  user-facing immutability; `*Instrument` are non-frozen because `LoggingInstrument`
  / `OpenTelemetryInstrument` cache runtime state, forcing the whole hierarchy
  non-frozen. → `architecture/config-model.md`, `architecture/instruments.md`
- **`__post_init__` cascade.** Every config `__post_init__` must call
  `super().__post_init__()` (`BaseConfig` is the no-op terminator); `FastAPIConfig`
  uses the explicit `super(FastAPIConfig, self)` form under `slots=True`. →
  `architecture/config-model.md`
- **`from_dict` vs `from_object` differ on `None`.** `from_dict` passes explicit
  `None` through (overrides default); `from_object` filters `None`/missing (default
  wins). → `architecture/config-model.md`
- **Optional-dependency guard.** Optional imports sit behind
  `if import_checker.is_X_installed:`; code referencing the symbol runs only after
  `check_dependencies()` returned True. `ty` models this; other checkers may
  false-flag "possibly unbound". → `architecture/instruments.md`
- **Construction skip ordering.** `is_configured` (silent skip) → `check_dependencies`
  (warns on configured-but-missing) → instantiate; one INFO summary line via
  `build_summary()`. → `architecture/bootstrappers.md`
- **Idempotent teardown.** `teardown()` no-ops when not bootstrapped, runs instruments
  in reverse, collects per-instrument errors into one `TeardownError`, resets cached
  state in `try/finally`. → `architecture/bootstrappers.md`
- **OTel is single-instance per process.** `set_tracer_provider` is set-once; a second
  instance is ignored. Construct exactly one `OpenTelemetryInstrument` per process. →
  `architecture/instruments.md`
- **Teardown attaches once.** `_attach_teardown_once` guards against double-attach via
  the `_lite_bootstrap_teardown_attached` marker; a second bootstrapper on an already-marked
  target warns at construction and its `bootstrap()` raises `ConfigurationError`.
  `_lite_bootstrap_*`-prefixed attributes are the sanctioned way to tag user-supplied
  apps. → `architecture/bootstrappers.md`

Capability index (all of `architecture/`):

| Capability | File |
|---|---|
| Config model — `BaseConfig`, multiple-inheritance composition, `from_dict`/`from_object`, `UNSET`, `__post_init__` cascade | `architecture/config-model.md` |
| Instruments — `BaseInstrument` lifecycle, catalog, optional-dep guard, non-frozen rationale, cross-instrument integrations (Logging↔Sentry, OTel↔Logging, Pyroscope↔OTel), OTel single-instance | `architecture/instruments.md` |
| Bootstrappers — hierarchy, skip ordering, registry + idempotent teardown, summary logging, teardown-attach seam, app-tagging sentinels | `architecture/bootstrappers.md` |
| Free-threading — nogil support matrix, orjson fallback, single-threaded-init invariant | `architecture/free-threading.md` |

Recent design context, bugs, and rationale: bug-audit findings in
`planning/audits/`, post-work reflections in `planning/retros/`, and the audit
arcs recorded as change files under `planning/changes/`. The full extras
matrix is `[project.optional-dependencies]` in `pyproject.toml`.

## Workflow

Planning uses the portable two-axis convention: `architecture/` (repo root) is
the living truth home and promotion target; `planning/changes/` holds the
per-change files. **Start at the
[Quick path](planning/README.md#quick-path-start-here)** in
[`planning/README.md`](planning/README.md) to choose a lane (Full / Lightweight /
Tiny), create a change file, and ship — that file is the authoritative spec, with
copy-and-fill starters in [`planning/_templates/`](planning/_templates/). Run
`just check-planning` to validate changes and `just index` to print the listing.

Repo-local notes:

- Design docs and plans live under `planning/`, **not** under `docs/`, so the
  mkdocs site excludes them automatically. When superpowers skills default to
  `docs/superpowers/specs/` or `docs/superpowers/plans/`, use a change file
  under `planning/changes/` instead.
- `summary` is finalized at ship to state the realized result, in the
  implementing PR alongside the code and the `architecture/` promotion — no
  post-merge bookkeeping, no file move.

## Code style

- Line length: 120 characters (ruff enforced)
- Ruff ALL rules enabled; notable ignores: D1 (missing docstrings), S101 (assert), TCH (type-checking imports), FBT (boolean args)
- Type annotations required; checked with `ty`

### Conventions (from prior audit work)

These are coding rules. The capability invariants they touch are detailed in
`architecture/` (pointers below).

- **No `# noqa: PLR2004`**: extract magic values to named locals. Example: `expected_max_age = 600; assert config.cors_max_age == expected_max_age` (not `assert config.cors_max_age == 600  # noqa: PLR2004`).
- **Backward-compat aliases for renames**: when renaming a public class, add a silent module-level alias (`OldName = NewName`) at the end of the file. Re-export both names from `__init__.py` if the old name was publicly exported. Aliases are class assignments, not subclasses — same class object, so `isinstance` behavior is preserved.
- **Frozen-config bypass in `__post_init__`**: `object.__setattr__(self, "field", value)` inside a frozen config's `__post_init__` is acceptable to set a field that requires other config values to construct; document with a one-line comment naming the trade-off (user-facing immutability vs. construction-time mutation). → `architecture/config-model.md`
- **Optional-import guard pattern**: top-level conditional imports (`if import_checker.is_X_installed: import X`) keep optional dependencies actually optional; code referencing `X` runs only after `check_dependencies()` returned True (the `is_configured → check_dependencies → instantiate` flow in `BaseBootstrapper.__init__`). See "Type checking" below. → `architecture/instruments.md`
- **`from_dict` vs `from_object` differ on `None`**: `from_dict` overrides the default with explicit `None`; `from_object` filters `None`/missing so the default wins. Documented in both docstrings (`instruments/base.py`) and pinned by `tests/test_config.py`. Pick `from_dict` if explicit-None override is the load-bearing semantic. → `architecture/config-model.md`
- **`__post_init__` cascade**: every config-class `__post_init__` must call `super().__post_init__()`; `BaseConfig`'s no-op terminates the chain; `FastAPIConfig` needs the explicit `super(FastAPIConfig, self).__post_init__()` form under `slots=True`. → `architecture/config-model.md`
- **`_lite_bootstrap_*` prefix for sentinels on user-supplied apps**: tag a user-supplied framework app with a direct `_lite_bootstrap_`-prefixed attribute (read via `getattr(..., default)` — no SLF violation; write with `# noqa: SLF001`); don't squat in framework namespaces like Starlette's `application.state`. The canonical example is the `_lite_bootstrap_teardown_attached` double-attach marker set by `_attach_teardown_once`. → `architecture/bootstrappers.md`

### Type checking

The project uses **`ty`** (Astral's type checker), enforced via `just lint`. No other type checker is supported; the codebase patterns (conditional imports for optional dependencies, covariant `bootstrap_config` narrowing in framework instrument subclasses, TypedDict optional-key access guarded by `.get()` truthiness checks) require a checker that models them correctly. Pyright is not used.
