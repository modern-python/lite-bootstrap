import structlog
from litestar import status_codes
from litestar.testing import TestClient
from opentelemetry.sdk.trace.export import ConsoleSpanExporter

from lite_bootstrap import LitestarBootstrapper, LitestarConfig
from tests.conftest import CustomInstrumentor


logger = structlog.getLogger(__name__)


def test_litestar_bootstrap() -> None:
    bootstrapper = LitestarBootstrapper(
        bootstrap_config=LitestarConfig(
            service_name="microservice",
            service_version="2.0.0",
            service_environment="test",
            opentelemetry_endpoint="otl",
            opentelemetry_instrumentors=[CustomInstrumentor()],
            opentelemetry_span_exporter=ConsoleSpanExporter(),
            sentry_dsn="https://testdsn@localhost/1",
            health_checks_path="/health/",
            logging_buffer_capacity=0,
        ),
    )
    application = bootstrapper.bootstrap()
    logger.info("testing logging", key="value")

    try:
        with TestClient(app=application) as test_client:
            response = test_client.get("/health/")
            assert response.status_code == status_codes.HTTP_200_OK
            assert response.json() == {
                "health_status": True,
                "service_name": "microservice",
                "service_version": "2.0.0",
            }
    finally:
        bootstrapper.teardown()


def test_litestar_prometheus_bootstrap() -> None:
    prometheus_metrics_path = "/custom-metrics-path"
    bootstrapper = LitestarBootstrapper(
        bootstrap_config=LitestarConfig(prometheus_metrics_path=prometheus_metrics_path),
    )
    application = bootstrapper.bootstrap()

    with TestClient(app=application) as test_client:
        response = test_client.get(prometheus_metrics_path)
        assert response.status_code == status_codes.HTTP_200_OK
        assert response.text
