import logging
import os
import re
import sys
import typing
import warnings
from unittest.mock import patch

import pytest
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter as OTLPGrpcMetricExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter as OTLPHttpMetricExporter
from opentelemetry.instrumentation.instrumentor import BaseInstrumentor
from opentelemetry.metrics import get_meter_provider, set_meter_provider
from opentelemetry.sdk.metrics import MeterProvider as SDKMeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider
from opentelemetry.sdk.trace import sampling
from opentelemetry.trace import set_tracer_provider

import lite_bootstrap.instruments.opentelemetry_instrument as otel_module
from lite_bootstrap import import_checker
from lite_bootstrap.exceptions import InstrumentDependencyMissingWarning, TeardownError
from lite_bootstrap.instruments.opentelemetry_instrument import (
    InstrumentorWithParams,
    OpenTelemetryConfig,
    OpenTelemetryInstrument,
)
from tests.conftest import CustomInstrumentor, emulate_package_missing_with_module_reload, warning_source_files


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


_SAMPLER_ENV_VARS: typing.Final = ("OTEL_TRACES_SAMPLER", "OTEL_TRACES_SAMPLER_ARG")


@pytest.fixture
def without_sampler_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for env_var in _SAMPLER_ENV_VARS:
        monkeypatch.delenv(env_var, raising=False)


@pytest.mark.usefixtures("without_sampler_env")
def test_opentelemetry_sampler_reaches_tracer_provider() -> None:
    sample_rate = 0.01
    sampler = sampling.ParentBased(sampling.TraceIdRatioBased(sample_rate))
    instrument = OpenTelemetryInstrument(
        bootstrap_config=OpenTelemetryConfig(opentelemetry_log_traces=True, opentelemetry_sampler=sampler),
    )
    try:
        instrument.bootstrap()
        assert instrument._tracer_provider is not None  # noqa: SLF001
        assert instrument._tracer_provider.sampler is sampler  # noqa: SLF001
    finally:
        instrument.teardown()


@pytest.mark.usefixtures("without_sampler_env")
def test_opentelemetry_sampler_unset_keeps_sdk_default() -> None:
    instrument = OpenTelemetryInstrument(bootstrap_config=OpenTelemetryConfig(opentelemetry_log_traces=True))
    try:
        instrument.bootstrap()
        assert instrument._tracer_provider is not None  # noqa: SLF001
        assert instrument._tracer_provider.sampler is sampling.DEFAULT_ON  # noqa: SLF001
    finally:
        instrument.teardown()


def test_opentelemetry_sampler_unset_honours_sampler_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTEL_TRACES_SAMPLER", "traceidratio")
    monkeypatch.setenv("OTEL_TRACES_SAMPLER_ARG", "0.25")
    instrument = OpenTelemetryInstrument(bootstrap_config=OpenTelemetryConfig(opentelemetry_log_traces=True))
    try:
        instrument.bootstrap()
        assert instrument._tracer_provider is not None  # noqa: SLF001
        sampler = instrument._tracer_provider.sampler  # noqa: SLF001
        assert isinstance(sampler, sampling.TraceIdRatioBased)
        env_rate = 0.25
        assert sampler.rate == env_rate
    finally:
        instrument.teardown()


def test_opentelemetry_sampler_wins_over_sampler_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTEL_TRACES_SAMPLER", "traceidratio")
    monkeypatch.setenv("OTEL_TRACES_SAMPLER_ARG", "0.25")
    instrument = OpenTelemetryInstrument(
        bootstrap_config=OpenTelemetryConfig(
            opentelemetry_log_traces=True,
            opentelemetry_sampler=sampling.ALWAYS_OFF,
        ),
    )
    try:
        instrument.bootstrap()
        assert instrument._tracer_provider is not None  # noqa: SLF001
        assert instrument._tracer_provider.sampler is sampling.ALWAYS_OFF  # noqa: SLF001
    finally:
        instrument.teardown()


