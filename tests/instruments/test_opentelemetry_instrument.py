import logging
import warnings
from unittest.mock import patch

import pytest

from lite_bootstrap.instruments.opentelemetry_instrument import (
    InstrumentorWithParams,
    OpenTelemetryConfig,
    OpenTelemetryInstrument,
)
from tests.conftest import CustomInstrumentor


def test_opentelemetry_instrument() -> None:
    opentelemetry_instrument = OpenTelemetryInstrument(
        bootstrap_config=OpenTelemetryConfig(
            opentelemetry_instrumentors=[
                InstrumentorWithParams(instrumentor=CustomInstrumentor(), additional_params={"key": "value"}),
                CustomInstrumentor(),
            ],
            opentelemetry_log_traces=True,
        )
    )
    try:
        opentelemetry_instrument.bootstrap()
    finally:
        opentelemetry_instrument.teardown()


def test_opentelemetry_instrument_empty_instruments() -> None:
    opentelemetry_instrument = OpenTelemetryInstrument(
        bootstrap_config=OpenTelemetryConfig(
            opentelemetry_log_traces=True,
        )
    )
    try:
        opentelemetry_instrument.bootstrap()
    finally:
        opentelemetry_instrument.teardown()


def test_opentelemetry_instrument_teardown_shuts_down_tracer_provider() -> None:
    instrument = OpenTelemetryInstrument(
        bootstrap_config=OpenTelemetryConfig(opentelemetry_log_traces=True),
    )
    instrument.bootstrap()
    tracer_provider = instrument._tracer_provider  # noqa: SLF001
    assert tracer_provider is not None

    with patch.object(tracer_provider, "shutdown") as mock_shutdown:
        instrument.teardown()

    mock_shutdown.assert_called_once_with()
    assert instrument._tracer_provider is None  # noqa: SLF001


def test_opentelemetry_instrument_teardown_resets_tracer_provider_when_shutdown_raises() -> None:
    instrument = OpenTelemetryInstrument(
        bootstrap_config=OpenTelemetryConfig(opentelemetry_log_traces=True),
    )
    instrument.bootstrap()
    tracer_provider = instrument._tracer_provider  # noqa: SLF001
    assert tracer_provider is not None

    with (
        patch.object(tracer_provider, "shutdown", side_effect=RuntimeError("boom")),
        pytest.raises(RuntimeError, match="boom"),
    ):
        instrument.teardown()

    assert instrument._tracer_provider is None  # noqa: SLF001


def test_opentelemetry_teardown_restores_disabled_loggers() -> None:
    instrumentor_logger = logging.getLogger("opentelemetry.instrumentation.instrumentor")
    trace_logger = logging.getLogger("opentelemetry.trace")
    # Capture pre-bootstrap state so the assertion is independent of test order.
    prior_instrumentor_disabled = instrumentor_logger.disabled
    prior_trace_disabled = trace_logger.disabled

    instrument = OpenTelemetryInstrument(
        bootstrap_config=OpenTelemetryConfig(opentelemetry_log_traces=True),
    )
    instrument.bootstrap()
    assert instrumentor_logger.disabled is True
    assert trace_logger.disabled is True

    instrument.teardown()

    assert instrumentor_logger.disabled is prior_instrumentor_disabled
    assert trace_logger.disabled is prior_trace_disabled


@pytest.mark.parametrize(
    "endpoint",
    [
        "localhost:4317",
        "127.0.0.1:4317",
        "[::1]:4317",
        "http://localhost:4317",
        "https://127.0.0.1:4317",
    ],
)
def test_opentelemetry_config_no_warning_for_local_endpoints(endpoint: str) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        OpenTelemetryConfig(opentelemetry_endpoint=endpoint, opentelemetry_insecure=True)


@pytest.mark.parametrize(
    "endpoint",
    [
        "collector.example.com:4317",
        "http://collector.example.com:4317",
        "grpc://collector.example.com:4317",
    ],
)
def test_opentelemetry_config_warns_for_remote_endpoints(endpoint: str) -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        OpenTelemetryConfig(opentelemetry_endpoint=endpoint, opentelemetry_insecure=True)
    matching = [w for w in caught if "unencrypted" in str(w.message)]
    assert matching, f"endpoint {endpoint!r}: {[str(w.message) for w in caught]}"


def test_opentelemetry_config_no_warning_when_insecure_false() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        OpenTelemetryConfig(
            opentelemetry_endpoint="https://collector.example.com:4317",
            opentelemetry_insecure=False,
        )


def test_opentelemetry_config_no_warning_when_endpoint_unset() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        OpenTelemetryConfig(opentelemetry_log_traces=True)


def test_opentelemetry_config_no_warning_for_unix_socket_endpoint() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        OpenTelemetryConfig(
            opentelemetry_endpoint="unix:///var/run/otel.sock",
            opentelemetry_insecure=True,
        )
