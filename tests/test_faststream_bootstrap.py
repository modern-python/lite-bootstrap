import pytest
import structlog
from faststream.redis import RedisBroker, TestRedisBroker
from faststream.redis.opentelemetry import RedisTelemetryMiddleware
from faststream.redis.prometheus import RedisPrometheusMiddleware
from opentelemetry.sdk.trace.export import ConsoleSpanExporter
from starlette import status
from starlette.testclient import TestClient

from lite_bootstrap import FastStreamBootstrapper, FastStreamConfig, import_checker
from tests.conftest import CustomInstrumentor


logger = structlog.getLogger(__name__)


@pytest.fixture
def broker() -> RedisBroker:
    return RedisBroker()


async def test_faststream_bootstrap(broker: RedisBroker) -> None:
    prometheus_metrics_path = "/custom-metrics/"
    health_check_path = "/custom-health/"
    bootstrapper = FastStreamBootstrapper(
        bootstrap_config=FastStreamConfig(
            broker=broker,
            service_name="microservice",
            service_version="2.0.0",
            service_environment="test",
            service_debug=False,
            opentelemetry_endpoint="otl",
            opentelemetry_instrumentors=[CustomInstrumentor()],
            opentelemetry_span_exporter=ConsoleSpanExporter(),
            opentelemetry_middleware_cls=RedisTelemetryMiddleware,
            prometheus_metrics_path=prometheus_metrics_path,
            prometheus_middleware_cls=RedisPrometheusMiddleware,
            sentry_dsn="https://testdsn@localhost/1",
            health_checks_path=health_check_path,
            logging_buffer_capacity=0,
        ),
    )
    application = bootstrapper.bootstrap()
    test_client = TestClient(app=application)

    logger.info("testing logging", key="value")

    async with TestRedisBroker(broker):
        response = test_client.get(health_check_path)
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"health_status": True, "service_name": "microservice", "service_version": "2.0.0"}

        response = test_client.get(prometheus_metrics_path)
        assert response.status_code == status.HTTP_200_OK


async def test_faststream_bootstrap_health_check_wo_broker() -> None:
    health_check_path = "/custom-health-check-path"
    bootstrapper = FastStreamBootstrapper(
        bootstrap_config=FastStreamConfig(
            service_name="microservice",
            service_version="2.0.0",
            service_environment="test",
            service_debug=False,
            opentelemetry_endpoint="otl",
            opentelemetry_instrumentors=[CustomInstrumentor()],
            opentelemetry_span_exporter=ConsoleSpanExporter(),
            opentelemetry_middleware_cls=RedisTelemetryMiddleware,
            prometheus_middleware_cls=RedisPrometheusMiddleware,
            sentry_dsn="https://testdsn@localhost/1",
            health_checks_path=health_check_path,
            logging_buffer_capacity=0,
        ),
    )
    application = bootstrapper.bootstrap()
    test_client = TestClient(app=application)

    response = test_client.get(health_check_path)
    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert response.text == "Service is unhealthy"


def test_faststream_bootstrapper_not_ready() -> None:
    import_checker.is_faststream_installed = False
    try:
        with pytest.raises(RuntimeError, match="faststream is not installed"):
            FastStreamBootstrapper(
                bootstrap_config=FastStreamConfig(),
            )
    finally:
        import_checker.is_faststream_installed = True