@pytest.mark.parametrize(
    ("config", "expected_service_name"),
    [
        (OpenTelemetryConfig(opentelemetry_log_traces=True), "micro-service"),
        (OpenTelemetryConfig(opentelemetry_log_traces=True, service_name="configured"), "configured"),
        (
            OpenTelemetryConfig(
                opentelemetry_log_traces=True, service_name="configured", opentelemetry_service_name="otel-configured"
            ),
            "otel-configured",
        ),
    ],
)
def test_opentelemetry_configured_service_name_wins_over_env(
    monkeypatch: pytest.MonkeyPatch, config: OpenTelemetryConfig, expected_service_name: str
) -> None:
    monkeypatch.setenv("OTEL_SERVICE_NAME", "from-env")
    instrument = OpenTelemetryInstrument(bootstrap_config=config)
    try:
        instrument.bootstrap()
        assert instrument._tracer_provider is not None  # noqa: SLF001
        assert instrument._tracer_provider.resource.attributes["service.name"] == expected_service_name  # noqa: SLF001
    finally:
        instrument.teardown()


def test_opentelemetry_resource_detectors_enrich_resource(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTEL_EXPERIMENTAL_RESOURCE_DETECTORS", "process")
    monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "deployment.environment=from-env")
    instrument = OpenTelemetryInstrument(bootstrap_config=OpenTelemetryConfig(opentelemetry_log_traces=True))
    try:
        instrument.bootstrap()
        assert instrument._tracer_provider is not None  # noqa: SLF001
        attributes = instrument._tracer_provider.resource.attributes  # noqa: SLF001
        assert attributes["process.pid"] == os.getpid()
        assert attributes["deployment.environment"] == "from-env"
    finally:
        instrument.teardown()


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
        assert OpenTelemetryInstrument.dependencies_installed() is False


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


def test_bootstrap_http_protocol_uses_http_exporter() -> None:
    instrument = OpenTelemetryInstrument(
        bootstrap_config=OpenTelemetryConfig(
            opentelemetry_endpoint="http://collector:4318/v1/traces",
            opentelemetry_exporter_protocol="http",
        )
    )
    try:
        with patch.object(otel_module, "OTLPHttpSpanExporter") as mock_http:
            instrument.bootstrap()
        mock_http.assert_called_once_with(endpoint="http://collector:4318/v1/traces")
    finally:
        instrument.teardown()


def test_bootstrap_grpc_protocol_uses_grpc_exporter() -> None:
    instrument = OpenTelemetryInstrument(bootstrap_config=OpenTelemetryConfig(opentelemetry_endpoint="localhost:4317"))
    try:
        with patch.object(otel_module, "OTLPGrpcSpanExporter") as mock_grpc:
            instrument.bootstrap()
        mock_grpc.assert_called_once_with(endpoint="localhost:4317", insecure=True)
    finally:
        instrument.teardown()


def test_bootstrap_warns_when_endpoint_set_without_http_exporter() -> None:
    instrument = OpenTelemetryInstrument(
        bootstrap_config=OpenTelemetryConfig(
            opentelemetry_endpoint="http://collector:4318/v1/traces",
            opentelemetry_exporter_protocol="http",
        )
    )
    try:
        with (
            patch.object(import_checker, "is_otlp_http_exporter_installed", False),
            pytest.warns(InstrumentDependencyMissingWarning, match="HTTP OTLP exporter"),
        ):
            instrument.bootstrap()
    finally:
        instrument.teardown()


def test_http_protocol_does_not_emit_insecure_warning() -> None:
    # The insecure warning is gRPC-only; an http:// non-local endpoint must not warn.
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        OpenTelemetryConfig(
            opentelemetry_endpoint="http://remote-collector:4318/v1/traces",
            opentelemetry_exporter_protocol="http",
        )


