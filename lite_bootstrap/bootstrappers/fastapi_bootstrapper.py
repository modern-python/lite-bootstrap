import contextlib
import dataclasses
import typing

from prometheus_fastapi_instrumentator import Instrumentator

from lite_bootstrap.bootstrappers.base import BaseBootstrapper
from lite_bootstrap.instruments.healthchecks_instrument import (
    HealthChecksConfig,
    HealthChecksInstrument,
    HealthCheckTypedDict,
)
from lite_bootstrap.instruments.logging_instrument import LoggingConfig, LoggingInstrument
from lite_bootstrap.instruments.opentelemetry_instrument import OpentelemetryConfig, OpenTelemetryInstrument
from lite_bootstrap.instruments.prometheus_instrument import PrometheusConfig, PrometheusInstrument
from lite_bootstrap.instruments.sentry_instrument import SentryConfig, SentryInstrument


with contextlib.suppress(ImportError):
    import fastapi
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.trace import get_tracer_provider


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class FastAPIConfig(HealthChecksConfig, LoggingConfig, OpentelemetryConfig, PrometheusConfig, SentryConfig):
    application: fastapi.FastAPI = dataclasses.field(default_factory=fastapi.FastAPI)
    opentelemetry_excluded_urls: list[str] = dataclasses.field(default_factory=list)
    prometheus_instrumentator_params: dict[str, typing.Any] = dataclasses.field(default_factory=dict)
    prometheus_instrument_params: dict[str, typing.Any] = dataclasses.field(default_factory=dict)
    prometheus_expose_params: dict[str, typing.Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class FastAPIHealthChecksInstrument(HealthChecksInstrument):
    bootstrap_config: FastAPIConfig

    def build_fastapi_health_check_router(self) -> fastapi.APIRouter:
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

    def _build_excluded_urls(self) -> list[str]:
        excluded_urls = [*self.bootstrap_config.opentelemetry_excluded_urls]
        for one_url in (self.bootstrap_config.health_checks_path, self.bootstrap_config.prometheus_metrics_path):
            if one_url and one_url not in excluded_urls:
                excluded_urls.append(one_url)
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

    def bootstrap(self) -> None:
        Instrumentator(**self.bootstrap_config.prometheus_instrument_params).instrument(
            self.bootstrap_config.application,
            **self.bootstrap_config.prometheus_instrument_params,
        ).expose(
            self.bootstrap_config.application,
            endpoint=self.bootstrap_config.prometheus_metrics_path,
            include_in_schema=self.bootstrap_config.prometheus_metrics_include_in_schema,
            **self.bootstrap_config.prometheus_expose_params,
        )


class FastAPIBootstrapper(BaseBootstrapper[fastapi.FastAPI]):
    instruments_types: typing.ClassVar = [
        FastAPIOpenTelemetryInstrument,
        FastAPISentryInstrument,
        FastAPIHealthChecksInstrument,
        FastAPILoggingInstrument,
        FastAPIPrometheusInstrument,
    ]
    bootstrap_config: FastAPIConfig
    __slots__ = "bootstrap_config", "instruments"

    def __init__(self, bootstrap_config: FastAPIConfig) -> None:
        super().__init__(bootstrap_config)

    def _prepare_application(self) -> fastapi.FastAPI:
        return self.bootstrap_config.application
