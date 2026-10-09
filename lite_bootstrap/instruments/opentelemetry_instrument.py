import dataclasses
import logging
import os
import re
import typing
import urllib.parse

from lite_bootstrap import import_checker
from lite_bootstrap.exceptions import InstrumentDependencyMissingWarning, collect_teardown_errors
from lite_bootstrap.helpers.warn import warn_at_caller
from lite_bootstrap.instruments.base import BaseConfig, BaseInstrument


if typing.TYPE_CHECKING:
    from opentelemetry.instrumentation.instrumentor import BaseInstrumentor
    from opentelemetry.sdk.trace.sampling import Sampler

if import_checker.is_opentelemetry_sdk_installed:
    from opentelemetry.context import Context
    from opentelemetry.metrics import get_meter_provider, set_meter_provider
    from opentelemetry.sdk import resources
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import MetricExporter, PeriodicExportingMetricReader
    from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor, TracerProvider
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor,
        ConsoleSpanExporter,
        SimpleSpanProcessor,
        SpanExporter,
    )
    from opentelemetry.trace import Span, format_span_id, get_tracer_provider, set_tracer_provider

if import_checker.is_otlp_grpc_exporter_installed:
    # opentelemetry-api can be present without the grpc otlp exporter package (e.g.
    # lite-bootstrap[fastmcp] pulls bare opentelemetry-api transitively); this must
    # stay a separate guard from is_opentelemetry_installed above.
    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter as OTLPGrpcMetricExporter
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter as OTLPGrpcSpanExporter

if import_checker.is_otlp_http_exporter_installed:
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter as OTLPHttpMetricExporter
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter as OTLPHttpSpanExporter

if import_checker.is_pyroscope_installed:
    import pyroscope


