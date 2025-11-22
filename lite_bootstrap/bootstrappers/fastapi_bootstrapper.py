import contextlib
import dataclasses
import typing
import warnings

from lite_bootstrap import import_checker
from lite_bootstrap.bootstrappers.base import BaseBootstrapper
from lite_bootstrap.helpers.fastapi_helpers import enable_offline_docs
from lite_bootstrap.instruments.cors_instrument import CorsConfig, CorsInstrument
from lite_bootstrap.instruments.healthchecks_instrument import (
    HealthChecksConfig,
    HealthChecksInstrument,
    HealthCheckTypedDict,
)
from lite_bootstrap.instruments.logging_instrument import LoggingConfig, LoggingInstrument
from lite_bootstrap.instruments.opentelemetry_instrument import OpentelemetryConfig, OpenTelemetryInstrument
from lite_bootstrap.instruments.prometheus_instrument import PrometheusConfig, PrometheusInstrument
from lite_bootstrap.instruments.sentry_instrument import SentryConfig, SentryInstrument
from lite_bootstrap.instruments.swagger_instrument import SwaggerConfig, SwaggerInstrument


if import_checker.is_fastapi_installed:
    import fastapi
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.routing import _merge_lifespan_context

if import_checker.is_opentelemetry_installed:
    from opentelemetry.trace import get_tracer_provider

if import_checker.is_fastapi_opentelemetry_installed:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

if import_checker.is_prometheus_fastapi_instrumentator_installed:
    from prometheus_fastapi_instrumentator import Instrumentator


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class FastAPIConfig(
    CorsConfig, HealthChecksConfig, LoggingConfig, OpentelemetryConfig, PrometheusConfig, SentryConfig, SwaggerConfig
):
    application: "fastapi.FastAPI" = dataclasses.field(default=None)  # type: ignore[assignment]
    application_kwargs: dict[str, typing.Any] = dataclasses.field(default_factory=dict)
    opentelemetry_excluded_urls: list[str] = dataclasses.field(default_factory=list)
    prometheus_instrumentator_params: dict[str, typing.Any] = dataclasses.field(default_factory=dict)
    prometheus_instrument_params: dict[str, typing.Any] = dataclasses.field(default_factory=dict)
    prometheus_expose_params: dict[str, typing.Any] = dataclasses.field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.application:
            object.__setattr__(
                self, "application", fastapi.FastAPI(docs_url=self.swagger_path, **self.application_kwargs)
            )
        elif self.application_kwargs:
            warnings.warn("application_kwargs must be used without application", stacklevel=2)

        self.application.title = self.service_name
        self.application.debug = self.service_debug
        self.application.version = self.service_version


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class FastApiCorsInstrument(CorsInstrument):
    bootstrap_config: FastAPIConfig

    def bootstrap(self) -> None:
        self.bootstrap_config.application.add_middleware(
            CORSMiddleware,
            allow_origins=self.bootstrap_config.cors_allowed_origins,
            allow_methods=self.bootstrap_config.cors_allowed_methods,
            allow_headers=self.bootstrap_config.cors_allowed_headers,
            allow_credentials=self.bootstrap_config.cors_allowed_credentials,
            allow_origin_regex=self.bootstrap_config.cors_allowed_origin_regex,
            expose_headers=self.bootstrap_config.cors_exposed_headers,
            max_age=self.bootstrap_config.cors_max_age,
        )


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class FastAPIHealthChecksInstrument(HealthChecksInstrument):
    bootstrap_config: FastAPIConfig

    def build_fastapi_health_check_router(self) -> "fastapi.APIRouter":
        fastapi_router = fastapi.APIRouter(
            tags=["probes"],
            include_in_schema=self.bootstrap_config.health_checks_include_in_schema,
        )

        @fastapi_router.get(self.bootstrap_config.health_checks_path)
        async def health_check_handler() -> HealthCheckTypedDict:
            return self.render_health_check_data()

        return fastapi_router

    def bootstrap(self) -> None:
        self.bootstrap_config.application.include_router(self.build_fastapi_health_check_router())


@dataclasses.dataclass(kw_only=True, frozen=True)
class FastAPILoggingInstrument(LoggingInstrument):
    bootstrap_config: FastAPIConfig


