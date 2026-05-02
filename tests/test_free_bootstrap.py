from unittest.mock import MagicMock

import pytest
import structlog
from structlog.testing import capture_logs

from lite_bootstrap import FreeBootstrapper, FreeBootstrapperConfig
from tests.conftest import CustomInstrumentor, SentryTestTransport, emulate_package_missing


logger = structlog.getLogger(__name__)


@pytest.fixture
def free_bootstrapper_config() -> FreeBootstrapperConfig:
    return FreeBootstrapperConfig(
        service_debug=False,
        opentelemetry_instrumentors=[CustomInstrumentor()],
        opentelemetry_log_traces=True,
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
    with capture_logs() as cap_logs:
        FreeBootstrapper(
            bootstrap_config=FreeBootstrapperConfig(
                service_debug=True,
                opentelemetry_instrumentors=[CustomInstrumentor()],
                opentelemetry_log_traces=True,
                sentry_dsn="https://testdsn@localhost/1",
                sentry_additional_params={"transport": SentryTestTransport()},
                logging_buffer_capacity=0,
            ),
        )
        assert cap_logs == [
            {"event": "LoggingInstrument is not ready: service_debug is True", "log_level": "info"},
            {"event": "PyroscopeInstrument is not ready: pyroscope_endpoint is empty", "log_level": "info"},
        ]


def test_teardown_error_isolation(free_bootstrapper_config: FreeBootstrapperConfig) -> None:
    bootstrapper = FreeBootstrapper(bootstrap_config=free_bootstrapper_config)
    bootstrapper.bootstrap()

    # Replace instruments with mocks: first raises, second succeeds.
    bad = MagicMock()
    bad.teardown.side_effect = RuntimeError("boom")
    good = MagicMock()
    bootstrapper.instruments = [bad, good]

    with capture_logs() as cap_logs, pytest.raises(RuntimeError, match="1 instrument"):
        bootstrapper.teardown()

    # Both instruments attempted teardown despite the error (LIFO: good first, bad second).
    good.teardown.assert_called_once()
    bad.teardown.assert_called_once()
    assert any("boom" in entry.get("event", "") for entry in cap_logs)


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
