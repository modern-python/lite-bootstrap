import logging
import sys
import typing
import warnings
from unittest.mock import patch

import pytest
from opentelemetry.instrumentation.instrumentor import BaseInstrumentor

from lite_bootstrap import import_checker
from lite_bootstrap.exceptions import InstrumentDependencyMissingWarning, TeardownError
from lite_bootstrap.instruments.opentelemetry_instrument import (
    InstrumentorWithParams,
    OpenTelemetryConfig,
    OpenTelemetryInstrument,
)
from tests.conftest import CustomInstrumentor, emulate_package_missing_with_module_reload


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


def test_opentelemetry_teardown_aggregates_instrumentor_and_shutdown_errors() -> None:
    class BoomInstrumentor(BaseInstrumentor):
        def instrumentation_dependencies(self) -> typing.Collection[str]:
            return []

        def _instrument(self, **_kwargs: object) -> None: ...

        def _uninstrument(self, **_kwargs: object) -> None:
            msg = "instrumentor boom"
            raise RuntimeError(msg)

    instrument = OpenTelemetryInstrument(
        bootstrap_config=OpenTelemetryConfig(
            opentelemetry_instrumentors=[BoomInstrumentor()],
            opentelemetry_log_traces=True,
        ),
    )
    instrument.bootstrap()
    tracer_provider = instrument._tracer_provider  # noqa: SLF001
    assert tracer_provider is not None

    with (
        patch.object(tracer_provider, "shutdown", side_effect=RuntimeError("shutdown boom")),
        pytest.raises(TeardownError) as excinfo,
    ):
        instrument.teardown()

    error_msgs = [str(err) for _, err in excinfo.value.errors]
    assert any("instrumentor boom" in m for m in error_msgs), error_msgs
    assert any("shutdown boom" in m for m in error_msgs), error_msgs
    assert instrument._tracer_provider is None  # noqa: SLF001
    assert instrument._prior_logger_disabled == {}  # noqa: SLF001


# The grpc otlp exporter's dotted submodules are already cached in sys.modules from
# earlier imports of this very module (both in normal test collection and by the
# reload below), so a plain "opentelemetry.exporter" -> None emulation would take the
# "already in sys.modules" fast path and never exercise the parent-import bug; evict
# the cached leaf/intermediate entries first to force a real resolution.
_GRPC_EXPORTER_SUBMODULES = (
    "opentelemetry.exporter.otlp.proto.grpc.trace_exporter",
    "opentelemetry.exporter.otlp.proto.grpc",
    "opentelemetry.exporter.otlp.proto",
    "opentelemetry.exporter.otlp",
)


def test_opentelemetry_instrument_survives_missing_grpc_exporter() -> None:
    # opentelemetry-api (+sdk) present but the grpc otlp exporter package absent must
    # not crash importing opentelemetry_instrument (e.g. lite-bootstrap[fastmcp],
    # which pulls bare opentelemetry-api transitively without any exporter package).
    saved_submodules = {name: sys.modules.pop(name) for name in _GRPC_EXPORTER_SUBMODULES if name in sys.modules}
    try:
        with emulate_package_missing_with_module_reload(
            "opentelemetry.exporter",
            ["lite_bootstrap.instruments.opentelemetry_instrument"],
        ):
            assert import_checker.is_otlp_grpc_exporter_installed is False
    finally:
        sys.modules.update(saved_submodules)


def test_opentelemetry_instrument_survives_missing_sdk() -> None:
    # opentelemetry-api present but opentelemetry-sdk absent (e.g. lite-bootstrap[fastmcp],
    # which pulls bare opentelemetry-api transitively) must not crash importing
    # opentelemetry_instrument, whose guarded block imports opentelemetry.sdk.* symbols.
    with emulate_package_missing_with_module_reload(
        "opentelemetry.sdk",
        ["lite_bootstrap.instruments.opentelemetry_instrument"],
    ):
        assert import_checker.is_opentelemetry_sdk_installed is False
        assert OpenTelemetryInstrument.check_dependencies() is False


def test_bootstrap_warns_when_endpoint_set_without_grpc_exporter() -> None:
    # SDK present but the grpc exporter absent, with an endpoint configured: bootstrap()
    # must warn (configured-but-missing) rather than silently skip OTLP export.
    instrument = OpenTelemetryInstrument(bootstrap_config=OpenTelemetryConfig(opentelemetry_endpoint="localhost:4317"))
    try:
        with (
            patch.object(import_checker, "is_otlp_grpc_exporter_installed", False),
            pytest.warns(InstrumentDependencyMissingWarning, match="gRPC OTLP exporter"),
        ):
            instrument.bootstrap()
    finally:
        instrument.teardown()
