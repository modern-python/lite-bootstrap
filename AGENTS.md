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

## Workflow

Real work **not scheduled** becomes a GitHub issue.

An invariant is a test whose name is the claim, with a docstring opening `INVARIANT:` and a second
paragraph naming **what breaks it** — design rationale, not a report of what this one test catches.
Nothing enforces that docstring shape; it is read at review time.

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

## Agent skills

- **Domain docs** — [`CONTEXT.md`](CONTEXT.md) owns the vocabulary and [`docs/adr/`](docs/adr/)
  holds the decisions. Both follow the `domain-modeling` skill: invoke it when writing either,
  rather than restating its rules here.
