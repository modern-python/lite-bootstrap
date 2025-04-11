import pytest
import structlog
from opentelemetry.sdk.trace.export import ConsoleSpanExporter
from starlette import status
from starlette.testclient import TestClient

from lite_bootstrap import FastAPIBootstrapper, FastAPIConfig, import_checker
from tests.conftest import CustomInstrumentor


logger = structlog.getLogger(__name__)


def test_fastapi_bootstrap() -> None:
    health_checks_path = "/custom-health/"
    prometheus_metrics_path = "/custom-metrics/"
    bootstrapper = FastAPIBootstrapper(
        bootstrap_config=FastAPIConfig(
            service_name="microservice",
            service_version="2.0.0",
            service_environment="test",
            service_debug=False,
            opentelemetry_endpoint="otl",
            opentelemetry_instrumentors=[CustomInstrumentor()],
            opentelemetry_span_exporter=ConsoleSpanExporter(),
            prometheus_metrics_path=prometheus_metrics_path,
            sentry_dsn="https://testdsn@localhost/1",
            health_checks_path=health_checks_path,
            logging_buffer_capacity=0,
        ),
    )
    application = bootstrapper.bootstrap()
    test_client = TestClient(application)

    logger.info("testing logging", key="value")

    try:
        response = test_client.get(health_checks_path)
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"health_status": True, "service_name": "microservice", "service_version": "2.0.0"}

        response = test_client.get(prometheus_metrics_path)
        assert response.status_code == status.HTTP_200_OK
        assert response.text
    finally:
        bootstrapper.teardown()


def test_fastapi_bootstrapper_not_ready() -> None:
    import_checker.is_fastapi_installed = False
    try:
        with pytest.raises(RuntimeError, match="fastapi is not installed"):
            FastAPIBootstrapper(bootstrap_config=FastAPIConfig())
    finally:
        import_checker.is_fastapi_installed = True
