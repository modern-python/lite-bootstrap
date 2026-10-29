import asyncio
import dataclasses
import json
import logging
import typing
from collections.abc import Mapping, Sequence

from lite_bootstrap import import_checker
from lite_bootstrap.bootstrappers.base import BaseBootstrapper
from lite_bootstrap.helpers.warn import warn_at_caller
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
    from opentelemetry.metrics import Meter, MeterProvider, get_meter_provider
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

    # A constructed instance is passed to broker.add_middleware, which expects a
    # faststream BrokerMiddleware — a builder callable. Declared with Any to keep
    # lite-bootstrap decoupled from faststream's internal middleware types.
    def __call__(self, msg: typing.Any, /, *, context: typing.Any) -> typing.Any: ...  # noqa: ANN401


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

    # See FastStreamTelemetryMiddlewareProtocol.__call__.
    def __call__(self, msg: typing.Any, /, *, context: typing.Any) -> typing.Any: ...  # noqa: ANN401


_MiddlewareT = typing.TypeVar("_MiddlewareT")


def _middleware_targets(
    brokers: Sequence[typing.Any],
    configured: "type[_MiddlewareT] | Mapping[type, type[_MiddlewareT]]",
    field_name: str,
) -> list[tuple[typing.Any, "type[_MiddlewareT]"]]:
    by_broker_type = configured if isinstance(configured, Mapping) else {type(brokers[0]): configured}
    targets: list[tuple[typing.Any, type[_MiddlewareT]]] = []
    skipped: dict[str, None] = {}
    for broker in brokers:
        middleware_cls = next(
            (by_broker_type[one] for one in type(broker).__mro__ if one in by_broker_type),
            None,
        )
        if middleware_cls is None:
            skipped[repr(type(broker).__name__)] = None
        else:
            targets.append((broker, middleware_cls))
    if skipped:
        warn_at_caller(
            f"FastStream brokers {', '.join(skipped)} are not instrumented: {field_name} has no middleware "
            "class for their type. Pass a mapping from broker class to middleware class to cover them."
        )
    return targets


def _make_asgi_faststream() -> "AsgiFastStream":
    return AsgiFastStream()


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class FastStreamConfig(
    HealthChecksConfig, LoggingConfig, OpenTelemetryConfig, PrometheusConfig, PyroscopeConfig, SentryConfig
):
    application: "AsgiFastStream" = dataclasses.field(default_factory=_make_asgi_faststream)
    opentelemetry_middleware_cls: (
        type[FastStreamTelemetryMiddlewareProtocol] | Mapping[type, type[FastStreamTelemetryMiddlewareProtocol]] | None
    ) = None
    prometheus_middleware_cls: (
        type[FastStreamPrometheusMiddlewareProtocol]
        | Mapping[type, type[FastStreamPrometheusMiddlewareProtocol]]
        | None
    ) = None
    prometheus_metrics_path: str = ""
    prometheus_collector_registry: "prometheus_client.CollectorRegistry | None" = None
    faststream_log_level: int = logging.WARNING
    faststream_health_check_broker_timeout: float = 5.0


@dataclasses.dataclass(kw_only=True, slots=True)
class FastStreamHealthChecksInstrument(HealthChecksInstrument[FastStreamConfig]):
    def bootstrap(self) -> None:
        config = self.bootstrap_config

        @handle_get
        async def check_health(_: object) -> "AsgiResponse":
            health_status = await self.define_health_status()
            return AsgiResponse(
                json.dumps(self.render_health_check_data(health_status=health_status)).encode(),
                200 if health_status else 503,
                headers={"content-type": "application/json"},
            )

        if config.opentelemetry_generate_health_check_spans and import_checker.is_opentelemetry_installed:
            check_health = tracer.start_as_current_span(f"GET {config.health_checks_path}")(check_health)

        config.application.mount(config.health_checks_path, check_health)

    async def _define_framework_health_status(self) -> bool:
        config = self.bootstrap_config
        if not config.application or not config.application.brokers:
            return False

        timeout = config.faststream_health_check_broker_timeout
        results = await asyncio.gather(*(broker.ping(timeout=timeout) for broker in config.application.brokers))
        return all(results)


