# lite-bootstrap

[![PyPI version](https://img.shields.io/pypi/v/lite-bootstrap.svg)](https://pypi.org/project/lite-bootstrap/)
[![Supported Python versions](https://img.shields.io/pypi/pyversions/lite-bootstrap.svg)](https://pypi.org/project/lite-bootstrap/)
[![Downloads](https://img.shields.io/pypi/dm/lite-bootstrap.svg)](https://pypistats.org/packages/lite-bootstrap)
[![Coverage](https://img.shields.io/badge/coverage-100%25-brightgreen.svg)](https://github.com/modern-python/lite-bootstrap/actions/workflows/ci.yml)
[![CI](https://github.com/modern-python/lite-bootstrap/actions/workflows/ci.yml/badge.svg)](https://github.com/modern-python/lite-bootstrap/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/modern-python/lite-bootstrap.svg)](https://github.com/modern-python/lite-bootstrap/blob/main/LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/modern-python/lite-bootstrap)](https://github.com/modern-python/lite-bootstrap/stargazers)
[![Context7](https://img.shields.io/badge/Context7-docs-blue)](https://context7.com/modern-python/lite-bootstrap)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![ty](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ty/main/assets/badge/v0.json)](https://github.com/astral-sh/ty)

`lite-bootstrap` helps you bootstrap production-ready Python microservices with all the necessary instruments already set up.

With `lite-bootstrap`, you receive an application with lightweight built-in support for:
- `sentry`
- `prometheus`
- `opentelemetry`
- `pyroscope` - with OpenTelemetry trace-profile linking
- `structlog`
- `cors`
- `swagger` - with additional offline version support
- `health-checks`

Those instruments can be bootstrapped for:

- [LiteStar](https://lite-bootstrap.modern-python.org/integrations/litestar)
- [FastStream](https://lite-bootstrap.modern-python.org/integrations/faststream)
- [FastAPI](https://lite-bootstrap.modern-python.org/integrations/fastapi)
- [FastMCP](https://lite-bootstrap.modern-python.org/integrations/fastmcp)
- [services and scripts without frameworks](https://lite-bootstrap.modern-python.org/integrations/free)

## Lifecycle constraints

A few constraints that aren't obvious from the API:

- **One bootstrapper per application instance.** Constructing two `FastAPIBootstrapper`s around the same `fastapi.FastAPI` (or two `FastMcpBootstrapper`s around the same `FastMCP`) stacks teardown hooks and re-wraps the lifespan. The library warns and skips the second attachment, but the second bootstrapper's `teardown()` won't fire on ASGI shutdown.
- **One `OpenTelemetryInstrument` per process.** `bootstrap()` calls `opentelemetry.trace.set_tracer_provider(...)`, which the OTel SDK enforces as set-once — subsequent calls log a warning and have no effect. `teardown()` flushes spans and closes exporters but can't reset the process-global pointer.
- **`teardown()` is idempotent.** `BaseBootstrapper.teardown()` short-circuits if not bootstrapped; per-instrument teardown methods are safe to call multiple times.
- **Partial teardown failures are aggregated.** If an instrument's teardown raises, the bootstrapper continues with the rest of the instruments and raises `TeardownError` at the end with all collected failures.

---

Usage examples:

- with LiteStar - [litestar-sqlalchemy-template](https://github.com/modern-python/litestar-sqlalchemy-template)
- with FastAPI - [fastapi-sqlalchemy-template](https://github.com/modern-python/fastapi-sqlalchemy-template)

## Acknowledgements

`lite-bootstrap` is inspired by [`microbootstrap`](https://github.com/community-of-python/microbootstrap) — a single package that wires up the common observability stack (sentry, prometheus, opentelemetry, logging, cors, swagger, health-checks) for FastAPI / Litestar / FastStream services and for plain scripts.

The following ideas were borrowed:

- the overall surface — a `Bootstrapper` per framework that composes a set of instruments,
- the lifecycle model — each instrument has `bootstrap()` / `teardown()` / `is_ready()` and is skipped when its optional dependency is not installed,
- the catalog of supported instruments and supported frameworks.

The following intentionally differ:

- **Configuration**: `lite-bootstrap` uses frozen `dataclass` configs (no `pydantic` / `pydantic-settings` runtime dependency), which is what makes it "lite". `microbootstrap` configures everything through `pydantic-settings` models.
- **Granular extras**: `lite-bootstrap` ships only `orjson` as a runtime dependency; every instrument (`sentry`, `otl`, `logging`, `pyroscope`) and every framework (`fastapi`, `litestar`, `faststream`) is its own extra, with per-pair combos (`fastapi-sentry`, `litestar-otl`, `faststream-metrics`, …) and `*-all` rollups. You install only what you actually use. `microbootstrap` bundles the full observability stack (opentelemetry, sentry-sdk, structlog, pyroscope-io, rich, pydantic-settings, …) as base dependencies and only splits framework packages into extras.
- **Scope**: `lite-bootstrap` is deliberately narrow — only instrument wiring. It does not include a Granian server runner or a console writer.

## 📚 [Documentation](https://lite-bootstrap.modern-python.org)

## 📦 [PyPI](https://pypi.org/project/lite-bootstrap)

## 📝 [License](LICENSE)

## Part of `modern-python`

Browse the full list of templates and libraries in
[`modern-python`](https://github.com/modern-python) — see the org profile for the categorized index.