@dataclasses.dataclass(kw_only=True, frozen=True)
class FastAPIOpenTelemetryInstrument(OpenTelemetryInstrument):
    bootstrap_config: FastAPIConfig

    def _build_excluded_urls(self) -> set[str]:
        excluded_urls = set(self.bootstrap_config.opentelemetry_excluded_urls)
        excluded_urls.add(self.bootstrap_config.prometheus_metrics_path)
        if not self.bootstrap_config.opentelemetry_generate_health_check_spans:
            excluded_urls.add(self.bootstrap_config.health_checks_path)

        return excluded_urls

    def bootstrap(self) -> None:
        super().bootstrap()
        FastAPIInstrumentor.instrument_app(
            app=self.bootstrap_config.application,
            tracer_provider=get_tracer_provider(),
            excluded_urls=",".join(self._build_excluded_urls()),
        )

    def teardown(self) -> None:
        FastAPIInstrumentor.uninstrument_app(self.bootstrap_config.application)
        super().teardown()


@dataclasses.dataclass(kw_only=True, frozen=True)
class FastAPISentryInstrument(SentryInstrument):
    bootstrap_config: FastAPIConfig


@dataclasses.dataclass(kw_only=True, frozen=True)
class FastAPIPrometheusInstrument(PrometheusInstrument):
    bootstrap_config: FastAPIConfig
    missing_dependency_message = "prometheus_fastapi_instrumentator is not installed"

    @staticmethod
    def check_dependencies() -> bool:
        return import_checker.is_prometheus_fastapi_instrumentator_installed

    def bootstrap(self) -> None:
        Instrumentator(**self.bootstrap_config.prometheus_instrumentator_params).instrument(
            self.bootstrap_config.application,
            **self.bootstrap_config.prometheus_instrument_params,
        ).expose(
            self.bootstrap_config.application,
            endpoint=self.bootstrap_config.prometheus_metrics_path,
            include_in_schema=self.bootstrap_config.prometheus_metrics_include_in_schema,
            **self.bootstrap_config.prometheus_expose_params,
        )


@dataclasses.dataclass(kw_only=True, frozen=True)
class FastApiSwaggerInstrument(SwaggerInstrument):
    bootstrap_config: FastAPIConfig

    def bootstrap(self) -> None:
        if self.bootstrap_config.swagger_path != self.bootstrap_config.application.docs_url:
            warnings.warn(
                f"swagger_path is differ from docs_url, "
                f"{self.bootstrap_config.application.docs_url} will be used for docs path",
                stacklevel=2,
            )
        if self.bootstrap_config.swagger_offline_docs:
            enable_offline_docs(
                self.bootstrap_config.application, static_path=self.bootstrap_config.swagger_static_path
            )


class FastAPIBootstrapper(BaseBootstrapper["fastapi.FastAPI"]):
    __slots__ = "bootstrap_config", "instruments"

    instruments_types: typing.ClassVar = [
        FastApiCorsInstrument,
        FastAPIOpenTelemetryInstrument,
        FastAPISentryInstrument,
        FastAPIHealthChecksInstrument,
        FastAPILoggingInstrument,
        FastAPIPrometheusInstrument,
        FastApiSwaggerInstrument,
    ]
    bootstrap_config: FastAPIConfig
    not_ready_message = "fastapi is not installed"

    @contextlib.asynccontextmanager
    async def lifespan_manager(self, _: "fastapi.FastAPI") -> typing.AsyncIterator[dict[str, typing.Any]]:
        try:
            yield {}
        finally:
            self.teardown()

    def __init__(self, bootstrap_config: FastAPIConfig) -> None:
        super().__init__(bootstrap_config)

        old_lifespan_manager = self.bootstrap_config.application.router.lifespan_context
        self.bootstrap_config.application.router.lifespan_context = _merge_lifespan_context(
            old_lifespan_manager,
            self.lifespan_manager,
        )

    def is_ready(self) -> bool:
        return import_checker.is_fastapi_installed

    def _prepare_application(self) -> "fastapi.FastAPI":
        return self.bootstrap_config.application
