from __future__ import annotations
import contextlib
import dataclasses
import json
import typing

from lite_bootstrap.bootstrappers.base import BaseBootstrapper
from lite_bootstrap.instruments.healthchecks_instrument import HealthChecksConfig, HealthChecksInstrument
from lite_bootstrap.instruments.logging_instrument import LoggingConfig, LoggingInstrument
from lite_bootstrap.instruments.opentelemetry_instrument import OpentelemetryConfig, OpenTelemetryInstrument
from lite_bootstrap.instruments.prometheus_instrument import PrometheusConfig, PrometheusInstrument
from lite_bootstrap.instruments.sentry_instrument import SentryConfig, SentryInstrument


with contextlib.suppress(ImportError):
    import faststream
    import prometheus_client
    from faststream.asgi import AsgiFastStream, AsgiResponse
    from faststream.asgi import get as handle_get
    from faststream.broker.core.usecase import BrokerUsecase
    from opentelemetry.metrics import Meter, MeterProvider
    from opentelemetry.trace import TracerProvider, get_tracer_provider


@typing.runtime_checkable
class FastStreamTelemetryMiddlewareProtocol(typing.Protocol):
    def __init__(
        self,
        *,
        tracer_provider: TracerProvider | None = None,
        meter_provider: MeterProvider | None = None,
        meter: Meter | None = None,
    ) -> None: ...
    def __call__(self, msg: typing.Any | None) -> faststream.BaseMiddleware: ...  # noqa: ANN401


@typing.runtime_checkable
class FastStreamPrometheusMiddlewareProtocol(typing.Protocol):
    def __init__(
        self,
        *,
        registry: prometheus_client.CollectorRegistry,
        app_name: str = ...,
        metrics_prefix: str = "faststream",
        received_messages_size_buckets: typing.Sequence[float] | None = None,
    ) -> None: ...
    def __call__(self, msg: typing.Any | None) -> faststream.BaseMiddleware: ...  # noqa: ANN401


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class FastStreamConfig(HealthChecksConfig, LoggingConfig, OpentelemetryConfig, PrometheusConfig, SentryConfig):
    application: AsgiFastStream = dataclasses.field(default_factory=AsgiFastStream)
    broker: BrokerUsecase[typing.Any, typing.Any] | None = None
    opentelemetry_middleware_cls: type[FastStreamTelemetryMiddlewareProtocol] | None = None
    prometheus_middleware_cls: type[FastStreamPrometheusMiddlewareProtocol] | None = None


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class FastStreamHealthChecksInstrument(HealthChecksInstrument):
    bootstrap_config: FastStreamConfig

    def bootstrap(self) -> None:
        @handle_get
        async def check_health(_: object) -> AsgiResponse:
            return (
                AsgiResponse(
                    json.dumps(self.render_health_check_data()).encode(), 200, headers={"content-type": "text/plain"}
                )
                if await self._define_health_status()
                else AsgiResponse(b"Service is unhealthy", 500, headers={"content-type": "application/json"})
            )

        self.bootstrap_config.application.mount(self.bootstrap_config.health_checks_path, check_health)

    async def _define_health_status(self) -> bool:
        if not self.bootstrap_config.application or not self.bootstrap_config.application.broker:
            return False

        return await self.bootstrap_config.application.broker.ping(timeout=5)


@dataclasses.dataclass(kw_only=True, frozen=True)
class FastStreamLoggingInstrument(LoggingInstrument):
    bootstrap_config: FastStreamConfig


@dataclasses.dataclass(kw_only=True, frozen=True)
class FastStreamOpenTelemetryInstrument(OpenTelemetryInstrument):
    bootstrap_config: FastStreamConfig

    def is_ready(self) -> bool:
        return bool(self.bootstrap_config.opentelemetry_middleware_cls and super().is_ready())

    def bootstrap(self) -> None:
        if self.bootstrap_config.opentelemetry_middleware_cls and self.bootstrap_config.application.broker:
            self.bootstrap_config.application.broker.add_middleware(
                self.bootstrap_config.opentelemetry_middleware_cls(tracer_provider=get_tracer_provider())
            )


@dataclasses.dataclass(kw_only=True, frozen=True)
class FastStreamSentryInstrument(SentryInstrument):
    bootstrap_config: FastStreamConfig


@dataclasses.dataclass(kw_only=True, frozen=True)
class FastStreamPrometheusInstrument(PrometheusInstrument):
    bootstrap_config: FastStreamConfig
    collector_registry: prometheus_client.CollectorRegistry = dataclasses.field(
        default_factory=prometheus_client.CollectorRegistry, init=False
    )

    def is_ready(self) -> bool:
        return bool(self.bootstrap_config.prometheus_middleware_cls and super().is_ready())

    def bootstrap(self) -> None:
        self.bootstrap_config.application.mount(
            self.bootstrap_config.prometheus_metrics_path, prometheus_client.make_asgi_app(self.collector_registry)
        )
        if self.bootstrap_config.prometheus_middleware_cls and self.bootstrap_config.application.broker:
            self.bootstrap_config.application.broker.add_middleware(
                self.bootstrap_config.prometheus_middleware_cls(registry=self.collector_registry)
            )


class FastStreamBootstrapper(BaseBootstrapper[AsgiFastStream]):
    instruments_types: typing.ClassVar = [
        FastStreamOpenTelemetryInstrument,
        FastStreamSentryInstrument,
        FastStreamHealthChecksInstrument,
        FastStreamLoggingInstrument,
        FastStreamPrometheusInstrument,
    ]
    bootstrap_config: FastStreamConfig
    __slots__ = "bootstrap_config", "instruments"

    def __init__(self, bootstrap_config: FastStreamConfig) -> None:
        super().__init__(bootstrap_config)
        if self.bootstrap_config.broker:
            self.bootstrap_config.application.broker = self.bootstrap_config.broker

    def _prepare_application(self) -> AsgiFastStream:
        return self.bootstrap_config.application
