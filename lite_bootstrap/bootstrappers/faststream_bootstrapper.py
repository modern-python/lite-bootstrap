import dataclasses
import json
import logging
import typing

from lite_bootstrap import import_checker
from lite_bootstrap.bootstrappers.base import BaseBootstrapper
from lite_bootstrap.instruments.healthchecks_instrument import HealthChecksConfig, HealthChecksInstrument
from lite_bootstrap.instruments.logging_instrument import LoggingConfig, LoggingInstrument
from lite_bootstrap.instruments.opentelemetry_instrument import OpenTelemetryConfig, OpenTelemetryInstrument
from lite_bootstrap.instruments.prometheus_instrument import PrometheusConfig, PrometheusInstrument
from lite_bootstrap.instruments.pyroscope_instrument import PyroscopeConfig, PyroscopeInstrument
from lite_bootstrap.instruments.sentry_instrument import SentryConfig, SentryInstrument


if import_checker.is_faststream_installed:
    from faststream._internal.logger.params_storage import ManualLoggerStorage
    from faststream.asgi import AsgiFastStream, AsgiResponse
    from faststream.asgi import get as handle_get

if import_checker.is_structlog_installed:
    import structlog

if import_checker.is_prometheus_client_installed:
    import prometheus_client

if import_checker.is_opentelemetry_installed:
    from opentelemetry import trace
    from opentelemetry.metrics import Meter, MeterProvider
    from opentelemetry.trace import TracerProvider, get_tracer_provider

    tracer: typing.Final = trace.get_tracer(__name__)


@typing.runtime_checkable
class FastStreamTelemetryMiddlewareProtocol(typing.Protocol):
    def __init__(
        self,
        *,
        tracer_provider: typing.Optional["TracerProvider"] = None,
        meter_provider: typing.Optional["MeterProvider"] = None,
        meter: typing.Optional["Meter"] = None,
        include_messages_counters: bool = True,
    ) -> None: ...


@typing.runtime_checkable
class FastStreamPrometheusMiddlewareProtocol(typing.Protocol):
    def __init__(
        self,
        *,
        registry: "prometheus_client.CollectorRegistry",
        app_name: str = ...,
        metrics_prefix: str = "faststream",
        received_messages_size_buckets: typing.Sequence[float] | None = None,
    ) -> None: ...


def _make_asgi_faststream() -> "AsgiFastStream":
    return AsgiFastStream()


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class FastStreamConfig(
    HealthChecksConfig, LoggingConfig, OpenTelemetryConfig, PrometheusConfig, PyroscopeConfig, SentryConfig
):
    application: "AsgiFastStream" = dataclasses.field(default_factory=_make_asgi_faststream)
    opentelemetry_middleware_cls: type[FastStreamTelemetryMiddlewareProtocol] | None = None
    opentelemetry_excluded_urls: list[str] = dataclasses.field(default_factory=list)
    prometheus_middleware_cls: type[FastStreamPrometheusMiddlewareProtocol] | None = None
    prometheus_collector_registry: "prometheus_client.CollectorRegistry | None" = None
    faststream_log_level: int = logging.WARNING
    faststream_health_check_broker_timeout: float = 5.0


@dataclasses.dataclass(kw_only=True, slots=True)
class FastStreamHealthChecksInstrument(HealthChecksInstrument):
    bootstrap_config: FastStreamConfig

    def bootstrap(self) -> None:
        @handle_get
        async def check_health(_: object) -> "AsgiResponse":
            return (
                AsgiResponse(
                    json.dumps(self.render_health_check_data()).encode(),
                    200,
                    headers={"content-type": "application/json"},
                )
                if await self._define_health_status()
                else AsgiResponse(b"Service is unhealthy", 500, headers={"content-type": "text/plain"})
            )

        if (
            self.bootstrap_config.opentelemetry_generate_health_check_spans
            and import_checker.is_opentelemetry_installed
        ):
            check_health = tracer.start_as_current_span(f"GET {self.bootstrap_config.health_checks_path}")(
                check_health,
            )

        self.bootstrap_config.application.mount(self.bootstrap_config.health_checks_path, check_health)

    async def _define_health_status(self) -> bool:
        if not self.bootstrap_config.application or not self.bootstrap_config.application.broker:
            return False

        return await self.bootstrap_config.application.broker.ping(
            timeout=self.bootstrap_config.faststream_health_check_broker_timeout,
        )