@pytest.mark.parametrize(
    ("protocol", "endpoint", "flag_name"),
    [
        ("grpc", "localhost:4317", "is_otlp_grpc_exporter_installed"),
        ("http", "http://collector:4318/v1/traces", "is_otlp_http_exporter_installed"),
    ],
)
def test_missing_exporter_warning_points_at_the_caller_of_bootstrap(
    protocol: typing.Literal["grpc", "http"], endpoint: str, flag_name: str
) -> None:
    """INVARIANT: the missing-exporter warning is attributed to the frame that called bootstrap().

    Replacing warn_at_caller with a literal stacklevel breaks it: the literal counts frames that
    only exist by convention, so any helper extracted out of bootstrap() moves the warning one
    frame deeper, onto lite_bootstrap's own source, and nothing but this test notices. Both
    transports are pinned because each warns from its own branch and a refactor can reshape one
    without the other. This covers the instrument called on its own; the bootstrapper path, where
    the frame to skip past is lite_bootstrap's own, is pinned in tests/test_fastapi_bootstrap.py.
    """
    instrument = OpenTelemetryInstrument(
        bootstrap_config=OpenTelemetryConfig(opentelemetry_endpoint=endpoint, opentelemetry_exporter_protocol=protocol)
    )
    try:
        with (
            patch.object(import_checker, flag_name, False),
            warnings.catch_warnings(record=True) as caught,
        ):
            warnings.simplefilter("always")
            instrument.bootstrap()
    finally:
        instrument.teardown()

    assert warning_source_files(caught, InstrumentDependencyMissingWarning) == [__file__]


def test_bootstrap_warns_when_a_tracer_provider_is_already_installed() -> None:
    """REGRESSION #227: losing the set-once race leaves a provider nothing will ever feed.

    `set_tracer_provider` is refused when the application installed its own provider first, so the
    exporter, sampler and resource configured here are never used, and the BatchSpanProcessor
    worker thread the instrument started runs idle until teardown. The SDK's own complaint about
    the refusal goes to a logger `_silence_otel_loggers` has just disabled, so without this warning
    nothing reports it.
    """
    application_provider = SDKTracerProvider()
    set_tracer_provider(application_provider)
    instrument = OpenTelemetryInstrument(bootstrap_config=OpenTelemetryConfig(opentelemetry_log_traces=True))

    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            instrument.bootstrap()
    finally:
        instrument.teardown()

    assert [str(one_warning.message) for one_warning in caught] == [
        "a TracerProvider is already installed; the configured exporter, sampler and resource will not be used"
    ]
    # The frame to blame is the caller's, not lite_bootstrap's own bootstrap().
    assert warning_source_files(caught, UserWarning) == [__file__]


def test_bootstrap_is_silent_when_it_installs_the_tracer_provider() -> None:
    """The warning marks a lost race, so winning one must stay quiet."""
    instrument = OpenTelemetryInstrument(bootstrap_config=OpenTelemetryConfig(opentelemetry_log_traces=True))

    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            instrument.bootstrap()
    finally:
        instrument.teardown()

    assert warning_source_files(caught, UserWarning) == []


def test_metrics_endpoint_alone_configures_the_instrument() -> None:
    """The metrics signal is the same concern, so asking only for it is asking for the instrument."""
    assert OpenTelemetryInstrument.is_configured(OpenTelemetryConfig(opentelemetry_metrics_endpoint="localhost:4317"))
    assert not OpenTelemetryInstrument.is_configured(OpenTelemetryConfig())


def test_metrics_endpoint_installs_a_meter_provider_carrying_the_resource() -> None:
    """The metrics pipeline is opt-in through its own endpoint and shares the trace resource."""
    instrument = OpenTelemetryInstrument(
        bootstrap_config=OpenTelemetryConfig(
            service_name="metrics-svc", opentelemetry_metrics_endpoint="localhost:4317"
        )
    )
    try:
        instrument.bootstrap()

        meter_provider = get_meter_provider()
        assert isinstance(meter_provider, SDKMeterProvider)
        assert meter_provider is instrument._meter_provider  # noqa: SLF001
        assert meter_provider._sdk_config.resource.attributes["service.name"] == "metrics-svc"  # noqa: SLF001
        (reader,) = meter_provider._metric_readers  # noqa: SLF001
        assert isinstance(reader, PeriodicExportingMetricReader)
        assert isinstance(reader._exporter, OTLPGrpcMetricExporter)  # noqa: SLF001
    finally:
        instrument.teardown()


