import dataclasses
import logging
import warnings

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


def test_second_fastapi_bootstrapper_on_same_app_warns_not_stacks(fastapi_config: FastAPIConfig) -> None:
    application = fastapi.FastAPI()
    config_a = dataclasses.replace(fastapi_config, application=application)
    FastAPIBootstrapper(bootstrap_config=config_a)
    lifespan_after_first = application.router.lifespan_context

    config_b = dataclasses.replace(fastapi_config, application=application)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        FastAPIBootstrapper(bootstrap_config=config_b)

    matching = [w for w in caught if "already has a lite-bootstrap teardown hook" in str(w.message)]
    assert matching, "expected warning about existing lite-bootstrap teardown hook"
    assert application.router.lifespan_context is lifespan_after_first, (
        "second bootstrapper must not re-wrap the lifespan"
    )


def test_narrow_app_raises_when_application_unset() -> None:
    # Build a config and forcibly reset application to UNSET to simulate the
    # invariant violation `_narrow_app` was guarding with an assert.
    config = FastAPIConfig()
    object.__setattr__(config, "application", UNSET)
    with pytest.raises(TypeError, match="application is UNSET"):
        _narrow_app(config)


def test_user_supplied_app_keeps_title_version_debug() -> None:
    user_app = fastapi.FastAPI(title="user-title", version="9.9.9", debug=False)
    config = FastAPIConfig(
        application=user_app,
        service_name="lite-name",
        service_version="1.0.0",
        service_debug=True,
    )
    assert config.application is user_app
    assert user_app.title == "user-title"
    assert user_app.version == "9.9.9"
    assert user_app.debug is False


def test_fastapi_config_inherits_otel_insecure_warning() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        FastAPIConfig(
            opentelemetry_endpoint="http://collector.example.com:4317",
            opentelemetry_insecure=True,
        )
    matching = [w for w in caught if "unencrypted" in str(w.message)]
    assert matching, [str(w.message) for w in caught]
