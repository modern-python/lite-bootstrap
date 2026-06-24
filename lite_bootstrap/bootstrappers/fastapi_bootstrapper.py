import contextlib
import dataclasses
import typing
import warnings

from lite_bootstrap import import_checker
from lite_bootstrap.bootstrappers.base import BaseBootstrapper
from lite_bootstrap.exceptions import ConfigurationError
from lite_bootstrap.helpers.fastapi_helpers import enable_offline_docs
from lite_bootstrap.instruments.cors_instrument import CorsConfig, CorsInstrument
from lite_bootstrap.instruments.healthchecks_instrument import (
    HealthChecksConfig,
    HealthChecksInstrument,
    HealthCheckTypedDict,
)
from lite_bootstrap.instruments.logging_instrument import LoggingConfig, LoggingInstrument
from lite_bootstrap.instruments.opentelemetry_instrument import OpenTelemetryConfig, OpenTelemetryInstrument
from lite_bootstrap.instruments.prometheus_instrument import PrometheusConfig, PrometheusInstrument
from lite_bootstrap.instruments.pyroscope_instrument import PyroscopeConfig, PyroscopeInstrument
from lite_bootstrap.instruments.sentry_instrument import SentryConfig, SentryInstrument
from lite_bootstrap.instruments.swagger_instrument import SwaggerConfig, SwaggerInstrument
from lite_bootstrap.types import UNSET, UnsetType


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
    CorsConfig,
    HealthChecksConfig,
    LoggingConfig,
    OpenTelemetryConfig,
    PrometheusConfig,
    PyroscopeConfig,
    SentryConfig,
    SwaggerConfig,
):
    application: "fastapi.FastAPI | UnsetType" = UNSET
    application_kwargs: dict[str, typing.Any] = dataclasses.field(default_factory=dict)
    opentelemetry_excluded_urls: list[str] = dataclasses.field(default_factory=list)
    prometheus_instrumentator_params: dict[str, typing.Any] = dataclasses.field(default_factory=dict)
    prometheus_instrument_params: dict[str, typing.Any] = dataclasses.field(default_factory=dict)
    prometheus_expose_params: dict[str, typing.Any] = dataclasses.field(default_factory=dict)

    def __post_init__(self) -> None:
        # @dataclass(slots=True) replaces the class object, breaking bare super().
        super(FastAPIConfig, self).__post_init__()
        if not import_checker.is_fastapi_installed:
            msg = "fastapi is not installed"
            raise ConfigurationError(msg)

        if isinstance(self.application, UnsetType):
            application = fastapi.FastAPI(docs_url=self.swagger_path, **self.application_kwargs)
            # FastAPIConfig stays frozen for user-facing immutability; __post_init__ needs
            # to set application after construction, so we bypass the freeze here.
            object.__setattr__(self, "application", application)
            application.title = self.service_name
            application.debug = self.service_debug
            application.version = self.service_version
        elif self.application_kwargs:
            warnings.warn("application_kwargs must be used without application", stacklevel=2)


def _narrow_app(config: "FastAPIConfig") -> "fastapi.FastAPI":
    if isinstance(config.application, UnsetType):
        msg = "FastAPIConfig.application is UNSET; __post_init__ did not run"
        raise TypeError(msg)
    return config.application


@dataclasses.dataclass(kw_only=True, slots=True)
class FastAPICorsInstrument(CorsInstrument):
    bootstrap_config: FastAPIConfig

    def bootstrap(self) -> None:
        _narrow_app(self.bootstrap_config).add_middleware(
            CORSMiddleware,
            allow_origins=self.bootstrap_config.cors_allowed_origins,
            allow_methods=self.bootstrap_config.cors_allowed_methods,
            allow_headers=self.bootstrap_config.cors_allowed_headers,
            allow_credentials=self.bootstrap_config.cors_allowed_credentials,
            allow_origin_regex=self.bootstrap_config.cors_allowed_origin_regex,
            expose_headers=self.bootstrap_config.cors_exposed_headers,
            max_age=self.bootstrap_config.cors_max_age,
        )


@dataclasses.dataclass(kw_only=True, slots=True)
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
        _narrow_app(self.bootstrap_config).include_router(self.build_fastapi_health_check_router())


@dataclasses.dataclass(kw_only=True)
class FastAPIOpenTelemetryInstrument(OpenTelemetryInstrument):
    bootstrap_config: FastAPIConfig

    def bootstrap(self) -> None:
        super().bootstrap()
        FastAPIInstrumentor.instrument_app(
            app=_narrow_app(self.bootstrap_config),
            tracer_provider=get_tracer_provider(),
            excluded_urls=",".join(self._build_excluded_urls()),
        )

    def teardown(self) -> None:
        FastAPIInstrumentor.uninstrument_app(_narrow_app(self.bootstrap_config))
        super().teardown()


@dataclasses.dataclass(kw_only=True)
class FastAPIPrometheusInstrument(PrometheusInstrument):
    bootstrap_config: FastAPIConfig
    missing_dependency_message = "prometheus_fastapi_instrumentator is not installed"

    @staticmethod
    def check_dependencies() -> bool:
        return import_checker.is_prometheus_fastapi_instrumentator_installed

    def bootstrap(self) -> None:
        application = _narrow_app(self.bootstrap_config)
        Instrumentator(**self.bootstrap_config.prometheus_instrumentator_params).instrument(
            application,
            **self.bootstrap_config.prometheus_instrument_params,
        ).expose(
            application,
            endpoint=self.bootstrap_config.prometheus_metrics_path,
            include_in_schema=self.bootstrap_config.prometheus_metrics_include_in_schema,
            **self.bootstrap_config.prometheus_expose_params,
        )


@dataclasses.dataclass(kw_only=True)
class FastAPISwaggerInstrument(SwaggerInstrument):
    bootstrap_config: FastAPIConfig

    def bootstrap(self) -> None:
        application = _narrow_app(self.bootstrap_config)
        if self.bootstrap_config.swagger_path != application.docs_url:
            warnings.warn(
                f"swagger_path differs from docs_url, {application.docs_url} will be used for docs path",
                stacklevel=2,
            )
        if self.bootstrap_config.swagger_offline_docs:
            enable_offline_docs(application, static_path=self.bootstrap_config.swagger_static_path)


class FastAPIBootstrapper(BaseBootstrapper["fastapi.FastAPI"]):
    __slots__ = "bootstrap_config", "instruments"

    instruments_types: typing.ClassVar = [
        FastAPICorsInstrument,
        FastAPIOpenTelemetryInstrument,
        PyroscopeInstrument,
        SentryInstrument,
        FastAPIHealthChecksInstrument,
        LoggingInstrument,
        FastAPIPrometheusInstrument,
        FastAPISwaggerInstrument,
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
        application = _narrow_app(self.bootstrap_config)
        self._attach_teardown_once(application, lambda: self._wrap_lifespan(application))

    def _wrap_lifespan(self, application: "fastapi.FastAPI") -> None:
        old_lifespan_manager = application.router.lifespan_context
        application.router.lifespan_context = _merge_lifespan_context(
            old_lifespan_manager,
            self.lifespan_manager,
        )

    def is_ready(self) -> bool:
        return import_checker.is_fastapi_installed

    def _prepare_application(self) -> "fastapi.FastAPI":
        return _narrow_app(self.bootstrap_config)
