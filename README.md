Lite-Bootstrap
==
[![Test Coverage](https://codecov.io/gh/modern-python/lite-bootstrap/branch/main/graph/badge.svg)](https://codecov.io/gh/modern-python/lite-bootstrap)
[![Supported versions](https://img.shields.io/pypi/pyversions/lite-bootstrap.svg)](https://pypi.python.org/pypi/lite-bootstrap)
[![downloads](https://img.shields.io/pypi/dm/lite-bootstrap.svg)](https://pypistats.org/packages/lite-bootstrap)
[![GitHub stars](https://img.shields.io/github/stars/modern-python/lite-bootstrap)](https://github.com/modern-python/lite-bootstrap/stargazers)

`lite-bootstrap` assists you in creating applications with all the necessary instruments already set up.

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

- [LiteStar](https://lite-bootstrap.readthedocs.io/integrations/litestar)
- [FastStream](https://lite-bootstrap.readthedocs.io/integrations/faststream)
- [FastAPI](https://lite-bootstrap.readthedocs.io/integrations/fastapi)
- [FastMCP](https://lite-bootstrap.readthedocs.io/integrations/fastmcp)
- [services and scripts without frameworks](https://lite-bootstrap.readthedocs.io/integrations/free)
---

Usage examples:

- with LiteStar - [litestar-sqlalchemy-template](https://github.com/modern-python/litestar-sqlalchemy-template)
- with FastAPI - [fastapi-sqlalchemy-template](https://github.com/modern-python/fastapi-sqlalchemy-template)

## Part of `modern-python`

Browse the full list of templates and libraries in
[`modern-python`](https://github.com/modern-python) — see the org profile for the
categorized index.

## 📚 [Documentation](https://lite-bootstrap.readthedocs.io)

## 📦 [PyPi](https://pypi.org/project/lite-bootstrap)

## 📝 [License](LICENSE)

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
