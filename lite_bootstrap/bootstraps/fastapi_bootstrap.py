import dataclasses
import typing

import fastapi
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from sentry_sdk.integrations.asgi import SentryAsgiMiddleware

from lite_bootstrap.bootstraps.base import BaseBootstrap
from lite_bootstrap.instruments.opentelemetry_instrument import OpenTelemetryInstrument
from lite_bootstrap.instruments.sentry_instrument import SentryInstrument


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


@dataclasses.dataclass(kw_only=True)
class FastAPISentryInstrument(SentryInstrument):
    app: fastapi.FastAPI = dataclasses.field(init=False)

    def bootstrap(self) -> None:
        super().bootstrap()
        self.app.add_middleware(SentryAsgiMiddleware)  # type: ignore[arg-type]

    def teardown(self) -> None:
        FastAPIInstrumentor.uninstrument_app(self.app)
        super().teardown()


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class FastAPIBootstrap(BaseBootstrap):
    app: fastapi.FastAPI
    instruments: typing.Sequence[FastAPIOpenTelemetryInstrument | FastAPISentryInstrument]

    def __post_init__(self) -> None:
        for one_instrument in self.instruments:
            one_instrument.app = self.app
