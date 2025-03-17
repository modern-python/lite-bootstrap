import contextlib
import dataclasses
import typing

from lite_bootstrap.instruments.base import BaseInstrument
from lite_bootstrap.service_config import ServiceConfig
from lite_bootstrap.types import ApplicationT


with contextlib.suppress(ImportError):
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.instrumentor import BaseInstrumentor  # type: ignore[attr-defined]
    from opentelemetry.sdk import resources
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class InstrumentorWithParams:
    instrumentor: BaseInstrumentor
    additional_params: dict[str, typing.Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass(kw_only=True, slots=True)
class OpenTelemetryInstrument(BaseInstrument):
    container_name: str | None = None
    endpoint: str | None = None
    namespace: str | None = None
    insecure: bool = True
    instrumentors: list[InstrumentorWithParams | BaseInstrumentor] = dataclasses.field(default_factory=list)
    span_exporter: SpanExporter | None = None

    tracer_provider: TracerProvider = dataclasses.field(init=False)

    def is_ready(self) -> bool:
        return bool(self.endpoint)

    def bootstrap(self, service_config: ServiceConfig, _: ApplicationT | None = None) -> None:
        attributes = {
            resources.SERVICE_NAME: service_config.service_name,
            resources.TELEMETRY_SDK_LANGUAGE: "python",
            resources.SERVICE_NAMESPACE: self.namespace,
            resources.SERVICE_VERSION: service_config.service_version,
            resources.CONTAINER_NAME: self.container_name,
        }
        resource: typing.Final = resources.Resource.create(
            attributes={k: v for k, v in attributes.items() if v},
        )
        self.tracer_provider = TracerProvider(resource=resource)
        self.tracer_provider.add_span_processor(
            BatchSpanProcessor(
                self.span_exporter
                or OTLPSpanExporter(
                    endpoint=self.endpoint,
                    insecure=self.insecure,
                ),
            ),
        )
        for one_instrumentor in self.instrumentors:
            if isinstance(one_instrumentor, InstrumentorWithParams):
                one_instrumentor.instrumentor.instrument(
                    tracer_provider=self.tracer_provider,
                    **one_instrumentor.additional_params,
                )
            else:
                one_instrumentor.instrument(tracer_provider=self.tracer_provider)

    def teardown(self, _: ApplicationT | None = None) -> None:
        for one_instrumentor in self.instrumentors:
            if isinstance(one_instrumentor, InstrumentorWithParams):
                one_instrumentor.instrumentor.uninstrument(**one_instrumentor.additional_params)
            else:
                one_instrumentor.uninstrument()
