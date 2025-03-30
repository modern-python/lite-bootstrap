import structlog
from opentelemetry.sdk.trace.export import ConsoleSpanExporter
from starlette import status
from starlette.testclient import TestClient

from lite_bootstrap import FastAPIBootstrapper, FastAPIConfig
from tests.conftest import CustomInstrumentor


logger = structlog.getLogger(__name__)


def test_fastapi_bootstrap() -> None:
    bootstrapper = FastAPIBootstrapper(
        bootstrap_config=FastAPIConfig(
            service_name="microservice",
            service_version="2.0.0",
            service_environment="test",
            service_debug=False,
            opentelemetry_endpoint="otl",
            opentelemetry_instrumentors=[CustomInstrumentor()],
            opentelemetry_span_exporter=ConsoleSpanExporter(),
            sentry_dsn="https://testdsn@localhost/1",
            health_checks_path="/health/",
            logging_buffer_capacity=0,
        ),
    )
    fastapi_app = bootstrapper.bootstrap()
    logger.info("testing logging", key="value")

    try:
        response = TestClient(fastapi_app).get("/health/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"health_status": True, "service_name": "microservice", "service_version": "2.0.0"}
    finally:
        bootstrapper.teardown()


def test_fastapi_prometheus_instrument() -> None:
    prometheus_metrics_path = "/custom-metrics-path"
    bootstrapper = FastAPIBootstrapper(
        bootstrap_config=FastAPIConfig(
            prometheus_metrics_path=prometheus_metrics_path,
        ),
    )
    fastapi_app = bootstrapper.bootstrap()

    response = TestClient(fastapi_app).get(prometheus_metrics_path)
    assert response.status_code == status.HTTP_200_OK
    assert response.text
