import contextlib
import dataclasses
import typing

from litestar.plugins.prometheus import PrometheusConfig, PrometheusController

from lite_bootstrap.bootstrappers.base import BaseBootstrapper
from lite_bootstrap.instruments.healthchecks_instrument import (
    HealthChecksConfig,
    HealthChecksInstrument,
    HealthCheckTypedDict,
)
from lite_bootstrap.instruments.logging_instrument import LoggingConfig, LoggingInstrument
from lite_bootstrap.instruments.opentelemetry_instrument import OpentelemetryConfig, OpenTelemetryInstrument
from lite_bootstrap.instruments.prometheus_instrument import (
    PrometheusConfig as PrometheusBootstrapperConfig,
)
from lite_bootstrap.instruments.prometheus_instrument import (
    PrometheusInstrument,
)
from lite_bootstrap.instruments.sentry_instrument import SentryConfig, SentryInstrument


with contextlib.suppress(ImportError):
    import litestar
    from litestar.config.app import AppConfig
    from litestar.contrib.opentelemetry import OpenTelemetryConfig
    from opentelemetry.trace import get_tracer_provider


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class LitestarConfig(
    HealthChecksConfig, LoggingConfig, OpentelemetryConfig, PrometheusBootstrapperConfig, SentryConfig
):
    application_config: AppConfig = dataclasses.field(default_factory=AppConfig)
    opentelemetry_excluded_urls: list[str] = dataclasses.field(default_factory=list)
    prometheus_additional_params: dict[str, typing.Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class LitestarHealthChecksInstrument(HealthChecksInstrument):
    bootstrap_config: LitestarConfig

    def build_litestar_health_check_router(self) -> litestar.Router:
        @litestar.get(media_type=litestar.MediaType.JSON)
        async def health_check_handler() -> HealthCheckTypedDict:
            return self.render_health_check_data()

        return litestar.Router(
            path=self.bootstrap_config.health_checks_path,
            route_handlers=[health_check_handler],
            tags=["probes"],
            include_in_schema=self.bootstrap_config.health_checks_include_in_schema,
        )

    def bootstrap(self) -> None:
        self.bootstrap_config.application_config.route_handlers.append(self.build_litestar_health_check_router())


@dataclasses.dataclass(kw_only=True, frozen=True)
class LitestarLoggingInstrument(LoggingInstrument):
    bootstrap_config: LitestarConfig


@dataclasses.dataclass(kw_only=True, frozen=True)
class LitestarOpenTelemetryInstrument(OpenTelemetryInstrument):
    bootstrap_config: LitestarConfig

    def _build_excluded_urls(self) -> list[str]:
        excluded_urls = [*self.bootstrap_config.opentelemetry_excluded_urls]
        for one_url in (self.bootstrap_config.health_checks_path, self.bootstrap_config.prometheus_metrics_path):
            if one_url and one_url not in excluded_urls:
                excluded_urls.append(one_url)
        return excluded_urls

    def bootstrap(self) -> None:
        super().bootstrap()
        self.bootstrap_config.application_config.middleware.append(
            OpenTelemetryConfig(
                tracer_provider=get_tracer_provider(),
                exclude=self._build_excluded_urls(),
            ).middleware,
        )


@dataclasses.dataclass(kw_only=True, frozen=True)
class LitestarSentryInstrument(SentryInstrument):
    bootstrap_config: LitestarConfig


@dataclasses.dataclass(kw_only=True, frozen=True)
class LitestarPrometheusInstrument(PrometheusInstrument):
    bootstrap_config: LitestarConfig

    def bootstrap(self) -> None:
        class LitestarPrometheusController(PrometheusController):
            path = self.bootstrap_config.prometheus_metrics_path
            include_in_schema = self.bootstrap_config.prometheus_metrics_include_in_schema
            openmetrics_format = True

        litestar_prometheus_config = PrometheusConfig(
            app_name=self.bootstrap_config.service_name,
            **self.bootstrap_config.prometheus_additional_params,
        )

        self.bootstrap_config.application_config.route_handlers.append(LitestarPrometheusController)
        self.bootstrap_config.application_config.middleware.append(litestar_prometheus_config.middleware)


class LitestarBootstrapper(BaseBootstrapper[litestar.Litestar]):
    instruments_types: typing.ClassVar = [
        LitestarOpenTelemetryInstrument,
        LitestarSentryInstrument,
        LitestarHealthChecksInstrument,
        LitestarLoggingInstrument,
        LitestarPrometheusInstrument,
    ]
    bootstrap_config: LitestarConfig
    __slots__ = "bootstrap_config", "instruments"

    def __init__(self, bootstrap_config: LitestarConfig) -> None:
        super().__init__(bootstrap_config)

    def _prepare_application(self) -> litestar.Litestar:
        return litestar.Litestar.from_config(self.bootstrap_config.application_config)
