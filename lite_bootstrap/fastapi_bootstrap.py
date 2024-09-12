import dataclasses

import fastapi
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from sentry_sdk.integrations.asgi import SentryAsgiMiddleware

from lite_bootstrap.opentelemetry_bootstrap import OpenTelemetryBootstrap
from lite_bootstrap.sentry_bootstrap import SentryBootstrap


@dataclasses.dataclass(kw_only=True, slots=True)
class FastAPIBootstrap:
    app: fastapi.FastAPI
    opentelemetry: OpenTelemetryBootstrap
    sentry: SentryBootstrap
    opentelemetry_excluded_urls: list[str] = dataclasses.field(default_factory=list)

    def bootstrap_init(self) -> None:
        if self.sentry.sentry_dsn:
            self.sentry.start_tracing()
            self.app.add_middleware(SentryAsgiMiddleware)

        self.opentelemetry.start_tracing()
        if self.opentelemetry.endpoint:
            FastAPIInstrumentor.instrument_app(
                app=self.app,
                tracer_provider=self.opentelemetry.tracer_provider,
                excluded_urls=",".join(self.opentelemetry_excluded_urls),
            )

    def teardown(self) -> None:
        self.opentelemetry.teardown()
        if self.opentelemetry.endpoint:
            FastAPIInstrumentor.uninstrument_app(self.app)
