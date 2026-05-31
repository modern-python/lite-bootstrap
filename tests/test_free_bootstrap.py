from unittest.mock import MagicMock

import pytest
import structlog
from structlog.testing import capture_logs

from lite_bootstrap import (
    FreeBootstrapper,
    FreeBootstrapperConfig,
    InstrumentNotReadyWarning,
    TeardownError,
)
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


def test_free_bootstrap_logging_disabled() -> None:
    with pytest.warns(InstrumentNotReadyWarning) as records:
        FreeBootstrapper(
            bootstrap_config=FreeBootstrapperConfig(
                logging_enabled=False,
                opentelemetry_instrumentors=[CustomInstrumentor()],
                opentelemetry_log_traces=True,
                sentry_dsn="https://testdsn@localhost/1",
                sentry_additional_params={"transport": SentryTestTransport()},
                logging_buffer_capacity=0,
            ),
        )
    messages = [str(r.message) for r in records]
    assert "LoggingInstrument is not ready: logging_enabled is False" in messages
    assert "PyroscopeInstrument is not ready: pyroscope_endpoint is empty" in messages


def test_teardown_error_isolation(free_bootstrapper_config: FreeBootstrapperConfig) -> None:
    bootstrapper = FreeBootstrapper(bootstrap_config=free_bootstrapper_config)
    bootstrapper.bootstrap()

    # Replace instruments with mocks: first raises, second succeeds.
    bad = MagicMock()
    bad.teardown.side_effect = RuntimeError("boom")
    good = MagicMock()
    bootstrapper.instruments = [bad, good]

    with capture_logs() as cap_logs, pytest.raises(TeardownError, match="boom") as excinfo:
        bootstrapper.teardown()

    # Both instruments attempted teardown despite the error (LIFO: good first, bad second).
    good.teardown.assert_called_once()
    bad.teardown.assert_called_once()
    assert any("boom" in entry.get("event", "") for entry in cap_logs)
    assert excinfo.value.errors == [("MagicMock", excinfo.value.__cause__)]


def test_teardown_error_aggregates_all_failures(free_bootstrapper_config: FreeBootstrapperConfig) -> None:
    bootstrapper = FreeBootstrapper(bootstrap_config=free_bootstrapper_config)
    bootstrapper.bootstrap()

    first = MagicMock()
    first.teardown.side_effect = RuntimeError("boom-1")
    second = MagicMock()
    second.teardown.side_effect = ValueError("boom-2")
    bootstrapper.instruments = [first, second]

    with pytest.raises(TeardownError) as excinfo:
        bootstrapper.teardown()

    msg = str(excinfo.value)
    assert "2 instrument(s) failed during teardown" in msg
    assert "boom-1" in msg
    assert "boom-2" in msg
    # `second` runs first under reversed(), so its ValueError is the chained cause.
    assert isinstance(excinfo.value.__cause__, ValueError)
    assert [name for name, _ in excinfo.value.errors] == ["MagicMock", "MagicMock"]


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


def test_teardown_is_idempotent(free_bootstrapper_config: FreeBootstrapperConfig) -> None:
    bootstrapper = FreeBootstrapper(bootstrap_config=free_bootstrapper_config)
    bootstrapper.bootstrap()

    first = MagicMock()
    second = MagicMock()
    bootstrapper.instruments = [first, second]

    bootstrapper.teardown()
    bootstrapper.teardown()

    first.teardown.assert_called_once()
    second.teardown.assert_called_once()
    assert not bootstrapper.is_bootstrapped
