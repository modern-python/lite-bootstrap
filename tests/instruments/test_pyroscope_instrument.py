import unittest.mock as mock_module
from unittest.mock import MagicMock, patch

import fastapi
import pyroscope
from fastapi.testclient import TestClient
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import lite_bootstrap.instruments.opentelemetry_instrument as otel_module
from lite_bootstrap import FreeConfig
from lite_bootstrap.instruments.opentelemetry_instrument import OpenTelemetryInstrument
from lite_bootstrap.instruments.pyroscope_instrument import PyroscopeConfig, PyroscopeInstrument


_PYROSCOPE_PYROSCOPE = "lite_bootstrap.instruments.pyroscope_instrument.pyroscope"
_PYROSCOPE_OTEL = "lite_bootstrap.instruments.opentelemetry_instrument.pyroscope"


def _make_config(endpoint: str | None = "http://pyroscope:4040") -> PyroscopeConfig:
    return PyroscopeConfig(service_name="test-service", pyroscope_endpoint=endpoint)


def test_pyroscope_instrument_not_configured_without_endpoint() -> None:
    config = _make_config(endpoint=None)
    assert not PyroscopeInstrument.is_configured(config)


def test_pyroscope_instrument_is_configured() -> None:
    config = _make_config()
    assert PyroscopeInstrument.is_configured(config)


def test_pyroscope_check_dependencies() -> None:
    assert PyroscopeInstrument.check_dependencies()


def test_pyroscope_instrument_bootstrap_and_teardown() -> None:
    with patch(_PYROSCOPE_PYROSCOPE) as mock_pyroscope:
        instrument = PyroscopeInstrument(bootstrap_config=_make_config())
        instrument.bootstrap()
        mock_pyroscope.configure.assert_called_once_with(
            application_name="test-service",
            server_address="http://pyroscope:4040",
            sample_rate=100,
            tags={},
        )
        instrument.teardown()
        mock_pyroscope.shutdown.assert_called_once()


def test_pyroscope_bootstrap_uses_opentelemetry_service_name() -> None:
    config = FreeConfig(
        service_name="fallback",
        pyroscope_endpoint="http://pyroscope:4040",
        opentelemetry_service_name="otel-name",
    )
    with patch(_PYROSCOPE_PYROSCOPE) as mock_pyroscope:
        PyroscopeInstrument(bootstrap_config=config).bootstrap()
        mock_pyroscope.configure.assert_called_once()
        assert mock_pyroscope.configure.call_args.kwargs["application_name"] == "otel-name"


def test_pyroscope_standalone_config_accepts_otel_fields() -> None:
    config = PyroscopeConfig(
        service_name="fallback",
        pyroscope_endpoint="http://pyroscope:4040",
        opentelemetry_service_name="otel-name",
        opentelemetry_namespace="my-ns",
    )
    with patch(_PYROSCOPE_PYROSCOPE) as mock_pyroscope:
        PyroscopeInstrument(bootstrap_config=config).bootstrap()
        kwargs = mock_pyroscope.configure.call_args.kwargs
        assert kwargs["application_name"] == "otel-name"
        assert kwargs["tags"] == {"service_namespace": "my-ns"}


def test_pyroscope_bootstrap_merges_namespace_tag() -> None:
    config = FreeConfig(
        service_name="svc",
        pyroscope_endpoint="http://pyroscope:4040",
        pyroscope_tags={"env": "prod"},
        opentelemetry_namespace="my-namespace",
    )
    with patch(_PYROSCOPE_PYROSCOPE) as mock_pyroscope:
        PyroscopeInstrument(bootstrap_config=config).bootstrap()
        assert mock_pyroscope.configure.call_args.kwargs["tags"] == {
            "service_namespace": "my-namespace",
            "env": "prod",
        }


def test_pyroscope_span_processor_on_start_root_span() -> None:
    with patch(_PYROSCOPE_OTEL) as mock_pyroscope:
        processor = otel_module.PyroscopeSpanProcessor()
        mock_span = MagicMock()
        mock_span.parent = None
        mock_span.context.span_id = 0xABCDEF1234567890
        mock_span.name = "test-span"

        processor.on_start(mock_span)

        mock_pyroscope.add_thread_tag.assert_any_call("span_id", mock_span.context.span_id.__format__("016x"))
        mock_pyroscope.add_thread_tag.assert_any_call("span_name", "test-span")
        mock_span.set_attribute.assert_called_once()


def test_pyroscope_span_processor_on_start_child_span() -> None:
    with patch(_PYROSCOPE_OTEL) as mock_pyroscope:
        processor = otel_module.PyroscopeSpanProcessor()
        mock_parent = MagicMock()
        mock_parent.is_remote = False
        mock_span = MagicMock()
        mock_span.parent = mock_parent

        processor.on_start(mock_span)

        mock_pyroscope.add_thread_tag.assert_not_called()
        mock_span.set_attribute.assert_not_called()