def _format_span(readable_span: "ReadableSpan") -> str:
    return typing.cast("str", readable_span.to_json(indent=None)) + "\n"


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class InstrumentorWithParams:
    instrumentor: "BaseInstrumentor"
    additional_params: dict[str, typing.Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass(kw_only=True, frozen=True)
class OpenTelemetryServiceFieldsConfig(BaseConfig):
    opentelemetry_service_name: str | None = None
    opentelemetry_namespace: str | None = None


# OpenTelemetry's ExcludeList searches its patterns in a full URL, not a bare path.
_EXCLUDED_URL_SCHEME_AND_HOST: typing.Final = r"^\w+://[^/]*"

_LOCAL_HOSTS: typing.Final[frozenset[str]] = frozenset({"localhost", "127.0.0.1", "::1", ""})


@dataclasses.dataclass(kw_only=True, frozen=True)
class OpenTelemetryConfig(OpenTelemetryServiceFieldsConfig):
    opentelemetry_container_name: str | None = dataclasses.field(
        default_factory=lambda: os.environ.get("HOSTNAME") or None
    )
    opentelemetry_endpoint: str | None = None
    opentelemetry_metrics_endpoint: str | None = None
    opentelemetry_insecure: bool = True
    opentelemetry_exporter_protocol: typing.Literal["grpc", "http"] = "grpc"
    opentelemetry_instrumentors: list[typing.Union[InstrumentorWithParams, "BaseInstrumentor"]] = dataclasses.field(
        default_factory=list
    )
    opentelemetry_log_traces: bool = False
    # Left None, the SDK picks its own default, which reads OTEL_TRACES_SAMPLER; see ADR-0008
    # (docs/adr/0008-otel-sampling-is-a-sampler-object.md).
    opentelemetry_sampler: "Sampler | None" = None
    opentelemetry_generate_health_check_spans: bool = True
    opentelemetry_excluded_urls: list[str] = dataclasses.field(default_factory=list)

    def __post_init__(self) -> None:
        for host in self._parse_remote_insecure_hosts():
            warn_at_caller(
                f"OTLP exporter sending telemetry unencrypted to non-local host {host!r}; "
                "set opentelemetry_insecure=False or use a localhost/unix endpoint."
            )
        super().__post_init__()

    def _parse_remote_insecure_hosts(self) -> list[str]:
        """Return each distinct host an insecure, non-local endpoint points at, in declaration order."""
        endpoints = (self.opentelemetry_endpoint, self.opentelemetry_metrics_endpoint)
        hosts = (self._parse_remote_insecure_host(endpoint) for endpoint in endpoints)
        return list(dict.fromkeys(host for host in hosts if host is not None))

    def _parse_remote_insecure_host(self, endpoint: str | None) -> str | None:
        """Return the host name if the endpoint is insecure AND non-local; else None."""
        if self.opentelemetry_exporter_protocol != "grpc":
            return None
        if not endpoint or not self.opentelemetry_insecure:
            return None
        if endpoint.startswith("unix://"):
            return None
        # urlparse treats schemeless input as `path`, misparsing `host:port` forms.
        # Prepend `//` so urlparse always sees a network-location-style input.
        raw = endpoint
        if "://" not in raw:
            raw = f"//{raw}"
        parsed = urllib.parse.urlparse(raw)
        host = (parsed.hostname or "").lower()
        if host in _LOCAL_HOSTS:
            return None
        return host


if import_checker.is_opentelemetry_sdk_installed and import_checker.is_pyroscope_installed:
    _OTEL_PROFILE_ID_KEY: typing.Final = "pyroscope.profile.id"
    _PYROSCOPE_SPAN_ID_KEY: typing.Final = "span_id"
    _PYROSCOPE_SPAN_NAME_KEY: typing.Final = "span_name"

    def _is_root_span(span: "ReadableSpan") -> bool:
        return span.parent is None or span.parent.is_remote

    class PyroscopeSpanProcessor(SpanProcessor):
        def on_start(self, span: "Span", parent_context: "Context | None" = None) -> None:  # noqa: ARG002
            if _is_root_span(span):  # ty: ignore[invalid-argument-type]
                formatted_span_id = format_span_id(span.context.span_id)  # ty: ignore[unresolved-attribute]
                span.set_attribute(_OTEL_PROFILE_ID_KEY, formatted_span_id)
                pyroscope.add_thread_tag(_PYROSCOPE_SPAN_ID_KEY, formatted_span_id)
                pyroscope.add_thread_tag(_PYROSCOPE_SPAN_NAME_KEY, span.name)  # ty: ignore[unresolved-attribute]

        def on_end(self, span: "ReadableSpan") -> None:
            if _is_root_span(span):
                pyroscope.remove_thread_tag(_PYROSCOPE_SPAN_ID_KEY, format_span_id(span.context.span_id))
                pyroscope.remove_thread_tag(_PYROSCOPE_SPAN_NAME_KEY, span.name)

        def force_flush(self, timeout_millis: int = 30000) -> bool:  # noqa: ARG002
            return True  # pragma: no cover - matters only at the sdk 1.28 floor, whose base returns None


@dataclasses.dataclass(kw_only=True, slots=True)
class OpenTelemetryInstrument(BaseInstrument[OpenTelemetryConfig]):
    """OpenTelemetry tracing instrument.

    Lifecycle note: ``bootstrap()`` calls ``opentelemetry.trace.set_tracer_provider``,
    which the OTel SDK enforces as **set-once per process** (subsequent calls log
    "Overriding of current TracerProvider is not allowed" and have no effect).
    ``teardown()`` calls ``shutdown()`` on the provider, which flushes batched
    spans and closes exporters, but it cannot reset the process-global pointer —
    callers of ``opentelemetry.trace.get_tracer_provider()`` after teardown will
    still receive the shut-down provider. The supported lifecycle is one
    ``OpenTelemetryInstrument`` per process; do not bootstrap a second instance.
    """

    not_configured_reason = (
        "opentelemetry_endpoint and opentelemetry_metrics_endpoint are empty and opentelemetry_log_traces is False"
    )
    missing_dependency_message = "opentelemetry-sdk is not installed"
    _tracer_provider: "TracerProvider | None" = dataclasses.field(
        default_factory=lambda: None, init=False, repr=False, compare=False
    )
    _meter_provider: "MeterProvider | None" = dataclasses.field(
        default_factory=lambda: None, init=False, repr=False, compare=False
    )
    _prior_logger_disabled: dict[str, bool] = dataclasses.field(
        default_factory=dict, init=False, repr=False, compare=False
    )

    @classmethod
    def is_configured(cls, bootstrap_config: "OpenTelemetryConfig") -> bool:
        return bool(
            bootstrap_config.opentelemetry_endpoint
            or bootstrap_config.opentelemetry_metrics_endpoint
            or bootstrap_config.opentelemetry_log_traces
        )

    @staticmethod
    def dependencies_installed() -> bool:
        # The instrument imports from both the api (opentelemetry.trace/.context) and
        # the sdk (opentelemetry.sdk.*), so it needs both distributions present.
        return import_checker.is_opentelemetry_installed and import_checker.is_opentelemetry_sdk_installed

    def _build_infrastructure_excluded_paths(self) -> set[str]:
        """Paths this policy derives itself, without the caller-supplied entries."""
        config = self.bootstrap_config
        excluded_paths: set[str] = set()
        prometheus_path = getattr(config, "prometheus_metrics_path", None)
        if prometheus_path:
            excluded_paths.add(prometheus_path)
        if not config.opentelemetry_generate_health_check_spans:
            health_path = getattr(config, "health_checks_path", None)
            if health_path:
                excluded_paths.add(health_path)
        return excluded_paths

    def _build_excluded_urls(self) -> set[str]:
        return set(self.bootstrap_config.opentelemetry_excluded_urls) | self._build_infrastructure_excluded_paths()

    def _build_excluded_url_patterns(self, environment_key: str) -> list[str]:
        """Patterns for OpenTelemetry's ``ExcludeList``, which searches them unanchored in the full URL.

        Derived paths are anchored to the start of the path and to a segment end, with the trailing slash
        optional, so ``/metrics/`` excludes ``/metrics`` but neither ``/api/metrics/`` nor ``/metricsx``.
        Caller-supplied entries and ``OTEL_PYTHON_<environment_key>_EXCLUDED_URLS``, falling back to
        ``OTEL_PYTHON_EXCLUDED_URLS`` as OpenTelemetry does, stay verbatim because they are regexes.
        """
        anchored_patterns: typing.Final = {
            rf"{_EXCLUDED_URL_SCHEME_AND_HOST}{re.escape(normalized_path)}(?:/|$)"
            for excluded_path in self._build_infrastructure_excluded_paths()
            # A bare "/" would anchor to every URL, so it is dropped along with empty values.
            if (normalized_path := excluded_path.rstrip("/"))
        }
        environment_urls: typing.Final = os.environ.get(
            f"OTEL_PYTHON_{environment_key}_EXCLUDED_URLS", os.environ.get("OTEL_PYTHON_EXCLUDED_URLS", "")
        )
        environment_patterns: typing.Final = {url.strip() for url in environment_urls.split(",") if url.strip()}
        return sorted(anchored_patterns | set(self.bootstrap_config.opentelemetry_excluded_urls) | environment_patterns)

    def _silence_otel_loggers(self) -> None:
        for logger_name in ("opentelemetry.instrumentation.instrumentor", "opentelemetry.trace"):
            otel_logger = logging.getLogger(logger_name)
            self._prior_logger_disabled[logger_name] = otel_logger.disabled
            otel_logger.disabled = True

    def _build_resource(self) -> "resources.Resource":
        config = self.bootstrap_config
        attributes = {
            resources.SERVICE_NAME: config.opentelemetry_service_name or config.service_name,
            resources.TELEMETRY_SDK_LANGUAGE: "python",
            resources.SERVICE_NAMESPACE: config.opentelemetry_namespace,
            resources.SERVICE_VERSION: config.service_version,
            resources.CONTAINER_NAME: config.opentelemetry_container_name,
        }
        return resources.Resource.create(attributes={k: v for k, v in attributes.items() if v})

    def _build_span_exporter(self) -> "SpanExporter | None":
        """Return the OTLP exporter for the configured protocol, or None after warning it is missing.

        Only call this once opentelemetry_endpoint is set: both warnings claim that it is.
        """
        config = self.bootstrap_config
        if config.opentelemetry_exporter_protocol == "grpc":
            if not import_checker.is_otlp_grpc_exporter_installed:
                warn_at_caller(
                    "opentelemetry_endpoint is set but the gRPC OTLP exporter is not installed; "
                    "spans will not be exported. Install lite-bootstrap[otl].",
                    category=InstrumentDependencyMissingWarning,
                )
                return None
            return OTLPGrpcSpanExporter(
                endpoint=config.opentelemetry_endpoint,
                insecure=config.opentelemetry_insecure,
            )
        if not import_checker.is_otlp_http_exporter_installed:
            warn_at_caller(
                "opentelemetry_endpoint is set but the HTTP OTLP exporter is not installed; "
                "spans will not be exported. Install lite-bootstrap[otl-http].",
                category=InstrumentDependencyMissingWarning,
            )
            return None
        return OTLPHttpSpanExporter(endpoint=config.opentelemetry_endpoint)

    def _build_metric_exporter(self) -> "MetricExporter | None":
        """Return the OTLP metric exporter for the configured protocol, or None after warning it is missing.

        Only call this once opentelemetry_metrics_endpoint is set: both warnings claim that it is.
        """
        config = self.bootstrap_config
        if config.opentelemetry_exporter_protocol == "grpc":
            if not import_checker.is_otlp_grpc_exporter_installed:
                warn_at_caller(
                    "opentelemetry_metrics_endpoint is set but the gRPC OTLP exporter is not installed; "
                    "metrics will not be exported. Install lite-bootstrap[otl].",
                    category=InstrumentDependencyMissingWarning,
                )
                return None
            return OTLPGrpcMetricExporter(
                endpoint=config.opentelemetry_metrics_endpoint,
                insecure=config.opentelemetry_insecure,
            )
        if not import_checker.is_otlp_http_exporter_installed:
            warn_at_caller(
                "opentelemetry_metrics_endpoint is set but the HTTP OTLP exporter is not installed; "
                "metrics will not be exported. Install lite-bootstrap[otl-http].",
                category=InstrumentDependencyMissingWarning,
            )
            return None
        return OTLPHttpMetricExporter(endpoint=config.opentelemetry_metrics_endpoint)

    def _bootstrap_metrics(self, resource: "resources.Resource") -> None:
        config = self.bootstrap_config
        if not config.opentelemetry_metrics_endpoint:
            return
        metric_exporter = self._build_metric_exporter()
        if metric_exporter is None:
            return
        meter_provider = MeterProvider(
            resource=resource, metric_readers=[PeriodicExportingMetricReader(metric_exporter)]
        )
        set_meter_provider(meter_provider)
        if get_meter_provider() is not meter_provider:
            warn_at_caller(
                "a MeterProvider is already installed; the configured metrics exporter and resource will not be used"
            )
        self._meter_provider = meter_provider

    def _apply_instrumentors(self, tracer_provider: "TracerProvider") -> None:
        for one_instrumentor in self.bootstrap_config.opentelemetry_instrumentors:
            if isinstance(one_instrumentor, InstrumentorWithParams):
                one_instrumentor.instrumentor.instrument(
                    tracer_provider=tracer_provider,
                    **one_instrumentor.additional_params,
                )
            else:
                one_instrumentor.instrument(tracer_provider=tracer_provider)

    def bootstrap(self) -> None:
        config = self.bootstrap_config
        self._silence_otel_loggers()
        resource = self._build_resource()
        tracer_provider = TracerProvider(resource=resource, sampler=config.opentelemetry_sampler)
        set_tracer_provider(tracer_provider)
        if get_tracer_provider() is not tracer_provider:
            warn_at_caller(
                "a TracerProvider is already installed; the configured exporter, sampler and resource will not be used"
            )
        self._tracer_provider = tracer_provider
        if import_checker.is_pyroscope_installed and getattr(config, "pyroscope_endpoint", None):
            tracer_provider.add_span_processor(PyroscopeSpanProcessor())
        if config.opentelemetry_log_traces:
            tracer_provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter(formatter=_format_span)))
        if config.opentelemetry_endpoint and (span_exporter := self._build_span_exporter()):
            tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
        self._bootstrap_metrics(resource)
        self._apply_instrumentors(tracer_provider)

    def teardown(self) -> None:
        with collect_teardown_errors() as teardown_errors:
            for one_instrumentor in self.bootstrap_config.opentelemetry_instrumentors:
                with teardown_errors.capture(type(one_instrumentor).__name__):
                    if isinstance(one_instrumentor, InstrumentorWithParams):
                        one_instrumentor.instrumentor.uninstrument(**one_instrumentor.additional_params)
                    else:
                        one_instrumentor.uninstrument()
            for logger_name, prior in self._prior_logger_disabled.items():
                logging.getLogger(logger_name).disabled = prior
            self._prior_logger_disabled.clear()
            if self._tracer_provider is not None:
                try:
                    with teardown_errors.capture("TracerProvider"):
                        self._tracer_provider.shutdown()
                finally:
                    self._tracer_provider = None
            if self._meter_provider is not None:
                try:
                    with teardown_errors.capture("MeterProvider"):
                        self._meter_provider.shutdown()
                finally:
                    self._meter_provider = None


# Backward-compatible alias preserved for users importing the old (lowercase t) spelling.
OpentelemetryConfig = OpenTelemetryConfig
