import structlog
from opentelemetry.sdk.trace.export import ConsoleSpanExporter

from lite_bootstrap.bootstraps.free_bootstrap import FreeBootstrap
from lite_bootstrap.instruments.logging_instrument import LoggingInstrument
from lite_bootstrap.instruments.opentelemetry_instrument import OpenTelemetryInstrument
from lite_bootstrap.instruments.sentry_instrument import SentryInstrument
from lite_bootstrap.service_config import ServiceConfig
from tests.conftest import CustomInstrumentor


logger = structlog.getLogger(__name__)


def test_free_bootstrap(service_config: ServiceConfig) -> None:
    free_bootstrap = FreeBootstrap(
        service_config=service_config,
        instruments=[
            OpenTelemetryInstrument(
                endpoint="otl",
                instrumentors=[CustomInstrumentor()],
                span_exporter=ConsoleSpanExporter(),
            ),
            SentryInstrument(
                dsn="https://testdsn@localhost/1",
            ),
            LoggingInstrument(logging_buffer_capacity=0),
        ],
    )
    free_bootstrap.bootstrap()
    logger.info("testing logging", key="value")
