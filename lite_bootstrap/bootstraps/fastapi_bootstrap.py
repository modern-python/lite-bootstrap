import contextlib
import dataclasses
import typing

from lite_bootstrap.bootstraps.base import BaseBootstrap
from lite_bootstrap.instruments.healthchecks_instrument import HealthChecksInstrument, HealthCheckTypedDict
from lite_bootstrap.instruments.logging_instrument import LoggingInstrument
from lite_bootstrap.instruments.opentelemetry_instrument import OpenTelemetryInstrument
from lite_bootstrap.instruments.sentry_instrument import SentryInstrument
from lite_bootstrap.service_config import ServiceConfig


with contextlib.suppress(ImportError):
    import fastapi
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.trace import get_tracer_provider


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class FastAPIHealthChecksInstrument(HealthChecksInstrument):
    enabled: bool = True
    path: str = "/health/"
    include_in_schema: bool = False

    def build_fastapi_health_check_router(self, service_config: ServiceConfig) -> fastapi.APIRouter:
        fastapi_router = fastapi.APIRouter(
            tags=["probes"],
            include_in_schema=self.include_in_schema,
        )

        @fastapi_router.get(self.path)
        async def health_check_handler() -> HealthCheckTypedDict:
            return self.render_health_check_data(service_config)

        return fastapi_router

    def bootstrap(self, service_config: ServiceConfig, application: fastapi.FastAPI | None = None) -> None:
        if application:
            application.include_router(self.build_fastapi_health_check_router(service_config))


@dataclasses.dataclass(kw_only=True, frozen=True)
class FastAPILoggingInstrument(LoggingInstrument): ...


@dataclasses.dataclass(kw_only=True, frozen=True)
class FastAPIOpenTelemetryInstrument(OpenTelemetryInstrument):
    excluded_urls: list[str] = dataclasses.field(default_factory=list)

    def bootstrap(self, service_config: ServiceConfig, application: fastapi.FastAPI | None = None) -> None:
        super().bootstrap(service_config, application)
        FastAPIInstrumentor.instrument_app(
            app=application,
            tracer_provider=get_tracer_provider(),
            excluded_urls=",".join(self.excluded_urls),
        )

    def teardown(self, application: fastapi.FastAPI | None = None) -> None:
        if application:
            FastAPIInstrumentor.uninstrument_app(application)
        super().teardown()


@dataclasses.dataclass(kw_only=True, frozen=True)
class FastAPISentryInstrument(SentryInstrument): ...


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class FastAPIBootstrap(BaseBootstrap[fastapi.FastAPI]):
    application: fastapi.FastAPI
    instruments: typing.Sequence[
        FastAPIOpenTelemetryInstrument
        | FastAPISentryInstrument
        | FastAPIHealthChecksInstrument
        | FastAPILoggingInstrument
    ]
    service_config: ServiceConfig
