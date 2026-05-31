import dataclasses
import logging
import os
import typing

from lite_bootstrap import import_checker
from lite_bootstrap.instruments.base import BaseConfig, BaseInstrument


if typing.TYPE_CHECKING:
    from opentelemetry.instrumentation.instrumentor import BaseInstrumentor

if import_checker.is_opentelemetry_installed:
    from opentelemetry.context import Context
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk import resources
    from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor, TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter, SimpleSpanProcessor
    from opentelemetry.trace import Span, format_span_id, set_tracer_provider

if import_checker.is_pyroscope_installed:
    import pyroscope


def _format_span(readable_span: "ReadableSpan") -> str:
    return typing.cast("str", readable_span.to_json(indent=None)) + os.linesep


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class InstrumentorWithParams:
    instrumentor: "BaseInstrumentor"
    additional_params: dict[str, typing.Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass(kw_only=True, frozen=True)
class OpenTelemetryServiceFieldsConfig(BaseConfig):
    opentelemetry_service_name: str | None = None
    opentelemetry_namespace: str | None = None


@dataclasses.dataclass(kw_only=True, frozen=True)
class OpentelemetryConfig(OpenTelemetryServiceFieldsConfig):
    opentelemetry_container_name: str | None = dataclasses.field(
        default_factory=lambda: os.environ.get("HOSTNAME") or None
    )
    opentelemetry_endpoint: str | None = None
    opentelemetry_insecure: bool = True
    opentelemetry_instrumentors: list[typing.Union[InstrumentorWithParams, "BaseInstrumentor"]] = dataclasses.field(
        default_factory=list
    )
    opentelemetry_log_traces: bool = False
    opentelemetry_generate_health_check_spans: bool = True


if import_checker.is_opentelemetry_installed and import_checker.is_pyroscope_installed:
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

        def force_flush(self, timeout_millis: int = 30000) -> bool:  # pragma: no cover  # noqa: ARG002
            return True


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class OpenTelemetryInstrument(BaseInstrument):
    bootstrap_config: OpentelemetryConfig
    not_ready_message = "opentelemetry_endpoint is empty and opentelemetry_log_traces is False"
    missing_dependency_message = "opentelemetry is not installed"
    _tracer_provider: "TracerProvider | None" = dataclasses.field(
        default_factory=lambda: None, init=False, repr=False, compare=False
    )

    def is_ready(self) -> bool:
        return bool(self.bootstrap_config.opentelemetry_endpoint or self.bootstrap_config.opentelemetry_log_traces)

    @staticmethod
    def check_dependencies() -> bool:
        return import_checker.is_opentelemetry_installed

    def bootstrap(self) -> None:
        logging.getLogger("opentelemetry.instrumentation.instrumentor").disabled = True
        logging.getLogger("opentelemetry.trace").disabled = True
        attributes = {
            resources.SERVICE_NAME: self.bootstrap_config.opentelemetry_service_name
            or self.bootstrap_config.service_name,
            resources.TELEMETRY_SDK_LANGUAGE: "python",
            resources.SERVICE_NAMESPACE: self.bootstrap_config.opentelemetry_namespace,
            resources.SERVICE_VERSION: self.bootstrap_config.service_version,
            resources.CONTAINER_NAME: self.bootstrap_config.opentelemetry_container_name,
        }
        resource: typing.Final = resources.Resource.create(
            attributes={k: v for k, v in attributes.items() if v},
        )
        tracer_provider = TracerProvider(resource=resource)
        set_tracer_provider(tracer_provider)
        object.__setattr__(self, "_tracer_provider", tracer_provider)
        if import_checker.is_pyroscope_installed and getattr(self.bootstrap_config, "pyroscope_endpoint", None):
            tracer_provider.add_span_processor(PyroscopeSpanProcessor())
        if self.bootstrap_config.opentelemetry_log_traces:
            tracer_provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter(formatter=_format_span)))
        if self.bootstrap_config.opentelemetry_endpoint:  # pragma: no cover
            tracer_provider.add_span_processor(
                BatchSpanProcessor(
                    OTLPSpanExporter(
                        endpoint=self.bootstrap_config.opentelemetry_endpoint,
                        insecure=self.bootstrap_config.opentelemetry_insecure,
                    ),
                ),
            )
        for one_instrumentor in self.bootstrap_config.opentelemetry_instrumentors:
            if isinstance(one_instrumentor, InstrumentorWithParams):
                one_instrumentor.instrumentor.instrument(
                    tracer_provider=tracer_provider,
                    **one_instrumentor.additional_params,
                )
            else:
                one_instrumentor.instrument(tracer_provider=tracer_provider)

    def teardown(self) -> None:
        for one_instrumentor in self.bootstrap_config.opentelemetry_instrumentors:
            if isinstance(one_instrumentor, InstrumentorWithParams):
                one_instrumentor.instrumentor.uninstrument(**one_instrumentor.additional_params)
            else:
                one_instrumentor.uninstrument()
        if self._tracer_provider is not None:
            try:
                self._tracer_provider.shutdown()
            finally:
                object.__setattr__(self, "_tracer_provider", None)
