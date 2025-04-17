import dataclasses

import fastapi
import pytest
import structlog
from opentelemetry.sdk.trace.export import ConsoleSpanExporter
from starlette import status
from starlette.testclient import TestClient

from lite_bootstrap import FastAPIBootstrapper, FastAPIConfig
from tests.conftest import CustomInstrumentor, emulate_package_missing


logger = structlog.getLogger(__name__)


@pytest.fixture
def fastapi_config() -> FastAPIConfig:
    return FastAPIConfig(
        service_name="microservice",
        service_version="2.0.0",
        service_environment="test",
        service_debug=False,
        cors_allowed_origins=["http://test"],
        health_checks_path="/custom-health/",
        logging_buffer_capacity=0,
        opentelemetry_endpoint="otl",
        opentelemetry_instrumentors=[CustomInstrumentor()],
        opentelemetry_span_exporter=ConsoleSpanExporter(),
        prometheus_metrics_path="/custom-metrics/",
        sentry_dsn="https://testdsn@localhost/1",
        swagger_offline_docs=True,
    )


def test_fastapi_bootstrap(fastapi_config: FastAPIConfig) -> None:
    bootstrapper = FastAPIBootstrapper(bootstrap_config=fastapi_config)
    application = bootstrapper.bootstrap()
    assert bootstrapper.is_bootstrapped
    logger.info("testing logging", key="value")

    with TestClient(application) as test_client:
        response = test_client.get(fastapi_config.health_checks_path)
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"health_status": True, "service_name": "microservice", "service_version": "2.0.0"}

        response = test_client.get(fastapi_config.prometheus_metrics_path)
        assert response.status_code == status.HTTP_200_OK
        assert response.text

        response = test_client.get(str(application.docs_url))
        assert response.status_code == status.HTTP_200_OK
        assert response.text

        response = test_client.get(str(application.redoc_url))
        assert response.status_code == status.HTTP_200_OK
        assert response.text

    assert not bootstrapper.is_bootstrapped


def test_fastapi_bootstrapper_not_ready() -> None:
    with emulate_package_missing("fastapi"), pytest.raises(RuntimeError, match="fastapi is not installed"):
        FastAPIBootstrapper(bootstrap_config=FastAPIConfig())


def test_fastapi_bootstrapper_docs_url_differ(fastapi_config: FastAPIConfig) -> None:
    new_config = dataclasses.replace(fastapi_config, application=fastapi.FastAPI(docs_url="/custom-docs/"))
    bootstrapper = FastAPIBootstrapper(bootstrap_config=new_config)
    with pytest.warns(UserWarning, match="swagger_path is differ from docs_url"):
        bootstrapper.bootstrap()


@pytest.mark.parametrize(
    "package_name",
    [
        "opentelemetry",
        "sentry_sdk",
        "structlog",
        "prometheus_fastapi_instrumentator",
    ],
)
def test_fastapi_bootstrapper_with_missing_instrument_dependency(
    fastapi_config: FastAPIConfig, package_name: str
) -> None:
    with emulate_package_missing(package_name), pytest.warns(UserWarning, match=package_name):
        FastAPIBootstrapper(bootstrap_config=fastapi_config)
