from lite_bootstrap.opentelemetry_bootstrap import OpenTelemetryBootstrap
from tests.conftest import CustomInstrumentor


def test_bootstrap_opentelemetry() -> None:
    opentelemetry = OpenTelemetryBootstrap(
        endpoint="localhost",
        service_name="test_service",
        instruments=[CustomInstrumentor()],
    )
    opentelemetry.start_tracing()
    opentelemetry.teardown()


def test_bootstrap_opentelemetry_empty_instruments() -> None:
    opentelemetry = OpenTelemetryBootstrap(
        endpoint="localhost",
        service_name="test_service",
    )
    opentelemetry.start_tracing()
    opentelemetry.teardown()
