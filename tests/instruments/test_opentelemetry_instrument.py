from unittest.mock import patch

from lite_bootstrap.instruments.opentelemetry_instrument import (
    InstrumentorWithParams,
    OpentelemetryConfig,
    OpenTelemetryInstrument,
)
from tests.conftest import CustomInstrumentor


def test_opentelemetry_instrument() -> None:
    opentelemetry_instrument = OpenTelemetryInstrument(
        bootstrap_config=OpentelemetryConfig(
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
        bootstrap_config=OpentelemetryConfig(
            opentelemetry_log_traces=True,
        )
    )
    try:
        opentelemetry_instrument.bootstrap()
    finally:
        opentelemetry_instrument.teardown()


def test_opentelemetry_instrument_teardown_shuts_down_tracer_provider() -> None:
    instrument = OpenTelemetryInstrument(
        bootstrap_config=OpentelemetryConfig(opentelemetry_log_traces=True),
    )
    instrument.bootstrap()
    tracer_provider = instrument._tracer_provider  # noqa: SLF001
    assert tracer_provider is not None

    with patch.object(tracer_provider, "shutdown") as mock_shutdown:
        instrument.teardown()

    mock_shutdown.assert_called_once_with()
    assert instrument._tracer_provider is None  # noqa: SLF001
