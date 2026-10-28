# AGENTS.md

## Project Overview

`lite-bootstrap` bootstraps a Python microservice with pre-configured observability.
[`CONTEXT.md`](CONTEXT.md) owns the vocabulary; read it before naming a concept in code, a test, or
an issue. An instrument being **configured** versus a bootstrapper being **ready**, and the two
kinds of **skip**, are defined there and are load-bearing throughout.

## Commands

`just` (task runner) and `uv` (package manager). The [`justfile`](justfile) is the source of truth:
`just --list`, or read it. Every non-obvious recipe carries its intent as a comment.

## Architecture

One file per concern, named for it: `instruments/<name>_instrument.py` owns one observability
concern, `bootstrappers/<framework>_bootstrapper.py` owns one framework's bindings, and
`import_checker.py` owns every optional-dependency probe.

## Workflow

Every link in `README.md` must be absolute: `https://github.com/modern-python/<repo>/blob/main/<path>`,
or `.../tree/main/<path>` for a directory. Never a relative path: `README.md` is also the PyPI long
description, and PyPI does not rewrite relative links, so a relative one 404s on the package page.

Before pushing a raised dependency floor, run the `floors` steps from
[`_checks.yml`](.github/workflows/_checks.yml) locally. If resolution fails, raise the direct floor
it names.

## Versioning

- **A change is breaking when a user's working code or deployed behaviour changes without them
  editing anything:** a new default, a removed or renamed public name or config field, a changed
  HTTP surface (path, status code, response body), or a raised dependency floor that the previous
  floor ran correctly with. Correcting a floor the code never worked with is a fix.
- **A breaking change ships only in a major release.** One exception: dropping a Python version past
  its end of life ships in a minor, as 1.11.0 did for 3.10. Installers skip a release whose
  `requires-python` excludes the running interpreter, so no deployed service breaks.
- **A rename keeps the old name working, with a `DeprecationWarning`, for at least one minor, and
  the next major deletes it.** The warning names that major. A module-level name goes through
  `deprecated_module_getattr` plus a `typing.TYPE_CHECKING` alias so type checkers still see it; a
  config field goes through `BaseConfig._renamed_fields`.
- **Every breaking change gets a line in a "Breaking changes" section of the release notes**, as
  [1.12.0](https://github.com/modern-python/lite-bootstrap/releases/tag/1.12.0) has.

## Agent skills

### Issue tracker

GitHub issues on `modern-python/lite-bootstrap`, via `gh`. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical roles, each label string equal to its name. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

## Code style

Three rules that are not visible in the code that follows them:

- **No `# noqa: PLR2004`.** Extract the magic value to a named local instead:
  `expected_max_age = 600; assert config.cors_max_age == expected_max_age`.
- **A warning reached from config construction or an instrument's `bootstrap()` goes through
  `warn_at_caller`.** Neither depth is constant: a `__post_init__` cascade runs as deep as that
  config's MRO, and `bootstrap()` sits a frame deeper whenever it calls `super().bootstrap()`. So
  the helper walks out to the first frame outside `lite_bootstrap`. The three surviving literal
  `stacklevel=` sites lie outside both paths and stay literal; #202 measured them.
- **Sentinels on a user's app get a `_lite_bootstrap_` prefix.** A direct attribute on the app
  object, never a framework namespace like Starlette's `application.state`. Read it with
  `getattr(target, name, default)` (no SLF violation); write it with `# noqa: SLF001`.

### Type checking

`ty` is the only supported type checker; act on its diagnostics alone. The codebase leans on patterns
Pyright reports as errors (conditional imports for optional dependencies, covariant
`bootstrap_config` narrowing on instrument subclasses, `TypedDict` optional-key access guarded by
`.get()`), so adding it yields only noise.

Two suppressions recur and are both correct: `invalid-method-override` on a framework subclass's
`is_configured` classmethod, which narrows its parameter type where `ty` enforces invariance, and
`unresolved-attribute` on the optional OTel/pyroscope symbols whose guard `ty` does not follow.
