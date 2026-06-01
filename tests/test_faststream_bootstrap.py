import dataclasses
import logging
import typing
from unittest.mock import AsyncMock, patch

import faststream.asgi
import pytest
import structlog
from faststream._internal.broker import BrokerUsecase
from faststream._internal.logger.params_storage import ManualLoggerStorage
from faststream.redis import RedisBroker, TestRedisBroker
from faststream.redis.opentelemetry import RedisTelemetryMiddleware
from faststream.redis.prometheus import RedisPrometheusMiddleware
from starlette import status
from starlette.testclient import TestClient

from lite_bootstrap import FastStreamBootstrapper, FastStreamConfig
from tests.conftest import (
    CustomInstrumentor,
    SentryTestTransport,
    emulate_package_missing,
    emulate_package_missing_with_module_reload,
)


logger = structlog.getLogger(__name__)


@pytest.fixture
def broker() -> RedisBroker:
    return RedisBroker()


def build_faststream_config(
    broker: BrokerUsecase[typing.Any, typing.Any] | None = None,
) -> FastStreamConfig:
    return FastStreamConfig(
        service_name="microservice",
        service_version="2.0.0",
        service_environment="test",
        service_debug=False,
        opentelemetry_instrumentors=[CustomInstrumentor()],
        opentelemetry_log_traces=True,
        opentelemetry_middleware_cls=RedisTelemetryMiddleware,
        prometheus_metrics_path="/custom-metrics/",
        prometheus_middleware_cls=RedisPrometheusMiddleware,
        sentry_dsn="https://testdsn@localhost/1",
        sentry_additional_params={"transport": SentryTestTransport()},
        health_checks_path="/custom-health/",
        logging_buffer_capacity=0,
        application=faststream.asgi.AsgiFastStream(
            broker,
            asyncapi_path=faststream.asgi.AsyncAPIRoute("/docs/"),
            specification=faststream.AsyncAPI(),
        ),
    )


async def test_faststream_bootstrap(broker: RedisBroker) -> None:
    bootstrap_config = build_faststream_config(broker=broker)
    bootstrapper = FastStreamBootstrapper(bootstrap_config=bootstrap_config)
    application = bootstrapper.bootstrap()
    assert bootstrapper.is_bootstrapped
    logger.info("testing logging", key="value")

    with TestClient(app=application) as test_client:
        async with TestRedisBroker(broker):
            response = test_client.get(bootstrap_config.health_checks_path)
            assert response.status_code == status.HTTP_200_OK
            assert response.json() == {
                "health_status": True,
                "service_name": "microservice",
                "service_version": "2.0.0",
            }

            response = test_client.get(bootstrap_config.prometheus_metrics_path)
            assert response.status_code == status.HTTP_200_OK

            response = test_client.get("/docs/")
            assert response.status_code == status.HTTP_200_OK

    assert not bootstrapper.is_bootstrapped


async def test_faststream_bootstrap_health_check_wo_broker() -> None:
    bootstrap_config = build_faststream_config()
    bootstrapper = FastStreamBootstrapper(bootstrap_config=bootstrap_config)
    application = bootstrapper.bootstrap()
    test_client = TestClient(app=application)

    response = test_client.get(bootstrap_config.health_checks_path)
    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert response.text == "Service is unhealthy"
    bootstrapper.teardown()


def test_faststream_logging_instrument_injects_structlog_logger(broker: RedisBroker) -> None:
    bootstrap_config = FastStreamConfig(
        service_debug=False,
        logging_buffer_capacity=0,
        logging_log_level=logging.INFO,
        faststream_log_level=logging.WARNING,
        application=faststream.asgi.AsgiFastStream(broker),
    )
    bootstrapper = FastStreamBootstrapper(bootstrap_config=bootstrap_config)
    bootstrapper.bootstrap()
    try:
        assert isinstance(broker.config.logger.params_storage, ManualLoggerStorage)
        assert logging.getLogger("faststream").level == logging.WARNING
    finally:
        bootstrapper.teardown()


def test_faststream_config_default_application() -> None:
    config = FastStreamConfig()
    assert isinstance(config.application, faststream.asgi.AsgiFastStream)


def test_faststream_bootstrapper_not_ready() -> None:
    with emulate_package_missing("faststream"), pytest.raises(RuntimeError, match="faststream is not installed"):
        FastStreamBootstrapper(bootstrap_config=FastStreamConfig(application=faststream.asgi.AsgiFastStream()))


@pytest.mark.parametrize(
    "package_name",
    [
        "opentelemetry",
        "sentry_sdk",
        "structlog",
        "prometheus_client",
    ],
)
def test_faststream_bootstrapper_with_missing_instrument_dependency(broker: RedisBroker, package_name: str) -> None:
    bootstrap_config = build_faststream_config(broker=broker)
    with emulate_package_missing(package_name), pytest.warns(UserWarning, match=package_name):
        FastStreamBootstrapper(bootstrap_config=bootstrap_config)


def test_faststream_bootstrap_without_prometheus_client(broker: RedisBroker) -> None:
    # Regression: issue #87 bug 1 — FastStreamPrometheusInstrument's
    # default_factory called prometheus_client.CollectorRegistry() during
    # dataclass __init__, raising NameError before check_dependencies() ran.
    bootstrap_config = build_faststream_config(broker=broker)
    with emulate_package_missing_with_module_reload(
        "prometheus_client",
        ["lite_bootstrap.bootstrappers.faststream_bootstrapper"],
    ):
        with pytest.warns(UserWarning, match="prometheus_client"):
            bootstrapper = FastStreamBootstrapper(bootstrap_config=bootstrap_config)
        bootstrapper.bootstrap()


def test_faststream_bootstrap_without_opentelemetry(broker: RedisBroker) -> None:
    # Regression: issue #87 bug 2 — FastStreamHealthChecksInstrument.bootstrap
    # referenced unbound `tracer` when opentelemetry was absent and
    # opentelemetry_generate_health_check_spans defaulted to True.
    bootstrap_config = build_faststream_config(broker=broker)
    with emulate_package_missing_with_module_reload(
        "opentelemetry",
        ["lite_bootstrap.bootstrappers.faststream_bootstrapper"],
    ):
        bootstrapper = FastStreamBootstrapper(bootstrap_config=bootstrap_config)
        bootstrapper.bootstrap()


async def test_faststream_health_check_uses_configured_broker_timeout(broker: RedisBroker) -> None:
    expected_timeout = 12.5
    config = dataclasses.replace(
        build_faststream_config(broker=broker),
        faststream_health_check_broker_timeout=expected_timeout,
    )
    bootstrapper = FastStreamBootstrapper(bootstrap_config=config)
    application = bootstrapper.bootstrap()
    try:
        with (
            patch.object(broker, "ping", new=AsyncMock(return_value=True)) as mock_ping,
            TestClient(app=application) as test_client,
        ):
            response = test_client.get(config.health_checks_path)
            assert response.status_code == status.HTTP_200_OK
        mock_ping.assert_called_once_with(timeout=expected_timeout)
    finally:
        bootstrapper.teardown()
