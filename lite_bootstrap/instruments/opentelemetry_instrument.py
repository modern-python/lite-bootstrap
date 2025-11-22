import dataclasses
import os
import typing

from lite_bootstrap import import_checker
from lite_bootstrap.instruments.base import BaseConfig, BaseInstrument


if typing.TYPE_CHECKING:
    from opentelemetry.instrumentation.instrumentor import BaseInstrumentor  # type: ignore[attr-defined]

if import_checker.is_opentelemetry_installed:
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk import resources
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter, SimpleSpanProcessor
    from opentelemetry.trace import set_tracer_provider


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class InstrumentorWithParams:
    instrumentor: "BaseInstrumentor"
    additional_params: dict[str, typing.Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass(kw_only=True, frozen=True)
class OpentelemetryConfig(BaseConfig):
    opentelemetry_service_name: str | None = None
    opentelemetry_container_name: str | None = dataclasses.field(
        default_factory=lambda: os.environ.get("HOSTNAME") or None
    )
    opentelemetry_endpoint: str | None = None
    opentelemetry_namespace: str | None = None
    opentelemetry_insecure: bool = True
    opentelemetry_instrumentors: list[typing.Union[InstrumentorWithParams, "BaseInstrumentor"]] = dataclasses.field(
        default_factory=list
    )
    opentelemetry_log_traces: bool = False
    opentelemetry_generate_health_check_spans: bool = True


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class OpenTelemetryInstrument(BaseInstrument):
    bootstrap_config: OpentelemetryConfig
    not_ready_message = "opentelemetry_endpoint is empty and opentelemetry_log_traces is False"
    missing_dependency_message = "opentelemetry is not installed"

    def is_ready(self) -> bool:
        return (
            bool(self.bootstrap_config.opentelemetry_endpoint or self.bootstrap_config.opentelemetry_log_traces)
            and import_checker.is_opentelemetry_installed
        )

    @staticmethod
    def check_dependencies() -> bool:
        return import_checker.is_opentelemetry_installed

    def bootstrap(self) -> None:
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
        if self.bootstrap_config.opentelemetry_log_traces:
            tracer_provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
        if self.bootstrap_config.opentelemetry_endpoint:
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
        set_tracer_provider(tracer_provider)

    def teardown(self) -> None:
        for one_instrumentor in self.bootstrap_config.opentelemetry_instrumentors:
            if isinstance(one_instrumentor, InstrumentorWithParams):
                one_instrumentor.instrumentor.uninstrument(**one_instrumentor.additional_params)
            else:
                one_instrumentor.uninstrument()
