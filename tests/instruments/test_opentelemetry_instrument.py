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