@dataclasses.dataclass(kw_only=True)
class FastStreamLoggingInstrument(LoggingInstrument):
    bootstrap_config: FastStreamConfig
    _prior_broker_params_storage: typing.Any = dataclasses.field(default=None, init=False, repr=False, compare=False)
    _broker_logger_replaced: bool = dataclasses.field(default=False, init=False, repr=False, compare=False)

    def bootstrap(self) -> None:
        super().bootstrap()
        broker = self.bootstrap_config.application.broker
        if broker is not None and import_checker.is_structlog_installed and import_checker.is_faststream_installed:
            logger = structlog.get_logger("faststream")
            logger.setLevel(self.bootstrap_config.faststream_log_level)
            self._prior_broker_params_storage = broker.config.logger.params_storage
            broker.config.logger.params_storage = ManualLoggerStorage(logger)
            self._broker_logger_replaced = True

    def teardown(self) -> None:
        try:
            if self._broker_logger_replaced:
                broker = self.bootstrap_config.application.broker
                if broker is not None:
                    broker.config.logger.params_storage = self._prior_broker_params_storage
                self._broker_logger_replaced = False
                self._prior_broker_params_storage = None
        finally:
            super().teardown()


@dataclasses.dataclass(kw_only=True)
class FastStreamOpenTelemetryInstrument(OpenTelemetryInstrument):
    bootstrap_config: FastStreamConfig
    not_ready_message = OpenTelemetryInstrument.not_ready_message + " or opentelemetry_middleware_cls is empty"

    @classmethod
    def is_configured(cls, bootstrap_config: "FastStreamConfig") -> bool:  # ty: ignore[invalid-method-override]
        return super().is_configured(bootstrap_config) and bool(bootstrap_config.opentelemetry_middleware_cls)

    def bootstrap(self) -> None:
        if self.bootstrap_config.opentelemetry_middleware_cls and self.bootstrap_config.application.broker:
            self.bootstrap_config.application.broker.add_middleware(
                self.bootstrap_config.opentelemetry_middleware_cls(tracer_provider=get_tracer_provider())
            )


def _make_collector_registry() -> "prometheus_client.CollectorRegistry":
    return prometheus_client.CollectorRegistry()


@dataclasses.dataclass(kw_only=True)
class FastStreamPrometheusInstrument(PrometheusInstrument):
    bootstrap_config: FastStreamConfig
    collector_registry: "prometheus_client.CollectorRegistry" = dataclasses.field(init=False)
    not_ready_message = PrometheusInstrument.not_ready_message + " or prometheus_middleware_cls is missing"
    missing_dependency_message = "prometheus_client is not installed"

    def __post_init__(self) -> None:
        injected = self.bootstrap_config.prometheus_collector_registry
        self.collector_registry = injected if injected is not None else _make_collector_registry()

    @classmethod
    def is_configured(cls, bootstrap_config: "FastStreamConfig") -> bool:  # ty: ignore[invalid-method-override]
        return super().is_configured(bootstrap_config) and bool(bootstrap_config.prometheus_middleware_cls)

    @staticmethod
    def check_dependencies() -> bool:
        return import_checker.is_prometheus_client_installed

    def bootstrap(self) -> None:
        self.bootstrap_config.application.mount(
            self.bootstrap_config.prometheus_metrics_path, prometheus_client.make_asgi_app(self.collector_registry)
        )
        if self.bootstrap_config.prometheus_middleware_cls and self.bootstrap_config.application.broker:
            self.bootstrap_config.application.broker.add_middleware(
                self.bootstrap_config.prometheus_middleware_cls(registry=self.collector_registry)
            )


class FastStreamBootstrapper(BaseBootstrapper["AsgiFastStream"]):
    __slots__ = "bootstrap_config", "instruments"

    instruments_types: typing.ClassVar = [
        FastStreamOpenTelemetryInstrument,
        PyroscopeInstrument,
        SentryInstrument,
        FastStreamHealthChecksInstrument,
        FastStreamLoggingInstrument,
        FastStreamPrometheusInstrument,
    ]
    bootstrap_config: FastStreamConfig
    not_ready_message = "faststream is not installed"

    def is_ready(self) -> bool:
        return import_checker.is_faststream_installed

    def __init__(self, bootstrap_config: FastStreamConfig) -> None:
        super().__init__(bootstrap_config)
        self.bootstrap_config.application.on_shutdown(self.teardown)

    def _prepare_application(self) -> "AsgiFastStream":
        return self.bootstrap_config.application
