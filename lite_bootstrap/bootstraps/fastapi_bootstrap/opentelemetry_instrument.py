import contextlib
import dataclasses

import fastapi

from lite_bootstrap.instruments.opentelemetry_instrument import OpenTelemetryInstrument
from lite_bootstrap.service_config import ServiceConfig


with contextlib.suppress(ImportError):
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor


@dataclasses.dataclass(kw_only=True)
class FastAPIOpenTelemetryInstrument(OpenTelemetryInstrument):
    excluded_urls: list[str] = dataclasses.field(default_factory=list)

    def bootstrap(self, service_config: ServiceConfig, application: fastapi.FastAPI | None = None) -> None:
        super().bootstrap(service_config, application)
        FastAPIInstrumentor.instrument_app(
            app=application,
            tracer_provider=self.tracer_provider,
            excluded_urls=",".join(self.excluded_urls),
        )

    def teardown(self, application: fastapi.FastAPI | None = None) -> None:
        if application:
            FastAPIInstrumentor.uninstrument_app(application)
        super().teardown()
