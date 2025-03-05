import dataclasses
import typing

import pydantic
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.instrumentor import BaseInstrumentor  # type: ignore[attr-defined]
from opentelemetry.sdk import resources
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from lite_bootstrap.instruments.base import BaseInstrument


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class InstrumentorWithParams:
    instrumentor: BaseInstrumentor
    additional_params: dict[str, typing.Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass(kw_only=True, slots=True)
class OpenTelemetryInstrument(BaseInstrument):
    service_version: str = "1.0.0"
    service_name: str | None = None
    container_name: str | None = None
    endpoint: str | None = None
    namespace: str | None = None
    insecure: bool = pydantic.Field(default=True)
    instrumentors: list[InstrumentorWithParams | BaseInstrumentor] = dataclasses.field(default_factory=list)

    tracer_provider: TracerProvider = dataclasses.field(init=False)

    def is_ready(self) -> bool:
        return all(
            (
                self.endpoint,
                self.service_name,
            ),
        )

    def teardown(self) -> None:
        for one_instrumentor in self.instrumentors:
            if isinstance(one_instrumentor, InstrumentorWithParams):
                one_instrumentor.instrumentor.uninstrument(**one_instrumentor.additional_params)
            else:
                one_instrumentor.uninstrument()

    def bootstrap(self) -> None:
        attributes = {
            resources.SERVICE_NAME: self.service_name,
            resources.TELEMETRY_SDK_LANGUAGE: "python",
            resources.SERVICE_NAMESPACE: self.namespace,
            resources.SERVICE_VERSION: self.service_version,
            resources.CONTAINER_NAME: self.container_name,
        }
        resource: typing.Final = resources.Resource.create(
            attributes={k: v for k, v in attributes.items() if v},
        )
        self.tracer_provider = TracerProvider(resource=resource)
        self.tracer_provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(
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