def test_metrics_endpoint_uses_the_http_exporter_for_the_http_protocol() -> None:
    instrument = OpenTelemetryInstrument(
        bootstrap_config=OpenTelemetryConfig(
            opentelemetry_metrics_endpoint="http://collector:4318/v1/metrics",
            opentelemetry_exporter_protocol="http",
        )
    )
    try:
        instrument.bootstrap()

        meter_provider = instrument._meter_provider  # noqa: SLF001
        assert meter_provider is not None
        (reader,) = meter_provider._metric_readers  # noqa: SLF001
        assert isinstance(reader, PeriodicExportingMetricReader)
        assert isinstance(reader._exporter, OTLPHttpMetricExporter)  # noqa: SLF001
    finally:
        instrument.teardown()


def test_no_metrics_endpoint_installs_no_meter_provider() -> None:
    """Opt-in means a tracing-only config must leave the meter provider global untouched."""
    instrument = OpenTelemetryInstrument(bootstrap_config=OpenTelemetryConfig(opentelemetry_log_traces=True))
    try:
        instrument.bootstrap()

        assert instrument._meter_provider is None  # noqa: SLF001
        assert not isinstance(get_meter_provider(), SDKMeterProvider)
    finally:
        instrument.teardown()


def test_teardown_shuts_down_the_meter_provider() -> None:
    instrument = OpenTelemetryInstrument(
        bootstrap_config=OpenTelemetryConfig(opentelemetry_metrics_endpoint="localhost:4317")
    )
    instrument.bootstrap()
    meter_provider = instrument._meter_provider  # noqa: SLF001
    assert meter_provider is not None

    with patch.object(meter_provider, "shutdown") as mock_shutdown:
        instrument.teardown()

    mock_shutdown.assert_called_once_with()
    assert instrument._meter_provider is None  # noqa: SLF001


@pytest.mark.parametrize(
    ("protocol", "endpoint", "flag_name", "expected_extra"),
    [
        ("grpc", "localhost:4317", "is_otlp_grpc_exporter_installed", "lite-bootstrap[otl]"),
        ("http", "http://collector:4318/v1/metrics", "is_otlp_http_exporter_installed", "lite-bootstrap[otl-http]"),
    ],
)
def test_bootstrap_warns_when_metrics_endpoint_set_without_its_exporter(
    protocol: typing.Literal["grpc", "http"], endpoint: str, flag_name: str, expected_extra: str
) -> None:
    """Configured-but-missing is a deployment surprise, so it warns rather than silently skipping."""
    instrument = OpenTelemetryInstrument(
        bootstrap_config=OpenTelemetryConfig(
            opentelemetry_metrics_endpoint=endpoint, opentelemetry_exporter_protocol=protocol
        )
    )
    try:
        with (
            patch.object(import_checker, flag_name, False),
            pytest.warns(InstrumentDependencyMissingWarning, match=re.escape(expected_extra)),
        ):
            instrument.bootstrap()

        assert instrument._meter_provider is None  # noqa: SLF001
    finally:
        instrument.teardown()


def test_bootstrap_warns_when_a_meter_provider_is_already_installed() -> None:
    """`set_meter_provider` is set-once too, so the metrics pipeline can be orphaned exactly as #227's was."""
    set_meter_provider(SDKMeterProvider())
    instrument = OpenTelemetryInstrument(
        bootstrap_config=OpenTelemetryConfig(opentelemetry_metrics_endpoint="localhost:4317")
    )

    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            instrument.bootstrap()
    finally:
        instrument.teardown()

    assert [str(one_warning.message) for one_warning in caught] == [
        "a MeterProvider is already installed; the configured metrics exporter and resource will not be used"
    ]
    assert warning_source_files(caught, UserWarning) == [__file__]
