"""FastAPI through FastAPIBootstrapper, one instrument or knob at a time, on a do-nothing `/ping`."""

import typing

from common import (
    CORS,
    EXCL,
    LOG,
    ORIGIN,
    OTEL,
    OTEL_METRICS,
    PROM,
    ASGIApp,
    Cleanup,
    Op,
    Scenario,
    asgi_op,
    base_config,
    http_scope,
    ratio,
    sentry,
    start_lifespan,
)
from fastapi import FastAPI

from lite_bootstrap import FastAPIBootstrapper, FastAPIConfig


HEALTH: typing.Final = {"health_checks_enabled": True}

SCENARIOS: typing.Final = {
    "bare": Scenario(config=base_config()),
    "log": Scenario(config=base_config(**LOG)),
    "log_mw": Scenario(config=base_config(**LOG, fastapi_logging_middleware_enabled=True)),
    "prom": Scenario(config=base_config(**PROM)),
    "otel": Scenario(config=base_config(**OTEL)),
    "otel_excl": Scenario(config=base_config(**OTEL, **EXCL)),
    "otel_10": Scenario(config=base_config(**OTEL, **ratio(0.1))),
    "otel_10_excl": Scenario(config=base_config(**OTEL, **ratio(0.1), **EXCL)),
    "otel_0": Scenario(config=base_config(**OTEL, **ratio(0.0))),
    "otel_0_metrics": Scenario(config=base_config(**OTEL, **OTEL_METRICS, **ratio(0.0))),
    "otel_0_prom": Scenario(config=base_config(**OTEL, **ratio(0.0), **PROM)),
    "otel_0_metrics_prom": Scenario(config=base_config(**OTEL, **OTEL_METRICS, **ratio(0.0), **PROM)),
    "sentry": Scenario(config=base_config(**sentry())),
    "sentry_nosess": Scenario(config=base_config(**sentry(), sentry_auto_session_tracking=False)),
    "sentry_noauto": Scenario(config=base_config(**sentry(auto_enabling_integrations=False))),
    "health": Scenario(config=base_config(**HEALTH), path="/health/"),
    "health_otel": Scenario(config=base_config(**HEALTH, **OTEL), path="/health/"),
    "health_otel_nospan": Scenario(
        config=base_config(**HEALTH, **OTEL, opentelemetry_generate_health_check_spans=False), path="/health/"
    ),
    "cors": Scenario(config=base_config(**CORS), headers=ORIGIN),
    "full": Scenario(config=base_config(**OTEL, **PROM, **LOG, **sentry(), **HEALTH)),
}


def make_app() -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/ping")
    async def ping() -> dict[str, bool]:
        return {"ok": True}

    return app


def build(name: str) -> tuple[ASGIApp, Scenario]:
    scenario = SCENARIOS[name]
    app = make_app()
    FastAPIBootstrapper(FastAPIConfig(application=app, **scenario.config)).bootstrap()
    return app, scenario


async def make(name: str) -> tuple[Op, Cleanup]:
    app, scenario = build(name)
    stop = await start_lifespan(app)
    return asgi_op(app, http_scope(scenario.path, extra_headers=scenario.headers)), stop
