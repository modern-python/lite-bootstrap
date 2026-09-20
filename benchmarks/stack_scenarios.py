"""The whole lite-bootstrap observability stack, one instrument at a time and combined.

Configured through `FastAPIBootstrapper`, so these are the costs a real service pays.
OTLP spans go to `stub_otlp.py` in a separate process so the exporter succeeds instead of
spinning on retry backoff; Sentry events go to `driver.TRANSPORT`.

Every scenario here is reachable through `FastAPIConfig`, so a reader can copy the tuned
configuration into their own service and get the measured behaviour.
"""

import os
import typing

import structlog
from driver import DSN, TRANSPORT
from fastapi import FastAPI
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

from lite_bootstrap import FastAPIBootstrapper, FastAPIConfig


OTLP_PORT: typing.Final = int(os.environ.get("STUB_OTLP_PORT", "8139"))
OTLP_ENDPOINT: typing.Final = f"http://127.0.0.1:{OTLP_PORT}/v1/traces"
SAMPLE_RATIO: typing.Final = 0.01

APPS: typing.Final = ("async", "structlog")

log = structlog.get_logger("bench")

_EVERYTHING_OFF: typing.Final = {
    "prometheus_metrics_path": "",
    "health_checks_enabled": False,
    "swagger_offline_docs": False,
    "logging_enabled": False,
}
_OTEL: typing.Final = {
    "opentelemetry_endpoint": OTLP_ENDPOINT,
    "opentelemetry_exporter_protocol": "http",
}
_OTEL_EXCLUDE_SPANS: typing.Final = {"opentelemetry_exclude_spans": ["receive", "send"]}
_OTEL_SAMPLER: typing.Final = {"opentelemetry_sampler": ParentBased(TraceIdRatioBased(SAMPLE_RATIO))}
_PROMETHEUS: typing.Final = {"prometheus_metrics_path": "/metrics"}
_LOGGING: typing.Final = {"logging_enabled": True}
_SENTRY: typing.Final = {
    "sentry_dsn": DSN,
    "sentry_additional_params": {"transport": TRANSPORT},
}


def _sentry_tuned() -> dict[str, typing.Any]:
    """Sentry as an error sink only: OpenTelemetry owns distributed tracing here."""
    return {
        "sentry_dsn": DSN,
        "sentry_integrations": [
            StarletteIntegration(http_methods_to_capture=()),
            FastApiIntegration(http_methods_to_capture=()),
        ],
        "sentry_logging_breadcrumb_level": None,
        "sentry_auto_session_tracking": False,
        "sentry_additional_params": {"transport": TRANSPORT},
    }


def config(*parts: dict[str, typing.Any]) -> dict[str, typing.Any]:
    merged = {
        "service_name": "bench",
        "service_environment": "bench",
        "service_debug": False,
        **_EVERYTHING_OFF,
    }
    for part in parts:
        merged.update(part)
    return merged


SCENARIOS: dict[str, typing.Callable[[], dict[str, typing.Any]]] = {
    "bare": config,
    "otel": lambda: config(_OTEL),
    "prom": lambda: config(_PROMETHEUS),
    "log": lambda: config(_LOGGING),
    "sentry": lambda: config(_SENTRY),
    "full": lambda: config(_OTEL, _PROMETHEUS, _LOGGING, _SENTRY),
    "full_no_otel": lambda: config(_PROMETHEUS, _LOGGING, _SENTRY),
    "full_no_sentry": lambda: config(_OTEL, _PROMETHEUS, _LOGGING),
    "full_sentry_tuned": lambda: config(_OTEL, _PROMETHEUS, _LOGGING, _sentry_tuned()),
    "otel_exclude_spans": lambda: config(_OTEL, _OTEL_EXCLUDE_SPANS),
    "otel_sampler": lambda: config(_OTEL, _OTEL_SAMPLER),
    "otel_tuned": lambda: config(_OTEL, _OTEL_EXCLUDE_SPANS, _OTEL_SAMPLER),
    "full_all_tuned": lambda: config(_OTEL, _OTEL_EXCLUDE_SPANS, _OTEL_SAMPLER, _PROMETHEUS, _LOGGING, _sentry_tuned()),
}


def make_app(kind: str) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    if kind == "async":

        @app.get("/ping")
        async def ping() -> dict[str, bool]:
            return {"ok": True}

    elif kind == "structlog":

        @app.get("/ping")
        async def ping_log() -> dict[str, bool]:
            log.info("handling request", a=1)
            log.info("did a thing", b=2)
            log.info("done", c=3)
            return {"ok": True}

    else:
        msg = f"unknown app kind: {kind}"
        raise ValueError(msg)

    return app


def bootstrap(scenario: str, app: FastAPI) -> None:
    FastAPIBootstrapper(FastAPIConfig(application=app, **SCENARIOS[scenario]())).bootstrap()


def build(scenario: str, app_kind: str) -> FastAPI:
    app = make_app(app_kind)
    bootstrap(scenario, app)
    return app


__all__ = ["APPS", "SCENARIOS", "bootstrap", "build", "config", "make_app"]
