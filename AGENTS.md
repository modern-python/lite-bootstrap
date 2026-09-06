# AGENTS.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`lite-bootstrap` bootstraps a Python microservice with pre-configured observability;
[`CONTEXT.md`](CONTEXT.md) opens with what it does and owns the vocabulary — read it before naming a
concept in code, a test name, or an issue title. The distinction between an instrument being
**configured** and a bootstrapper being **ready**, and between the two kinds of **skip**, is defined
there and is load-bearing throughout.

## Commands

`just` (task runner) and `uv` (package manager). The [`justfile`](justfile) is the source of truth —
`just --list`, or read it; every non-obvious recipe carries its intent as a comment.

## Architecture

`lite_bootstrap/` is one file per concern and named for what it does: `instruments/<name>_instrument.py`
owns one observability concern, `bootstrappers/<framework>_bootstrapper.py` owns one framework's
bindings, and `import_checker.py` owns every optional-dependency probe. Read them.

What reading them will not tell you is why four shapes are load-bearing rather than incidental:

- The instrument × framework matrix stays on the **instrument** axis, not a per-framework adapter
  axis ([ADR-0002](docs/adr/0002-keep-per-instrument-axis.md)).
- The double-bootstrap guard is an attribute marker, with two known limits accepted
  ([ADR-0003](docs/adr/0003-teardown-marker-accepted-limits.md)).
- OpenTelemetry's URL-exclusion policy stays in one method reading its siblings, rather than being
  contributed per instrument ([ADR-0004](docs/adr/0004-excluded-urls-stay-one-method.md)).
- `orjson` is an opt-in extra ([ADR-0005](docs/adr/0005-orjson-is-opt-in.md)) and
  `typing-extensions` is core's only runtime dependency
  ([ADR-0007](docs/adr/0007-core-declares-typing-extensions.md)) — together, the reason every
  surface this library controls installs on free-threaded CPython.

Behaviour detail has no prose home: it lives in the code and in the `INVARIANT:`-marked tests.
Before writing prose about a capability, run the admission check in **Where a fact goes**.

## Workflow

**The spec for a change is its PR body**, not a committed file: why, design, non-goals,
verification, reviewed with the diff. There is no change file and no lane to choose. A trivial PR
(typo, dep bump, formatter, CI tweak) ships a conventional-commit title with no body ceremony.

Two things outlive the PR, and there are exactly two places to put them: an alternative **rejected**
with reasoning becomes an ADR in [`docs/adr/`](docs/adr/) (`NNNN-slug.md`, sequential, with a revisit
trigger), and real work **not scheduled** becomes a GitHub issue. There is no third state, and no
separate truth-home directory — a behaviour change is reviewed with the diff, not promoted to a page.

### Where a fact goes

Four homes, one owner each:

| Home | Holds |
|---|---|
| `lite_bootstrap/` | anything readable from the module — the default |
| a named test | an **invariant**: must stay true, and a change could silently break it |
| `docs/adr/` | a rejected alternative, with the reasoning that would otherwise be re-litigated |
| `README.md` and `docs/` | anything a user needs |

Before writing a line anywhere:

> Can an agent get this by reading `lite_bootstrap/`? → **don't write it.**
> Would a wrong change here fail a test? → it belongs **in the test**, not in prose.
> Does a user need it? → **`README.md` or `docs/`**.
> Otherwise it does not get written.

**Prose about mechanism has no home. There is no file to add a paragraph to.** This file included:
it is always loaded, so a line that restates a docstring, a justfile comment, or `pyproject.toml`
costs every turn and rots in two places at once. This project tempts that failure mode particularly
hard, because the instrument × framework matrix invites a written index of cells that the file
layout already gives you.

An invariant is a test whose name is the claim, with a docstring opening `INVARIANT:` and a second
paragraph naming **what breaks it** — design rationale, not a report of what this one test catches.
Nothing enforces that docstring shape; it is read at review time. A relative link to an ADR *is*
checked — CI runs lychee `--offline` over every `.md` — but a path named in a docstring or a comment
is not. Both ADRs and `INVARIANT:` docstrings ratchet: nothing prunes a record once its call is
settled. Keeping them lean is a standing habit.

## Code style

Three rules that are not visible in the code that follows them:

- **No `# noqa: PLR2004`.** Extract the magic value to a named local instead:
  `expected_max_age = 600; assert config.cors_max_age == expected_max_age`.
- **A public rename ships a silent alias.** Add `OldName = NewName` at the end of the module and
  re-export both from `__init__.py` if the old name was exported. It is a class assignment, not a
  subclass, so `isinstance` still holds. `FreeBootstrapperConfig`, `OpentelemetryConfig` and
  `IGNORED_STRUCTLOG_ATTRIBUTES` exist for this reason.
- **Sentinels on a user's app get a `_lite_bootstrap_` prefix.** Set a direct attribute on the app
  object; never squat in a framework namespace like Starlette's `application.state`. Read it with
  `getattr(target, name, default)` (no SLF violation); write it with `# noqa: SLF001`.

### Type checking

`ty` is the only supported type checker. The codebase leans on patterns a checker has to model
correctly — conditional imports for optional dependencies, covariant `bootstrap_config` narrowing on
instrument subclasses, `TypedDict` optional-key access guarded by `.get()` — and Pyright reports all
three as errors. Do not add it, and do not act on its diagnostics.

Two suppression spellings recur and are both correct as written: `# ty: ignore[invalid-method-override]`
on a framework subclass's `is_configured` classmethod, which narrows its parameter type where `ty`
enforces invariance, and `# ty: ignore[unresolved-attribute]` on the optional OTel/pyroscope symbols
whose guard `ty` does not follow.
