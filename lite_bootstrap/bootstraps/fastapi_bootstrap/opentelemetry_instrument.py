import contextlib
import dataclasses

import fastapi

from lite_bootstrap.instruments.opentelemetry_instrument import OpenTelemetryInstrument


with contextlib.suppress(ImportError):
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor


@dataclasses.dataclass(kw_only=True)
class FastAPIOpenTelemetryInstrument(OpenTelemetryInstrument):
    excluded_urls: list[str] = dataclasses.field(default_factory=list)
    app: fastapi.FastAPI = dataclasses.field(init=False)

    def bootstrap(self) -> None:
        super().bootstrap()
        FastAPIInstrumentor.instrument_app(
            app=self.app,
            tracer_provider=self.tracer_provider,
            excluded_urls=",".join(self.excluded_urls),
        )

    def teardown(self) -> None:
        FastAPIInstrumentor.uninstrument_app(self.app)
        super().teardown()
