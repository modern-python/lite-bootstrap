from lite_bootstrap.instruments.opentelemetry_instrument import InstrumentorWithParams, OpenTelemetryInstrument
from tests.conftest import CustomInstrumentor


def test_bootstrap_opentelemetry() -> None:
    opentelemetry = OpenTelemetryInstrument(
        endpoint="localhost",
        service_name="test_service",
        instrumentors=[
            InstrumentorWithParams(instrumentor=CustomInstrumentor(), additional_params={"key": "value"}),
            CustomInstrumentor(),
        ],
    )
    opentelemetry.bootstrap()
    opentelemetry.teardown()


def test_bootstrap_opentelemetry_empty_instruments() -> None:
    opentelemetry = OpenTelemetryInstrument(
        endpoint="localhost",
        service_name="test_service",
    )
    opentelemetry.bootstrap()
    opentelemetry.teardown()
