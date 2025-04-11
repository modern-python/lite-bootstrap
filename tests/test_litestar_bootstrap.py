import pytest
import structlog
from litestar import status_codes
from litestar.testing import TestClient
from opentelemetry.sdk.trace.export import ConsoleSpanExporter

from lite_bootstrap import LitestarBootstrapper, LitestarConfig, import_checker
from tests.conftest import CustomInstrumentor


logger = structlog.getLogger(__name__)


def test_litestar_bootstrap() -> None:
    health_checks_path = "/custom-health/"
    prometheus_metrics_path = "/custom-metrics/"
    bootstrapper = LitestarBootstrapper(
        bootstrap_config=LitestarConfig(
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

    try:
        logger.info("testing logging", key="value")

        with TestClient(app=application) as test_client:
            response = test_client.get(health_checks_path)
            assert response.status_code == status_codes.HTTP_200_OK
            assert response.json() == {
                "health_status": True,
                "service_name": "microservice",
                "service_version": "2.0.0",
            }

            response = test_client.get(prometheus_metrics_path)
            assert response.status_code == status_codes.HTTP_200_OK
            assert response.text
    finally:
        bootstrapper.teardown()


def test_litestar_bootstrapper_not_ready() -> None:
    import_checker.is_litestar_installed = False
    try:
        with pytest.raises(RuntimeError, match="litestar is not installed"):
            LitestarBootstrapper(
                bootstrap_config=LitestarConfig(),
            )
    finally:
        import_checker.is_litestar_installed = True
