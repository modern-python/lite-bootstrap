import dataclasses

from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.instrumentor import BaseInstrumentor  # type: ignore[attr-defined]
from opentelemetry.sdk import resources
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import set_tracer_provider


@dataclasses.dataclass(kw_only=True, slots=True)
class OpenTelemetryBootstrap:
    endpoint: str
    service_name: str
    instruments: list[BaseInstrumentor] = dataclasses.field(default_factory=list)
    tracer_provider: TracerProvider | None = dataclasses.field(init=False)

    def start_tracing(self) -> None:
        if not self.endpoint:
            return

        self.tracer_provider: TracerProvider = TracerProvider(
            resource=resources.Resource.create({resources.SERVICE_NAME: self.service_name}),
        )
        self.tracer_provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(
                    endpoint=self.endpoint,
                    insecure=True,
                ),
            ),
        )

        for instrument in self.instruments:
            instrument.instrument(
                tracer_provider=self.tracer_provider,
            )

        set_tracer_provider(self.tracer_provider)

    def teardown(self) -> None:
        if not self.endpoint:
            return

        for instrument in self.instruments:
            instrument.uninstrument()
