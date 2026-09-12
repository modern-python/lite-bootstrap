# AGENTS.md

## Project Overview

`lite-bootstrap` bootstraps a Python microservice with pre-configured observability.
[`CONTEXT.md`](CONTEXT.md) owns the vocabulary — read it before naming a concept in code, a test, or
an issue. An instrument being **configured** versus a bootstrapper being **ready**, and the two
kinds of **skip**, are defined there and are load-bearing throughout.

## Commands

`just` (task runner) and `uv` (package manager). The [`justfile`](justfile) is the source of truth;
every non-obvious recipe carries its intent as a comment.

## Architecture

One file per concern, named for it: `instruments/<name>_instrument.py` owns one observability
concern, `bootstrappers/<framework>_bootstrapper.py` owns one framework's bindings, and
`import_checker.py` owns every optional-dependency probe.

## Workflow

Real work **not scheduled** becomes a GitHub issue.

Every link in `README.md` is absolute — `https://github.com/modern-python/<repo>/blob/main/<path>`,
or `.../tree/main/<path>` for a directory. `README.md` is also the PyPI long description, and PyPI
does not rewrite relative links, so a relative one 404s on the package page.

An invariant is a test whose name is the claim, with a docstring opening `INVARIANT:` and a second
paragraph naming **what breaks it** — design rationale, not a report of what this one test catches.

## Agent docs

- Issue tracker: GitHub issues on `modern-python/lite-bootstrap` via `gh`. `docs/agents/issue-tracker.md`.
- Triage labels: five canonical roles, each label string equal to its name. `docs/agents/triage-labels.md`.
- Domain docs: single-context, `CONTEXT.md` and `docs/adr/` at the repo root. `docs/agents/domain.md`.

## Code style

Four rules that are not visible in the code that follows them:

- **No `# noqa: PLR2004`.** Extract the magic value to a named local instead:
  `expected_max_age = 600; assert config.cors_max_age == expected_max_age`.
- **A public rename ships a silent alias.** `OldName = NewName` at the end of the module, re-exported
  from `__init__.py` if the old name was. A class assignment, not a subclass, so `isinstance` still
  holds; `OpentelemetryConfig` is the worked example.
- **A warning reached from config construction or an instrument's `bootstrap()` goes through
  `warn_at_caller`.** Neither depth is constant — a `__post_init__` cascade runs as deep as that
  config's MRO, and `bootstrap()` sits a frame deeper whenever it calls `super().bootstrap()` — so
  the helper walks out to the first frame outside `lite_bootstrap`. The three surviving literal
  `stacklevel=` sites lie outside both paths and stay literal; #202 measured them.
- **Sentinels on a user's app get a `_lite_bootstrap_` prefix.** A direct attribute on the app
  object, never a framework namespace like Starlette's `application.state`. Read it with
  `getattr(target, name, default)` (no SLF violation); write it with `# noqa: SLF001`.

### Type checking

`ty` is the only supported type checker; act on its diagnostics alone. The codebase leans on patterns
Pyright reports as errors — conditional imports for optional dependencies, covariant
`bootstrap_config` narrowing on instrument subclasses, `TypedDict` optional-key access guarded by
`.get()` — so adding it yields noise, not findings.

Two suppression spellings recur and are both correct as written: `# ty: ignore[invalid-method-override]`
on a framework subclass's `is_configured` classmethod, which narrows its parameter type where `ty`
enforces invariance, and `# ty: ignore[unresolved-attribute]` on the optional OTel/pyroscope symbols
whose guard `ty` does not follow.
