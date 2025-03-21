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
    import litestar
    from litestar.config.app import AppConfig
    from litestar.contrib.opentelemetry import OpenTelemetryConfig
    from opentelemetry.trace import get_tracer_provider


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class LitestarHealthChecksInstrument(HealthChecksInstrument):
    enabled: bool = True
    path: str = "/health/"
    include_in_schema: bool = False

    def build_litestar_health_check_router(self, service_config: ServiceConfig) -> litestar.Router:
        @litestar.get(media_type=litestar.MediaType.JSON)
        async def health_check_handler() -> HealthCheckTypedDict:
            return self.render_health_check_data(service_config)

        return litestar.Router(
            path=self.path,
            route_handlers=[health_check_handler],
            tags=["probes"],
            include_in_schema=self.include_in_schema,
        )

    def bootstrap(self, service_config: ServiceConfig, app_config: AppConfig | None = None) -> None:
        if app_config:
            app_config.route_handlers.append(self.build_litestar_health_check_router(service_config))


@dataclasses.dataclass(kw_only=True, frozen=True)
class LitestarLoggingInstrument(LoggingInstrument): ...


@dataclasses.dataclass(kw_only=True, frozen=True)
class LitestarOpenTelemetryInstrument(OpenTelemetryInstrument):
    excluded_urls: list[str] = dataclasses.field(default_factory=list)

    def bootstrap(self, service_config: ServiceConfig, app_config: AppConfig | None = None) -> None:
        super().bootstrap(service_config, app_config)
        if app_config:
            app_config.middleware.append(
                OpenTelemetryConfig(
                    tracer_provider=get_tracer_provider(),
                    exclude=self.excluded_urls,
                ).middleware,
            )


@dataclasses.dataclass(kw_only=True, frozen=True)
class LitestarSentryInstrument(SentryInstrument): ...


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class LitestarBootstrap(BaseBootstrap[AppConfig]):
    application: AppConfig
    instruments: typing.Sequence[
        LitestarOpenTelemetryInstrument
        | LitestarSentryInstrument
        | LitestarHealthChecksInstrument
        | LitestarLoggingInstrument
    ]
    service_config: ServiceConfig
