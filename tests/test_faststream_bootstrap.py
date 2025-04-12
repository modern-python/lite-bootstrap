import typing

import pytest
import structlog
from faststream.broker.core.usecase import BrokerUsecase
from faststream.redis import RedisBroker, TestRedisBroker
from faststream.redis.opentelemetry import RedisTelemetryMiddleware
from faststream.redis.prometheus import RedisPrometheusMiddleware
from opentelemetry.sdk.trace.export import ConsoleSpanExporter
from starlette import status
from starlette.testclient import TestClient

from lite_bootstrap import FastStreamBootstrapper, FastStreamConfig
from tests.conftest import CustomInstrumentor, emulate_package_missing


logger = structlog.getLogger(__name__)


@pytest.fixture
def broker() -> RedisBroker:
    return RedisBroker()


def build_faststream_config(broker: BrokerUsecase[typing.Any, typing.Any] | None = None) -> FastStreamConfig:
    return FastStreamConfig(
        service_name="microservice",
        service_version="2.0.0",
        service_environment="test",
        service_debug=False,
        opentelemetry_endpoint="otl",
        opentelemetry_instrumentors=[CustomInstrumentor()],
        opentelemetry_span_exporter=ConsoleSpanExporter(),
        opentelemetry_middleware_cls=RedisTelemetryMiddleware,
        prometheus_metrics_path="/custom-metrics/",
        prometheus_middleware_cls=RedisPrometheusMiddleware,
        sentry_dsn="https://testdsn@localhost/1",
        health_checks_path="/custom-health/",
        logging_buffer_capacity=0,
        broker=broker,
    )


async def test_faststream_bootstrap(broker: RedisBroker) -> None:
    bootstrap_config = build_faststream_config(broker=broker)
    bootstrapper = FastStreamBootstrapper(bootstrap_config=bootstrap_config)
    application = bootstrapper.bootstrap()
    test_client = TestClient(app=application)

    logger.info("testing logging", key="value")

    async with TestRedisBroker(broker):
        response = test_client.get(bootstrap_config.health_checks_path)
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"health_status": True, "service_name": "microservice", "service_version": "2.0.0"}

        response = test_client.get(bootstrap_config.prometheus_metrics_path)
        assert response.status_code == status.HTTP_200_OK


async def test_faststream_bootstrap_health_check_wo_broker() -> None:
    bootstrap_config = build_faststream_config()
    bootstrapper = FastStreamBootstrapper(bootstrap_config=bootstrap_config)
    application = bootstrapper.bootstrap()
    test_client = TestClient(app=application)

    response = test_client.get(bootstrap_config.health_checks_path)
    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert response.text == "Service is unhealthy"


def test_faststream_bootstrapper_not_ready() -> None:
    with emulate_package_missing("faststream"), pytest.raises(RuntimeError, match="faststream is not installed"):
        FastStreamBootstrapper(bootstrap_config=FastStreamConfig())


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
