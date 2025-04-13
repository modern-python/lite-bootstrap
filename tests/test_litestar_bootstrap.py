import pytest
import structlog
from litestar import status_codes
from litestar.testing import TestClient
from opentelemetry.sdk.trace.export import ConsoleSpanExporter

from lite_bootstrap import LitestarBootstrapper, LitestarConfig
from tests.conftest import CustomInstrumentor, emulate_package_missing


logger = structlog.getLogger(__name__)


@pytest.fixture
def litestar_config() -> LitestarConfig:
    return LitestarConfig(
        service_name="microservice",
        service_version="2.0.0",
        service_environment="test",
        service_debug=False,
        cors_allowed_origins=["http://test"],
        health_checks_path="/custom-health/",
        opentelemetry_endpoint="otl",
        opentelemetry_instrumentors=[CustomInstrumentor()],
        opentelemetry_span_exporter=ConsoleSpanExporter(),
        prometheus_metrics_path="/custom-metrics/",
        sentry_dsn="https://testdsn@localhost/1",
        swagger_offline_docs=True,
        logging_buffer_capacity=0,
    )


def test_litestar_bootstrap(litestar_config: LitestarConfig) -> None:
    bootstrapper = LitestarBootstrapper(bootstrap_config=litestar_config)
    application = bootstrapper.bootstrap()

    try:
        logger.info("testing logging", key="value")

        assert application.cors_config
        assert application.cors_config.allow_origins == litestar_config.cors_allowed_origins

        with TestClient(app=application) as test_client:
            response = test_client.get(litestar_config.health_checks_path)
            assert response.status_code == status_codes.HTTP_200_OK
            assert response.json() == {
                "health_status": True,
                "service_name": "microservice",
                "service_version": "2.0.0",
            }

            response = test_client.get(litestar_config.prometheus_metrics_path)
            assert response.status_code == status_codes.HTTP_200_OK
            assert response.text

            response = test_client.get(litestar_config.swagger_path)
            assert response.status_code == status_codes.HTTP_200_OK
            response = test_client.get(f"{litestar_config.service_static_path}/swagger-ui.css")
            assert response.status_code == status_codes.HTTP_200_OK
    finally:
        bootstrapper.teardown()


def test_litestar_bootstrapper_not_ready() -> None:
    with emulate_package_missing("litestar"), pytest.raises(RuntimeError, match="litestar is not installed"):
        LitestarBootstrapper(bootstrap_config=LitestarConfig())


@pytest.mark.parametrize(
    "package_name",
    [
        "opentelemetry",
        "sentry_sdk",
        "structlog",
        "prometheus_client",
    ],
)
def test_litestar_bootstrapper_with_missing_instrument_dependency(
    litestar_config: LitestarConfig, package_name: str
) -> None:
    with emulate_package_missing(package_name), pytest.warns(UserWarning, match=package_name):
        LitestarBootstrapper(bootstrap_config=litestar_config)
