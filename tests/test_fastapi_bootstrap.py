import structlog
from fastapi import FastAPI
from opentelemetry.sdk.trace.export import ConsoleSpanExporter
from starlette import status
from starlette.testclient import TestClient

from lite_bootstrap import (
    FastAPIBootstrapper,
    FastAPIHealthChecksInstrument,
    FastAPILoggingInstrument,
    FastAPIOpenTelemetryInstrument,
    FastAPIPrometheusInstrument,
    FastAPISentryInstrument,
    ServiceConfig,
)
from tests.conftest import CustomInstrumentor


logger = structlog.getLogger(__name__)


def test_fastapi_bootstrap(fastapi_app: FastAPI, service_config: ServiceConfig) -> None:
    bootstrapper = FastAPIBootstrapper(
        bootstrap_object=fastapi_app,
        service_config=service_config,
        instruments=[
            FastAPIOpenTelemetryInstrument(
                endpoint="otl",
                instrumentors=[CustomInstrumentor()],
                span_exporter=ConsoleSpanExporter(),
            ),
            FastAPISentryInstrument(
                dsn="https://testdsn@localhost/1",
            ),
            FastAPIHealthChecksInstrument(
                path="/health/",
            ),
            FastAPILoggingInstrument(logging_buffer_capacity=0),
            FastAPIPrometheusInstrument(),
        ],
    )
    bootstrapper.bootstrap()
    logger.info("testing logging", key="value")

    try:
        response = TestClient(fastapi_app).get("/health/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"health_status": True, "service_name": "microservice", "service_version": "2.0.0"}
    finally:
        bootstrapper.teardown()


def test_fastapi_prometheus_instrument(fastapi_app: FastAPI, service_config: ServiceConfig) -> None:
    prometheus_instrument = FastAPIPrometheusInstrument(metrics_path="/custom-metrics-path")
    prometheus_instrument.bootstrap(service_config, fastapi_app)

    response = TestClient(fastapi_app).get(prometheus_instrument.metrics_path)
    assert response.status_code == status.HTTP_200_OK
    assert response.text