@dataclasses.dataclass(kw_only=True)
class FastStreamLoggingInstrument(LoggingInstrument[FastStreamConfig]):
    _prior_broker_params_storages: list[tuple[typing.Any, typing.Any]] = dataclasses.field(
        default_factory=list, init=False, repr=False, compare=False
    )
    _prior_faststream_handlers: list[logging.Handler] | None = dataclasses.field(
        default=None, init=False, repr=False, compare=False
    )

    def bootstrap(self) -> None:
        super().bootstrap()
        brokers = self.bootstrap_config.application.brokers
        if brokers and import_checker.is_structlog_installed and import_checker.is_faststream_installed:
            faststream_stdlib_logger = logging.getLogger("faststream")
            self._prior_faststream_handlers = faststream_stdlib_logger.handlers
            faststream_stdlib_logger.handlers = []
            logger = structlog.get_logger("faststream")
            logger.setLevel(self.bootstrap_config.faststream_log_level)
            for broker in brokers:
                self._prior_broker_params_storages.append((broker, broker.config.logger.params_storage))
                broker.config.logger.params_storage = ManualLoggerStorage(logger)

    def teardown(self) -> None:
        try:
            while self._prior_broker_params_storages:
                broker, prior_storage = self._prior_broker_params_storages.pop()
                broker.config.logger.params_storage = prior_storage
        finally:
            try:
                super().teardown()
            finally:
                if self._prior_faststream_handlers is not None:
                    logging.getLogger("faststream").handlers = self._prior_faststream_handlers
                    self._prior_faststream_handlers = None


@dataclasses.dataclass(kw_only=True)
class FastStreamOpenTelemetryInstrument(OpenTelemetryInstrument[FastStreamConfig]):
    def bootstrap(self) -> None:
        super().bootstrap()
        config = self.bootstrap_config
        if config.opentelemetry_middleware_cls and config.application.brokers:
            for broker, middleware_cls in _middleware_targets(
                config.application.brokers, config.opentelemetry_middleware_cls, "opentelemetry_middleware_cls"
            ):
                broker.add_middleware(
                    middleware_cls(tracer_provider=get_tracer_provider(), meter_provider=get_meter_provider())
                )


@dataclasses.dataclass(kw_only=True)
class FastStreamPrometheusInstrument(PrometheusInstrument[FastStreamConfig]):
    collector_registry: "prometheus_client.CollectorRegistry" = dataclasses.field(init=False)
    missing_dependency_message = "prometheus_client is not installed"

    def __post_init__(self) -> None:
        injected = self.bootstrap_config.prometheus_collector_registry
        self.collector_registry = injected if injected is not None else prometheus_client.REGISTRY

    @staticmethod
    def dependencies_installed() -> bool:
        return import_checker.is_prometheus_client_installed

    def bootstrap(self) -> None:
        config = self.bootstrap_config
        config.application.mount(
            config.prometheus_metrics_path, prometheus_client.make_asgi_app(self.collector_registry)
        )
        if config.prometheus_middleware_cls and config.application.brokers:
            for broker, middleware_cls in _middleware_targets(
                config.application.brokers, config.prometheus_middleware_cls, "prometheus_middleware_cls"
            ):
                broker.add_middleware(middleware_cls(registry=self.collector_registry))


class FastStreamBootstrapper(BaseBootstrapper["AsgiFastStream", FastStreamConfig]):
    __slots__ = "bootstrap_config", "instruments"

    instruments_types: typing.ClassVar = [
        FastStreamOpenTelemetryInstrument,
        PyroscopeInstrument,
        SentryInstrument,
        FastStreamHealthChecksInstrument,
        FastStreamLoggingInstrument,
        FastStreamPrometheusInstrument,
    ]
    not_ready_message = "faststream is not installed"

    def is_ready(self) -> bool:
        return import_checker.is_faststream_installed

    def __init__(self, bootstrap_config: FastStreamConfig) -> None:
        super().__init__(bootstrap_config)
        application = self.bootstrap_config.application
        self._attach_teardown_once(application, lambda: application.on_shutdown(self.teardown))

    def _prepare_application(self) -> "AsgiFastStream":
        return self.bootstrap_config.application
