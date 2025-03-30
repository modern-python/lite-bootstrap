import structlog
from opentelemetry.sdk.trace.export import ConsoleSpanExporter

from lite_bootstrap import FreeBootstrapper, FreeBootstrapperConfig
from tests.conftest import CustomInstrumentor


logger = structlog.getLogger(__name__)


def test_free_bootstrap() -> None:
    bootstrapper = FreeBootstrapper(
        bootstrap_config=FreeBootstrapperConfig(
            opentelemetry_endpoint="otl",
            opentelemetry_instrumentors=[CustomInstrumentor()],
            opentelemetry_span_exporter=ConsoleSpanExporter(),
            sentry_dsn="https://testdsn@localhost/1",
            logging_buffer_capacity=0,
        ),
    )
    bootstrapper.bootstrap()
    try:
        logger.info("testing logging", key="value")
    finally:
        bootstrapper.teardown()
