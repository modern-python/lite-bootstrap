import dataclasses
import logging

import fastapi
import pytest
import structlog
from starlette import status
from starlette.testclient import TestClient

from lite_bootstrap import FastAPIBootstrapper, FastAPIConfig
from lite_bootstrap.bootstrappers.fastapi_bootstrapper import _narrow_app
from lite_bootstrap.types import UNSET
from tests.conftest import CustomInstrumentor, SentryTestTransport, emulate_package_missing


logger = structlog.getLogger(__name__)
std_logger = logging.getLogger()


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
        opentelemetry_instrumentors=[CustomInstrumentor()],
        opentelemetry_log_traces=True,
        opentelemetry_generate_health_check_spans=False,
        prometheus_metrics_path="/custom-metrics/",
        sentry_dsn="https://testdsn@localhost/1",
        sentry_additional_params={"transport": SentryTestTransport()},
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


def test_fastapi_bootstrap_std_logger(fastapi_config: FastAPIConfig, capsys: pytest.CaptureFixture[str]) -> None:
    bootstrapper = FastAPIBootstrapper(bootstrap_config=fastapi_config)
    application = bootstrapper.bootstrap()

    @application.get("/")
    async def home() -> str:
        std_logger.info("std logger")
        logger.info("structlog logger")
        return ""

    with TestClient(application) as test_client:
        test_client.get("/")

    stdout = capsys.readouterr().out
    assert '"event":"std logger","level":"info","logger":"root"' in stdout
    assert stdout.count("std logger") == 1


def test_fastapi_bootstrapper_not_ready() -> None:
    with emulate_package_missing("fastapi"), pytest.raises(RuntimeError, match="fastapi is not installed"):
        FastAPIBootstrapper(bootstrap_config=FastAPIConfig())


def test_fastapi_bootstrapper_docs_url_differ(fastapi_config: FastAPIConfig) -> None:
    new_config = dataclasses.replace(fastapi_config, application=fastapi.FastAPI(docs_url="/custom-docs/"))
    bootstrapper = FastAPIBootstrapper(bootstrap_config=new_config)
    with pytest.warns(UserWarning, match="swagger_path differs from docs_url"):
        bootstrapper.bootstrap()
    bootstrapper.teardown()


def test_fastapi_bootstrapper_apps_and_kwargs_warning(fastapi_config: FastAPIConfig) -> None:
    with pytest.warns(UserWarning, match="application_kwargs must be used without application"):
        dataclasses.replace(fastapi_config, application=fastapi.FastAPI(), application_kwargs={"title": "some title"})


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


def test_narrow_app_raises_when_application_unset() -> None:
    # Build a config and forcibly reset application to UNSET to simulate the
    # invariant violation `_narrow_app` was guarding with an assert.
    config = FastAPIConfig()
    object.__setattr__(config, "application", UNSET)
    with pytest.raises(TypeError, match="application is UNSET"):
        _narrow_app(config)
