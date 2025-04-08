import pytest
import structlog
from faststream.redis import RedisBroker, TestRedisBroker
from faststream.redis.prometheus import RedisPrometheusMiddleware
from opentelemetry.sdk.trace.export import ConsoleSpanExporter
from starlette import status
from starlette.testclient import TestClient

from lite_bootstrap import FastStreamBootstrapper, FastStreamConfig
from tests.conftest import CustomInstrumentor


logger = structlog.getLogger(__name__)


@pytest.fixture
def broker() -> RedisBroker:
    return RedisBroker()


async def test_faststream_bootstrap(broker: RedisBroker) -> None:
    prometheus_metrics_path = "/test-metrics-path"
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
            prometheus_metrics_path=prometheus_metrics_path,
            prometheus_middleware_cls=RedisPrometheusMiddleware,
            sentry_dsn="https://testdsn@localhost/1",
            health_checks_path="/health/",
            logging_buffer_capacity=0,
        ),
    )
    application = bootstrapper.bootstrap()
    logger.info("testing logging", key="value")

    async with TestRedisBroker(broker):
        response = TestClient(app=application).get(prometheus_metrics_path)
        assert response.status_code == status.HTTP_200_OK
