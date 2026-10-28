"""Litestar through LitestarBootstrapper, one instrument or knob at a time, on a do-nothing `/ping`.

`kind="structlog"` swaps in a handler that writes three structlog records per request; `kind="healthlike"`
returns the same body the health check does, so `health` can be compared to a plain handler.
"""

import typing

import litestar
import structlog
from common import (
    ALL_SPANS,
    CORS,
    EXCL,
    LOG,
    ORIGIN,
    OTEL,
    OTEL_METRICS,
    PROM,
    SAMPLED_SENTRY_TRACE,
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
from litestar.config.app import AppConfig
from sentry_sdk.integrations.litestar import LitestarIntegration

from lite_bootstrap import LitestarBootstrapper, LitestarConfig


log = structlog.get_logger("bench")

HEALTH: typing.Final = {"health_checks_enabled": True}
LITESTAR_DEFAULTS: typing.Final = {**PROM, **HEALTH, **LOG, "swagger_path": "/docs"}
FULL: typing.Final = {**OTEL, **PROM, **LOG, **sentry(), **HEALTH}

SCENARIOS: typing.Final = {
    "bare": Scenario(config=base_config()),
    "bare_log3": Scenario(config=base_config(), kind="structlog"),
    "defaults_noobs": Scenario(config=base_config(**LITESTAR_DEFAULTS)),
    "log": Scenario(config=base_config(**LOG)),
    "log_log3": Scenario(config=base_config(**LOG), kind="structlog"),
    "log_mw": Scenario(config=base_config(**LOG, logging_access_log_enabled=True)),
    "prom": Scenario(config=base_config(**PROM)),
    "prom_nogroup": Scenario(config=base_config(**PROM, prometheus_group_path=False)),
    "otel": Scenario(config=base_config(**OTEL)),
    "otel_all_spans": Scenario(config=base_config(**OTEL, **ALL_SPANS)),
    "otel_excl": Scenario(config=base_config(**OTEL, **EXCL)),
    "otel_10": Scenario(config=base_config(**OTEL, **ratio(0.1))),
    "otel_10_excl": Scenario(config=base_config(**OTEL, **ratio(0.1), **EXCL)),
    "otel_1_excl": Scenario(config=base_config(**OTEL, **ratio(0.01), **EXCL)),
    "otel_0": Scenario(config=base_config(**OTEL, **ratio(0.0))),
    "otel_metrics": Scenario(config=base_config(**OTEL, **OTEL_METRICS)),
    "otel_0_metrics": Scenario(config=base_config(**OTEL, **OTEL_METRICS, **ratio(0.0))),
    "otel_0_prom": Scenario(config=base_config(**OTEL, **ratio(0.0), **PROM)),
    "otel_0_metrics_prom": Scenario(config=base_config(**OTEL, **OTEL_METRICS, **ratio(0.0), **PROM)),
    "sentry": Scenario(config=base_config(**sentry())),
    "sentry_nosess": Scenario(config=base_config(**sentry(), sentry_auto_session_tracking=False)),
    "sentry_noauto": Scenario(config=base_config(**sentry(auto_enabling_integrations=False))),
    "sentry_nodefault": Scenario(config=base_config(**sentry(), sentry_default_integrations=False)),
    "sentry_nointegration": Scenario(
        config=base_config(**sentry(disabled_integrations=[LitestarIntegration]), sentry_lean_error_capture=False)
    ),
    "sentry_integration": Scenario(config=base_config(**sentry(), sentry_lean_error_capture=False)),
    "sentry_sampled_trace": Scenario(config=base_config(**sentry()), headers=SAMPLED_SENTRY_TRACE),
    "sentry_integration_sampled_trace": Scenario(
        config=base_config(**sentry(), sentry_lean_error_capture=False), headers=SAMPLED_SENTRY_TRACE
    ),
    "cors_noorigin": Scenario(config=base_config(**CORS)),
    "cors": Scenario(config=base_config(**CORS), headers=ORIGIN),
    "bare_origin": Scenario(config=base_config(), headers=ORIGIN),
    "swagger": Scenario(config=base_config(swagger_path="/docs")),
    "swagger_offline": Scenario(config=base_config(swagger_path="/docs", swagger_offline_docs=True)),
    "health_ping": Scenario(config=base_config(**HEALTH), kind="healthlike"),
    "health": Scenario(config=base_config(**HEALTH), path="/health/"),
    "health_otel": Scenario(config=base_config(**HEALTH, **OTEL), path="/health/"),
    "health_otel_nospan": Scenario(
        config=base_config(**HEALTH, **OTEL, opentelemetry_generate_health_check_spans=False), path="/health/"
    ),
    "full": Scenario(config=base_config(**FULL)),
    "full_log3": Scenario(config=base_config(**FULL), kind="structlog"),
}


@litestar.get("/ping")
async def ping() -> dict[str, bool]:
    return {"ok": True}


@litestar.get("/ping")
async def ping_log() -> dict[str, bool]:
    log.info("handling request", a=1)
    log.info("did a thing", b=2)
    log.info("done", c=3)
    return {"ok": True}


@litestar.get("/ping")
async def ping_health() -> litestar.Response[dict[str, typing.Any]]:
    return litestar.Response({"service_version": "1.0.0", "service_name": "bench", "health_status": True})


HANDLERS: typing.Final = {"async": ping, "structlog": ping_log, "healthlike": ping_health}


def build(name: str) -> tuple[ASGIApp, Scenario]:
    scenario = SCENARIOS[name]
    app_config = AppConfig(route_handlers=[HANDLERS[scenario.kind]])
    app = LitestarBootstrapper(LitestarConfig(application_config=app_config, **scenario.config)).bootstrap()
    return app, scenario


async def make(name: str) -> tuple[Op, Cleanup]:
    app, scenario = build(name)
    stop = await start_lifespan(app)
    return asgi_op(app, http_scope(scenario.path, extra_headers=scenario.headers)), stop
