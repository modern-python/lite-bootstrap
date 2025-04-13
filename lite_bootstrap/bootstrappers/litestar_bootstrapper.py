import dataclasses
import pathlib
import typing

from lite_bootstrap import import_checker
from lite_bootstrap.bootstrappers.base import BaseBootstrapper
from lite_bootstrap.instruments.cors_instrument import CorsConfig, CorsInstrument
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
from lite_bootstrap.instruments.swagger_instrument import SwaggerConfig, SwaggerInstrument


if import_checker.is_litestar_installed:
    import litestar
    from litestar.config.app import AppConfig
    from litestar.config.cors import CORSConfig
    from litestar.contrib.opentelemetry import OpenTelemetryConfig
    from litestar.openapi import OpenAPIConfig
    from litestar.openapi.plugins import SwaggerRenderPlugin
    from litestar.plugins.prometheus import PrometheusConfig, PrometheusController
    from litestar.static_files import create_static_files_router

if import_checker.is_opentelemetry_installed:
    from opentelemetry.trace import get_tracer_provider


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class LitestarConfig(
    CorsConfig,
    HealthChecksConfig,
    LoggingConfig,
    OpentelemetryConfig,
    PrometheusBootstrapperConfig,
    SentryConfig,
    SwaggerConfig,
):
    application_config: "AppConfig" = dataclasses.field(default_factory=lambda: AppConfig())
    opentelemetry_excluded_urls: list[str] = dataclasses.field(default_factory=list)
    prometheus_additional_params: dict[str, typing.Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class LitestarCorsInstrument(CorsInstrument):
    bootstrap_config: LitestarConfig

    def bootstrap(self) -> None:
        self.bootstrap_config.application_config.cors_config = CORSConfig(
            allow_origins=self.bootstrap_config.cors_allowed_origins,
            allow_methods=self.bootstrap_config.cors_allowed_methods,  # type: ignore[arg-type]
            allow_headers=self.bootstrap_config.cors_allowed_headers,
            allow_credentials=self.bootstrap_config.cors_allowed_credentials,
            allow_origin_regex=self.bootstrap_config.cors_allowed_origin_regex,
            expose_headers=self.bootstrap_config.cors_exposed_headers,
            max_age=self.bootstrap_config.cors_max_age,
        )


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class LitestarHealthChecksInstrument(HealthChecksInstrument):
    bootstrap_config: LitestarConfig

    def build_litestar_health_check_router(self) -> "litestar.Router":
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
    not_ready_message = PrometheusInstrument.not_ready_message + " or prometheus_client is not installed"

    def is_ready(self) -> bool:
        return super().is_ready() and import_checker.is_prometheus_client_installed

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


@dataclasses.dataclass(kw_only=True, frozen=True)
class LitestarSwaggerInstrument(SwaggerInstrument):
    bootstrap_config: LitestarConfig

    def bootstrap(self) -> None:
        render_plugins: typing.Final = (
            (
                SwaggerRenderPlugin(
                    js_url=f"{self.bootstrap_config.service_static_path}/swagger-ui-bundle.js",
                    css_url=f"{self.bootstrap_config.service_static_path}/swagger-ui.css",
                    standalone_preset_js_url=(
                        f"{self.bootstrap_config.service_static_path}/swagger-ui-standalone-preset.js"
                    ),
                ),
            )
            if self.bootstrap_config.swagger_offline_docs
            else (SwaggerRenderPlugin(),)
        )
        self.bootstrap_config.application_config.openapi_config = OpenAPIConfig(
            path=self.bootstrap_config.swagger_path,
            title=self.bootstrap_config.service_name,
            version=self.bootstrap_config.service_version,
            description=self.bootstrap_config.service_description,
            render_plugins=render_plugins,
            **self.bootstrap_config.swagger_extra_params,
        )
        if self.bootstrap_config.swagger_offline_docs:
            static_dir_path = pathlib.Path(__file__).parent.parent / "litestar_swagger_static"
            self.bootstrap_config.application_config.route_handlers.append(
                create_static_files_router(
                    path=self.bootstrap_config.service_static_path, directories=[static_dir_path]
                )
            )


class LitestarBootstrapper(BaseBootstrapper["litestar.Litestar"]):
    __slots__ = "bootstrap_config", "instruments"

    instruments_types: typing.ClassVar = [
        LitestarCorsInstrument,
        LitestarOpenTelemetryInstrument,
        LitestarSentryInstrument,
        LitestarHealthChecksInstrument,
        LitestarLoggingInstrument,
        LitestarPrometheusInstrument,
        LitestarSwaggerInstrument,
    ]
    bootstrap_config: LitestarConfig
    not_ready_message = "litestar is not installed"

    def is_ready(self) -> bool:
        return import_checker.is_litestar_installed

    def _prepare_application(self) -> "litestar.Litestar":
        return litestar.Litestar.from_config(self.bootstrap_config.application_config)
