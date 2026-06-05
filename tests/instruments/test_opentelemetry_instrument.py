import logging
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
