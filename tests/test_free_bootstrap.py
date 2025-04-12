import pytest
import structlog
from opentelemetry.sdk.trace.export import ConsoleSpanExporter

from lite_bootstrap import FreeBootstrapper, FreeBootstrapperConfig
from tests.conftest import CustomInstrumentor, emulate_package_missing


logger = structlog.getLogger(__name__)


@pytest.fixture
def free_bootstrapper_config() -> FreeBootstrapperConfig:
    return FreeBootstrapperConfig(
        service_debug=False,
        opentelemetry_endpoint="otl",
        opentelemetry_instrumentors=[CustomInstrumentor()],
        opentelemetry_span_exporter=ConsoleSpanExporter(),
        sentry_dsn="https://testdsn@localhost/1",
        logging_buffer_capacity=0,
    )


def test_free_bootstrap(free_bootstrapper_config: FreeBootstrapperConfig) -> None:
    bootstrapper = FreeBootstrapper(bootstrap_config=free_bootstrapper_config)
    bootstrapper.bootstrap()
    try:
        logger.info("testing logging", key="value")
    finally:
        bootstrapper.teardown()


def test_free_bootstrap_logging_not_ready() -> None:
    with pytest.warns(UserWarning, match="service_debug is True or structlog is not installed"):
        FreeBootstrapper(
            bootstrap_config=FreeBootstrapperConfig(
                service_debug=True,
                opentelemetry_endpoint="otl",
                sentry_dsn="https://testdsn@localhost/1",
            ),
        )


@pytest.mark.parametrize(
    "package_name",
    [
        "opentelemetry",
        "sentry_sdk",
        "structlog",
    ],
)
def test_free_bootstrapper_with_missing_instrument_dependency(
    free_bootstrapper_config: FreeBootstrapperConfig, package_name: str
) -> None:
    with emulate_package_missing(package_name), pytest.warns(UserWarning, match=package_name):
        FreeBootstrapper(bootstrap_config=free_bootstrapper_config)