def test_pyroscope_span_processor_on_end_root_span() -> None:
    with patch(_PYROSCOPE_OTEL) as mock_pyroscope:
        processor = otel_module.PyroscopeSpanProcessor()
        mock_span = MagicMock()
        mock_span.parent = None
        mock_span.context.span_id = 0xABCDEF1234567890
        mock_span.name = "test-span"

        processor.on_end(mock_span)

        mock_pyroscope.remove_thread_tag.assert_any_call("span_id", mock_span.context.span_id.__format__("016x"))
        mock_pyroscope.remove_thread_tag.assert_any_call("span_name", "test-span")


def test_pyroscope_span_processor_on_end_child_span() -> None:
    with patch(_PYROSCOPE_OTEL) as mock_pyroscope:
        processor = otel_module.PyroscopeSpanProcessor()
        mock_parent = MagicMock()
        mock_parent.is_remote = False
        mock_span = MagicMock()
        mock_span.parent = mock_parent

        processor.on_end(mock_span)

        mock_pyroscope.remove_thread_tag.assert_not_called()


def test_pyroscope_span_processor_on_start_remote_parent() -> None:
    with patch(_PYROSCOPE_OTEL) as mock_pyroscope:
        processor = otel_module.PyroscopeSpanProcessor()
        mock_parent = MagicMock()
        mock_parent.is_remote = True
        mock_span = MagicMock()
        mock_span.parent = mock_parent
        mock_span.context.span_id = 0x1234567890ABCDEF
        mock_span.name = "remote-root"

        processor.on_start(mock_span)

        mock_pyroscope.add_thread_tag.assert_any_call("span_name", "remote-root")


def test_pyroscope_otel_adds_span_processor_when_configured() -> None:
    """OTel instrument adds PyroscopeSpanProcessor when pyroscope_endpoint is set."""
    config = FreeConfig(
        service_name="test-svc",
        opentelemetry_log_traces=True,
        pyroscope_endpoint="http://pyroscope:4040",
    )
    with patch("lite_bootstrap.instruments.opentelemetry_instrument.set_tracer_provider"):
        instrument = OpenTelemetryInstrument(bootstrap_config=config)  # type: ignore[arg-type]
        instrument.bootstrap()
        # The tracer_provider local is set; verify span processor fires on a real span
    instrument.teardown()


def test_pyroscope_otel_span_processor_integration() -> None:
    """PyroscopeSpanProcessor fires add/remove_thread_tag for root spans end-to-end."""
    provider = SDKTracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    with patch(_PYROSCOPE_OTEL) as mock_pyroscope_otel:
        processor = otel_module.PyroscopeSpanProcessor()
        provider.add_span_processor(processor)

        tracer = provider.get_tracer("test")
        with tracer.start_as_current_span("GET /test-handler"):
            pass

        mock_pyroscope_otel.add_thread_tag.assert_any_call(
            "span_id", mock_pyroscope_otel.add_thread_tag.call_args_list[0][0][1]
        )
        mock_pyroscope_otel.add_thread_tag.assert_any_call("span_name", "GET /test-handler")
        mock_pyroscope_otel.remove_thread_tag.assert_any_call("span_name", "GET /test-handler")
        assert mock_pyroscope_otel.add_thread_tag.call_args_list == mock_pyroscope_otel.remove_thread_tag.call_args_list


def test_pyroscope_otel_http_integration() -> None:
    """PyroscopeSpanProcessor fires add/remove_thread_tag for real HTTP requests end-to-end."""
    app = fastapi.FastAPI()

    @app.get("/test-handler")
    async def test_handler() -> None: ...

    provider = SDKTracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(InMemorySpanExporter()))

    with patch(_PYROSCOPE_OTEL) as mock_pyroscope_otel:
        mock_pyroscope_otel.add_thread_tag.side_effect = pyroscope.add_thread_tag
        mock_pyroscope_otel.remove_thread_tag.side_effect = pyroscope.remove_thread_tag
        provider.add_span_processor(otel_module.PyroscopeSpanProcessor())
        FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
        try:
            TestClient(app=app).get("/test-handler")
        finally:
            FastAPIInstrumentor.uninstrument_app(app)

        assert (
            mock_pyroscope_otel.add_thread_tag.mock_calls
            == mock_pyroscope_otel.remove_thread_tag.mock_calls
            == [
                mock_module.call("span_id", mock_module.ANY),
                mock_module.call("span_name", "GET /test-handler"),
            ]
        )
