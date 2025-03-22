import structlog
from opentelemetry.sdk.trace.export import ConsoleSpanExporter

from lite_bootstrap import FreeBootstrapper, LoggingInstrument, OpenTelemetryInstrument, SentryInstrument, ServiceConfig
from tests.conftest import CustomInstrumentor


logger = structlog.getLogger(__name__)


def test_free_bootstrap(service_config: ServiceConfig) -> None:
    bootstrapper = FreeBootstrapper(
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
    bootstrapper.bootstrap()
    try:
        logger.info("testing logging", key="value")
    finally:
        bootstrapper.teardown()
