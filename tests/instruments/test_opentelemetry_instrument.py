from opentelemetry.sdk.trace.export import ConsoleSpanExporter

from lite_bootstrap.instruments.opentelemetry_instrument import InstrumentorWithParams, OpenTelemetryInstrument
from lite_bootstrap.service_config import ServiceConfig
from tests.conftest import CustomInstrumentor


def test_opentelemetry_instrument(service_config: ServiceConfig) -> None:
    opentelemetry = OpenTelemetryInstrument(
        endpoint="otl",
        instrumentors=[
            InstrumentorWithParams(instrumentor=CustomInstrumentor(), additional_params={"key": "value"}),
            CustomInstrumentor(),
        ],
        span_exporter=ConsoleSpanExporter(),
    )
    try:
        opentelemetry.bootstrap(service_config)
    finally:
        opentelemetry.teardown()


def test_opentelemetry_instrument_empty_instruments(service_config: ServiceConfig) -> None:
    opentelemetry = OpenTelemetryInstrument(
        endpoint="otl",
        span_exporter=ConsoleSpanExporter(),
    )
    try:
        opentelemetry.bootstrap(service_config)
    finally:
        opentelemetry.teardown()
