import dataclasses
import logging
import logging.handlers
import sys
import typing
import uuid
import warnings
from unittest.mock import AsyncMock, patch

import faststream.asgi
import prometheus_client
import pytest
import structlog
from faststream._internal.broker import BrokerUsecase
from faststream._internal.logger.params_storage import ManualLoggerStorage
from faststream.redis import RedisBroker, TestRedisBroker
from faststream.redis.opentelemetry import RedisTelemetryMiddleware
from faststream.redis.prometheus import RedisPrometheusMiddleware
from opentelemetry.instrumentation.instrumentor import BaseInstrumentor
from opentelemetry.metrics import MeterProvider, get_meter_provider
from opentelemetry.sdk import resources
from opentelemetry.sdk.metrics import MeterProvider as SDKMeterProvider
from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import TracerProvider, get_tracer, get_tracer_provider
from starlette import status
from starlette.testclient import TestClient

from lite_bootstrap import FastStreamBootstrapper, FastStreamConfig
from lite_bootstrap.bootstrappers import faststream_bootstrapper
from lite_bootstrap.bootstrappers.faststream_bootstrapper import (
    FastStreamLoggingInstrument,
    FastStreamOpenTelemetryInstrument,
    FastStreamPrometheusInstrument,
)
from lite_bootstrap.exceptions import ConfigurationError
from lite_bootstrap.instruments.healthchecks_instrument import HealthProbe
from tests.conftest import (
    HEALTH_PROBE_CASES,
    CustomInstrumentor,
    SentryTestTransport,
    capture_probe_warnings,
    emulate_package_missing,
    emulate_package_missing_with_module_reload,
    failed_probe_names,
    passing_probe,
)


logger = structlog.getLogger(__name__)


@pytest.fixture
def broker() -> RedisBroker:
    return RedisBroker()


def build_faststream_config(
    broker: BrokerUsecase[typing.Any, typing.Any, typing.Any] | None = None,
) -> FastStreamConfig:
    asgi_kwargs: dict[str, typing.Any] = {
        "asyncapi_path": faststream.asgi.AsyncAPIRoute("/docs/"),
        "specification": faststream.AsyncAPI(),
    }
    application = (
        faststream.asgi.AsgiFastStream(broker, **asgi_kwargs)
        if broker is not None
        else faststream.asgi.AsgiFastStream(**asgi_kwargs)
    )
    return FastStreamConfig(
        service_name="microservice",
        service_version="2.0.0",
        service_environment="test",
        service_debug=False,
        opentelemetry_instrumentors=[CustomInstrumentor()],
        opentelemetry_log_traces=True,
        opentelemetry_middleware_cls=RedisTelemetryMiddleware,
        prometheus_metrics_path="/custom-metrics/",
        prometheus_middleware_cls=RedisPrometheusMiddleware,
        sentry_dsn="https://testdsn@localhost/1",
        sentry_additional_params={"transport": SentryTestTransport()},
        health_checks_path="/custom-health/",
        logging_buffer_capacity=0,
        application=application,
    )


def test_second_faststream_bootstrapper_on_same_app_warns(broker: RedisBroker) -> None:
    config_a = build_faststream_config(broker=broker)
    FastStreamBootstrapper(bootstrap_config=config_a)

    config_b = dataclasses.replace(config_a)  # shares the same application
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        FastStreamBootstrapper(bootstrap_config=config_b)

    matching = [w for w in caught if "already has a lite-bootstrap teardown hook" in str(w.message)]
    assert matching, "expected warning about existing lite-bootstrap teardown hook"


async def test_faststream_bootstrap(broker: RedisBroker) -> None:
    bootstrap_config = build_faststream_config(broker=broker)
    bootstrapper = FastStreamBootstrapper(bootstrap_config=bootstrap_config)
    application = bootstrapper.bootstrap()
    assert bootstrapper.is_bootstrapped
    logger.info("testing logging", key="value")

    with TestClient(app=application) as test_client:
        async with TestRedisBroker(broker):
            response = test_client.get(bootstrap_config.health_checks_path)
            assert response.status_code == status.HTTP_200_OK
            assert response.json() == {
                "health_status": True,
                "service_name": "microservice",
                "service_version": "2.0.0",
            }

            response = test_client.get(bootstrap_config.prometheus_metrics_path)
            assert response.status_code == status.HTTP_200_OK

            response = test_client.get("/docs/")
            assert response.status_code == status.HTTP_200_OK

    assert not bootstrapper.is_bootstrapped


async def test_faststream_bootstrap_health_check_wo_broker() -> None:
    bootstrap_config = build_faststream_config()
    bootstrapper = FastStreamBootstrapper(bootstrap_config=bootstrap_config)
    application = bootstrapper.bootstrap()
    test_client = TestClient(app=application)

    response = test_client.get(bootstrap_config.health_checks_path)
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert response.json() == {
        "health_status": False,
        "service_name": "microservice",
        "service_version": "2.0.0",
    }
    bootstrapper.teardown()


def test_faststream_logging_instrument_injects_structlog_logger(broker: RedisBroker) -> None:
    bootstrap_config = FastStreamConfig(
        service_debug=False,
        logging_buffer_capacity=0,
        logging_log_level=logging.INFO,
        faststream_log_level=logging.WARNING,
        application=faststream.asgi.AsgiFastStream(broker),
    )
    bootstrapper = FastStreamBootstrapper(bootstrap_config=bootstrap_config)
    bootstrapper.bootstrap()
    try:
        assert isinstance(broker.config.logger.params_storage, ManualLoggerStorage)
        assert logging.getLogger("faststream").level == logging.WARNING
    finally:
        bootstrapper.teardown()


def test_faststream_logging_replaces_faststream_stderr_handler(broker: RedisBroker) -> None:
    faststream_logger = logging.getLogger("faststream")
    original_handlers = faststream_logger.handlers[:]
    bootstrapper = FastStreamBootstrapper(
        bootstrap_config=FastStreamConfig(
            logging_buffer_capacity=0,
            faststream_log_level=logging.INFO,
            application=faststream.asgi.AsgiFastStream(broker),
        )
    )
    bootstrapper.bootstrap()
    try:
        assert not [one for one in faststream_logger.handlers if getattr(one, "stream", None) is sys.stderr]
        assert [type(one) for one in faststream_logger.handlers].count(logging.handlers.MemoryHandler) == 1
    finally:
        bootstrapper.teardown()

    assert faststream_logger.handlers == original_handlers


def test_faststream_config_default_application() -> None:
    config = FastStreamConfig()
    assert isinstance(config.application, faststream.asgi.AsgiFastStream)


def test_faststream_bootstrapper_not_ready() -> None:
    with emulate_package_missing("faststream"), pytest.raises(RuntimeError, match="faststream is not installed"):
        FastStreamBootstrapper(bootstrap_config=FastStreamConfig(application=faststream.asgi.AsgiFastStream()))


@pytest.mark.parametrize(
    "package_name",
    [
        "opentelemetry",
        "sentry_sdk",
        "structlog",
        "prometheus_client",
    ],
)
def test_faststream_bootstrapper_with_missing_instrument_dependency(broker: RedisBroker, package_name: str) -> None:
    bootstrap_config = build_faststream_config(broker=broker)
    with emulate_package_missing(package_name), pytest.warns(UserWarning, match=package_name):
        FastStreamBootstrapper(bootstrap_config=bootstrap_config)


def test_faststream_bootstrap_without_prometheus_client(broker: RedisBroker) -> None:
    # Regression: issue #87 bug 1 — FastStreamPrometheusInstrument's
    # default_factory called prometheus_client.CollectorRegistry() during
    # dataclass __init__, raising NameError before dependencies_installed() ran.
    bootstrap_config = build_faststream_config(broker=broker)
    with emulate_package_missing_with_module_reload(
        "prometheus_client",
        ["lite_bootstrap.bootstrappers.faststream_bootstrapper"],
    ):
        with pytest.warns(UserWarning, match="prometheus_client"):
            bootstrapper = FastStreamBootstrapper(bootstrap_config=bootstrap_config)
        bootstrapper.bootstrap()


def _span_names_for_one_health_check(config: FastStreamConfig) -> list[str]:
    bootstrapper = FastStreamBootstrapper(bootstrap_config=config)
    # The module's tracer stays bound to the first provider a test installed; this one resolves to this test's.
    with patch.object(faststream_bootstrapper, "tracer", get_tracer(__name__)):
        application = bootstrapper.bootstrap()
    tracer_provider = get_tracer_provider()
    assert isinstance(tracer_provider, SDKTracerProvider)
    exporter = InMemorySpanExporter()
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))
    try:
        TestClient(app=application).get(config.health_checks_path)
    finally:
        bootstrapper.teardown()
    return [span.name for span in exporter.get_finished_spans()]


def test_faststream_health_check_records_no_span_by_default() -> None:
    assert _span_names_for_one_health_check(build_faststream_config()) == []


def test_faststream_health_check_span_is_recorded_when_turned_on() -> None:
    config = dataclasses.replace(build_faststream_config(), opentelemetry_generate_health_check_spans=True)

    assert _span_names_for_one_health_check(config) == [f"GET {config.health_checks_path}"]


def test_faststream_bootstrap_without_opentelemetry(broker: RedisBroker) -> None:
    # Regression: issue #87 bug 2 — FastStreamHealthChecksInstrument.bootstrap
    # referenced unbound `tracer` when opentelemetry was absent and
    # opentelemetry_generate_health_check_spans defaulted to True.
    bootstrap_config = dataclasses.replace(
        build_faststream_config(broker=broker), opentelemetry_generate_health_check_spans=True
    )
    with emulate_package_missing_with_module_reload(
        "opentelemetry",
        ["lite_bootstrap.bootstrappers.faststream_bootstrapper"],
    ):
        with pytest.warns(UserWarning, match="opentelemetry"):
            bootstrapper = FastStreamBootstrapper(bootstrap_config=bootstrap_config)
        bootstrapper.bootstrap()


def test_faststream_teardown_restores_broker_params_storage(broker: RedisBroker) -> None:
    config = build_faststream_config(broker=broker)
    original_storage = broker.config.logger.params_storage
    bootstrapper = FastStreamBootstrapper(bootstrap_config=config)
    bootstrapper.bootstrap()
    assert isinstance(broker.config.logger.params_storage, ManualLoggerStorage)
    assert broker.config.logger.params_storage is not original_storage

    bootstrapper.teardown()

    assert broker.config.logger.params_storage is original_storage


async def test_faststream_health_check_uses_configured_broker_timeout(broker: RedisBroker) -> None:
    expected_timeout = 12.5
    config = dataclasses.replace(
        build_faststream_config(broker=broker),
        faststream_health_check_broker_timeout=expected_timeout,
    )
    bootstrapper = FastStreamBootstrapper(bootstrap_config=config)
    application = bootstrapper.bootstrap()
    try:
        with (
            patch.object(broker, "ping", new=AsyncMock(return_value=True)) as mock_ping,
            TestClient(app=application) as test_client,
        ):
            response = test_client.get(config.health_checks_path)
            assert response.status_code == status.HTTP_200_OK
        mock_ping.assert_called_once_with(timeout=expected_timeout)
    finally:
        bootstrapper.teardown()


async def test_faststream_health_check_fails_when_second_broker_is_down(broker: RedisBroker) -> None:
    second_broker = RedisBroker()
    config = build_faststream_config(broker=broker)
    config.application.add_broker(second_broker)
    bootstrapper = FastStreamBootstrapper(bootstrap_config=config)
    application = bootstrapper.bootstrap()
    try:
        with (
            patch.object(broker, "ping", new=AsyncMock(return_value=True)),
            patch.object(second_broker, "ping", new=AsyncMock(return_value=False)),
            TestClient(app=application) as test_client,
        ):
            response = test_client.get(config.health_checks_path)
            assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
            assert response.json()["health_status"] is False
    finally:
        bootstrapper.teardown()


async def test_faststream_health_check_pings_every_broker(broker: RedisBroker) -> None:
    expected_timeout = 3.0
    second_broker = RedisBroker()
    config = dataclasses.replace(
        build_faststream_config(broker=broker),
        faststream_health_check_broker_timeout=expected_timeout,
    )
    config.application.add_broker(second_broker)
    bootstrapper = FastStreamBootstrapper(bootstrap_config=config)
    application = bootstrapper.bootstrap()
    try:
        with (
            patch.object(broker, "ping", new=AsyncMock(return_value=True)) as first_ping,
            patch.object(second_broker, "ping", new=AsyncMock(return_value=True)) as second_ping,
            TestClient(app=application) as test_client,
        ):
            response = test_client.get(config.health_checks_path)
            assert response.status_code == status.HTTP_200_OK
        first_ping.assert_called_once_with(timeout=expected_timeout)
        second_ping.assert_called_once_with(timeout=expected_timeout)
    finally:
        bootstrapper.teardown()


def test_faststream_opentelemetry_excluded_urls_in_built_set(broker: RedisBroker) -> None:
    bootstrap_config = dataclasses.replace(
        build_faststream_config(broker=broker),
        opentelemetry_excluded_urls=["/foo", "/bar"],
    )
    instrument = FastStreamOpenTelemetryInstrument(bootstrap_config=bootstrap_config)
    excluded = instrument._build_excluded_urls()  # noqa: SLF001
    assert "/foo" in excluded
    assert "/bar" in excluded


def test_faststream_build_excluded_urls_covers_prometheus_and_health_paths(broker: RedisBroker) -> None:
    # Pins the genuine cross-instrument reads in _build_excluded_urls: a rename of
    # prometheus_metrics_path / health_checks_path (or a regression in the health
    # conditional) breaks this loudly instead of silently dropping the exclusion.
    config_no_health_spans = dataclasses.replace(
        build_faststream_config(broker=broker),
        opentelemetry_generate_health_check_spans=False,
    )
    excluded = FastStreamOpenTelemetryInstrument(bootstrap_config=config_no_health_spans)._build_excluded_urls()  # noqa: SLF001
    assert config_no_health_spans.prometheus_metrics_path in excluded  # always excluded
    assert config_no_health_spans.health_checks_path in excluded  # excluded when health spans are off

    config_with_health_spans = dataclasses.replace(
        build_faststream_config(broker=broker), opentelemetry_generate_health_check_spans=True
    )
    excluded_with = FastStreamOpenTelemetryInstrument(bootstrap_config=config_with_health_spans)._build_excluded_urls()  # noqa: SLF001
    assert config_with_health_spans.prometheus_metrics_path in excluded_with
    assert config_with_health_spans.health_checks_path not in excluded_with  # kept when health spans are on


@pytest.mark.parametrize(
    "middleware_cls", [RedisPrometheusMiddleware, None], ids=["with_middleware", "without_middleware"]
)
async def test_faststream_prometheus_uses_injected_registry(broker: RedisBroker, middleware_cls: type | None) -> None:
    custom_registry = prometheus_client.CollectorRegistry()
    counter_name = f"injected_counter_{uuid.uuid4().hex}_total"
    counter = prometheus_client.Counter(counter_name, "Injected registry counter", registry=custom_registry)
    counter.inc()

    bootstrap_config = dataclasses.replace(
        build_faststream_config(broker=broker),
        prometheus_middleware_cls=middleware_cls,
        prometheus_collector_registry=custom_registry,
    )
    bootstrapper = FastStreamBootstrapper(bootstrap_config=bootstrap_config)
    application = bootstrapper.bootstrap()
    try:
        with TestClient(app=application) as test_client:
            async with TestRedisBroker(broker):
                response = test_client.get(bootstrap_config.prometheus_metrics_path)
                assert response.status_code == status.HTTP_200_OK
                assert counter_name.encode() in response.content
    finally:
        bootstrapper.teardown()


def test_faststream_prometheus_is_skipped_without_metrics_path(broker: RedisBroker) -> None:
    bootstrap_config = FastStreamConfig(
        application=faststream.asgi.AsgiFastStream(broker),
        prometheus_middleware_cls=RedisPrometheusMiddleware,
        logging_buffer_capacity=0,
    )
    bootstrapper = FastStreamBootstrapper(bootstrap_config=bootstrap_config)
    skipped = dict(bootstrapper.skipped_instruments)
    assert skipped[FastStreamPrometheusInstrument] == "prometheus_metrics_path is empty or not valid"


async def test_faststream_prometheus_serves_the_default_registry(broker: RedisBroker) -> None:
    counter_name = f"default_registry_counter_{uuid.uuid4().hex}_total"
    counter = prometheus_client.Counter(counter_name, "Default registry counter")
    counter.inc()
    bootstrap_config = dataclasses.replace(
        build_faststream_config(broker=broker), prometheus_middleware_cls=None, prometheus_collector_registry=None
    )
    bootstrapper = FastStreamBootstrapper(bootstrap_config=bootstrap_config)
    application = bootstrapper.bootstrap()
    try:
        instruments = [one for one in bootstrapper.instruments if isinstance(one, FastStreamPrometheusInstrument)]
        assert [one.collector_registry for one in instruments] == [prometheus_client.REGISTRY]
        with TestClient(app=application) as test_client:
            async with TestRedisBroker(broker):
                response = test_client.get(bootstrap_config.prometheus_metrics_path)
                assert response.status_code == status.HTTP_200_OK
                assert counter_name.encode() in response.content
                assert b"python_info" in response.content
    finally:
        bootstrapper.teardown()
        prometheus_client.REGISTRY.unregister(counter)


def test_faststream_default_registry_takes_two_brokers_and_a_second_bootstrap() -> None:
    for _ in range(2):
        brokers: list[BrokerUsecase[typing.Any, typing.Any, typing.Any]] = [RedisBroker(), RedisBroker()]
        bootstrapper = _bootstrap_with_brokers(
            brokers, opentelemetry_log_traces=False, opentelemetry_middleware_cls=None
        )
        try:
            for one in brokers:
                assert _middleware_types(one) == [RedisPrometheusMiddleware]
        finally:
            bootstrapper.teardown()


def test_faststream_logging_teardown_runs_super_when_broker_write_raises(
    broker: RedisBroker, monkeypatch: pytest.MonkeyPatch
) -> None:
    bootstrap_config = build_faststream_config(broker=broker)
    instrument = FastStreamLoggingInstrument(bootstrap_config=bootstrap_config)
    instrument.bootstrap()

    def _raise_on_write(_self: object, _value: object) -> None:
        msg = "broker write boom"
        raise RuntimeError(msg)

    monkeypatch.setattr(type(broker.config.logger), "params_storage", property(fset=_raise_on_write), raising=False)

    # super().teardown() still runs (LoggingInstrument's structlog reset); broker write raises last.
    with pytest.raises(RuntimeError, match="broker write boom"):
        instrument.teardown()
    # If super().teardown() ran, structlog defaults were reset — no exception below.
    structlog.get_logger("verify-reset")


def test_faststream_bootstrap_after_teardown_raises() -> None:
    bootstrapper = FastStreamBootstrapper(bootstrap_config=FastStreamConfig())
    bootstrapper.bootstrap()
    bootstrapper.teardown()
    with pytest.raises(ConfigurationError, match="construct a new FastStreamBootstrapper"):
        bootstrapper.bootstrap()


def test_second_faststream_bootstrapper_bootstrap_raises(broker: RedisBroker) -> None:
    config_a = build_faststream_config(broker=broker)
    first = FastStreamBootstrapper(bootstrap_config=config_a)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        second = FastStreamBootstrapper(bootstrap_config=dataclasses.replace(config_a))

    try:
        first.bootstrap()
        with pytest.raises(ConfigurationError, match="FastStreamBootstrapper"):
            second.bootstrap()
    finally:
        first.teardown()


def test_faststream_bootstrap_builds_its_own_tracer_provider(broker: RedisBroker) -> None:
    bootstrapper = FastStreamBootstrapper(bootstrap_config=build_faststream_config(broker=broker))
    bootstrapper.bootstrap()
    try:
        instruments = [one for one in bootstrapper.instruments if isinstance(one, FastStreamOpenTelemetryInstrument)]
        assert len(instruments) == 1
        tracer_provider = instruments[0]._tracer_provider  # noqa: SLF001
        assert tracer_provider is not None
        assert tracer_provider.resource.attributes[resources.SERVICE_NAME] == "microservice"
    finally:
        bootstrapper.teardown()


@pytest.mark.parametrize(
    "middleware_cls", [RedisTelemetryMiddleware, None], ids=["with_middleware", "without_middleware"]
)
def test_faststream_bootstrap_applies_opentelemetry_instrumentors(
    broker: RedisBroker,
    middleware_cls: type | None,
) -> None:
    recorded_tracer_providers: list[object] = []

    class RecordingInstrumentor(BaseInstrumentor):
        def instrumentation_dependencies(self) -> typing.Collection[str]:
            return []

        def _instrument(self, **kwargs: object) -> None:
            recorded_tracer_providers.append(kwargs["tracer_provider"])

        def _uninstrument(self, **_kwargs: object) -> None: ...

    bootstrap_config = dataclasses.replace(
        build_faststream_config(broker=broker),
        opentelemetry_middleware_cls=middleware_cls,
        opentelemetry_instrumentors=[RecordingInstrumentor()],
    )
    bootstrapper = FastStreamBootstrapper(bootstrap_config=bootstrap_config)
    bootstrapper.bootstrap()
    try:
        instruments = [one for one in bootstrapper.instruments if isinstance(one, FastStreamOpenTelemetryInstrument)]
        assert len(instruments) == 1
        assert instruments[0]._tracer_provider is not None  # noqa: SLF001
        assert recorded_tracer_providers == [instruments[0]._tracer_provider]  # noqa: SLF001
    finally:
        bootstrapper.teardown()


async def test_faststream_otel_hands_the_middleware_the_meter_provider(broker: RedisBroker) -> None:
    """FastStream's telemetry middleware declares meter_provider and was being handed nothing."""
    recorded: dict[str, object] = {}

    class RecordingTelemetryMiddleware(RedisTelemetryMiddleware):
        def __init__(
            self, *, tracer_provider: "TracerProvider | None" = None, meter_provider: "MeterProvider | None" = None
        ) -> None:
            recorded["tracer_provider"] = tracer_provider
            recorded["meter_provider"] = meter_provider
            super().__init__(tracer_provider=tracer_provider, meter_provider=meter_provider)

    bootstrap_config = dataclasses.replace(
        build_faststream_config(broker=broker),
        opentelemetry_metrics_endpoint="localhost:4317",
        opentelemetry_middleware_cls=RecordingTelemetryMiddleware,
    )
    bootstrapper = FastStreamBootstrapper(bootstrap_config=bootstrap_config)
    try:
        bootstrapper.bootstrap()

        assert recorded["meter_provider"] is get_meter_provider()
        assert isinstance(get_meter_provider(), SDKMeterProvider)
    finally:
        bootstrapper.teardown()


@pytest.mark.parametrize(("probes", "expected_status", "expected_health_status", "expected_failed"), HEALTH_PROBE_CASES)
async def test_faststream_health_check_runs_probes(
    broker: RedisBroker,
    probes: dict[str, HealthProbe],
    expected_status: int,
    expected_health_status: bool,
    expected_failed: list[str],
) -> None:
    config = dataclasses.replace(build_faststream_config(broker=broker), health_checks_probes=probes)
    bootstrapper = FastStreamBootstrapper(bootstrap_config=config)
    application = bootstrapper.bootstrap()
    try:
        with (
            patch.object(broker, "ping", new=AsyncMock(return_value=True)),
            capture_probe_warnings() as probe_warnings,
            TestClient(app=application) as test_client,
        ):
            response = test_client.get(config.health_checks_path)
    finally:
        bootstrapper.teardown()

    assert response.status_code == expected_status
    assert response.json() == {
        "health_status": expected_health_status,
        "service_name": "microservice",
        "service_version": "2.0.0",
    }
    assert failed_probe_names(probe_warnings) == expected_failed


async def test_faststream_health_check_fails_on_broker_ping_despite_passing_probe(broker: RedisBroker) -> None:
    config = dataclasses.replace(build_faststream_config(broker=broker), health_checks_probes={"db": passing_probe})
    bootstrapper = FastStreamBootstrapper(bootstrap_config=config)
    application = bootstrapper.bootstrap()
    try:
        with (
            patch.object(broker, "ping", new=AsyncMock(return_value=False)),
            TestClient(app=application) as test_client,
        ):
            response = test_client.get(config.health_checks_path)
    finally:
        bootstrapper.teardown()

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert response.json()["health_status"] is False


class OtherRedisBroker(RedisBroker): ...


class OtherTelemetryMiddleware(RedisTelemetryMiddleware): ...


class OtherPrometheusMiddleware(RedisPrometheusMiddleware): ...


def _middleware_types(broker: BrokerUsecase[typing.Any, typing.Any, typing.Any]) -> list[type]:
    return [type(middleware) for middleware in broker.config.broker_middlewares]


def _bootstrap_with_brokers(
    brokers: list[BrokerUsecase[typing.Any, typing.Any, typing.Any]], **overrides: object
) -> FastStreamBootstrapper:
    config = dataclasses.replace(build_faststream_config(broker=brokers[0]), **overrides)
    for extra in brokers[1:]:
        config.application.add_broker(extra)
    bootstrapper = FastStreamBootstrapper(bootstrap_config=config)
    bootstrapper.bootstrap()
    return bootstrapper


def test_faststream_middlewares_are_added_to_every_broker(
    broker: RedisBroker, recwarn: pytest.WarningsRecorder
) -> None:
    second_broker = RedisBroker()
    bootstrapper = _bootstrap_with_brokers([broker, second_broker])
    try:
        for one in (broker, second_broker):
            assert _middleware_types(one) == [RedisTelemetryMiddleware, RedisPrometheusMiddleware]
        assert not [one for one in recwarn if "not instrumented" in str(one.message)]
    finally:
        bootstrapper.teardown()


def test_faststream_single_middleware_class_skips_brokers_of_another_type_with_a_warning(broker: RedisBroker) -> None:
    first_broker = OtherRedisBroker()
    with pytest.warns(UserWarning, match=r"not instrumented") as recorded:
        bootstrapper = _bootstrap_with_brokers(
            [first_broker, broker],
            opentelemetry_middleware_cls=OtherTelemetryMiddleware,
            prometheus_middleware_cls=OtherPrometheusMiddleware,
        )
    try:
        assert _middleware_types(first_broker) == [OtherTelemetryMiddleware, OtherPrometheusMiddleware]
        assert _middleware_types(broker) == []
        skipped_messages = [str(one.message) for one in recorded if "not instrumented" in str(one.message)]
        expected_warning_count = 2
        assert len(skipped_messages) == expected_warning_count
        assert all("'RedisBroker'" in message for message in skipped_messages)
    finally:
        bootstrapper.teardown()


def test_faststream_middleware_mapping_picks_the_most_specific_class_per_broker(broker: RedisBroker) -> None:
    other_broker = OtherRedisBroker()
    bootstrapper = _bootstrap_with_brokers(
        [broker, other_broker],
        opentelemetry_middleware_cls={
            RedisBroker: RedisTelemetryMiddleware,
            OtherRedisBroker: OtherTelemetryMiddleware,
        },
        prometheus_middleware_cls={
            RedisBroker: RedisPrometheusMiddleware,
            OtherRedisBroker: OtherPrometheusMiddleware,
        },
    )
    try:
        assert _middleware_types(broker) == [RedisTelemetryMiddleware, RedisPrometheusMiddleware]
        assert _middleware_types(other_broker) == [OtherTelemetryMiddleware, OtherPrometheusMiddleware]
    finally:
        bootstrapper.teardown()


def test_faststream_middleware_mapping_without_an_entry_skips_the_broker_with_a_warning(broker: RedisBroker) -> None:
    other_broker = OtherRedisBroker()
    with pytest.warns(UserWarning, match=r"'RedisBroker'.*not instrumented"):
        bootstrapper = _bootstrap_with_brokers(
            [other_broker, broker],
            opentelemetry_middleware_cls={OtherRedisBroker: OtherTelemetryMiddleware},
            prometheus_middleware_cls=None,
        )
    try:
        assert _middleware_types(other_broker) == [OtherTelemetryMiddleware]
        assert _middleware_types(broker) == []
    finally:
        bootstrapper.teardown()


def test_faststream_logging_covers_every_broker_and_teardown_restores_each(broker: RedisBroker) -> None:
    second_broker = RedisBroker()
    original_storages = [broker.config.logger.params_storage, second_broker.config.logger.params_storage]
    bootstrapper = _bootstrap_with_brokers([broker, second_broker])
    try:
        for one in (broker, second_broker):
            assert isinstance(one.config.logger.params_storage, ManualLoggerStorage)
    finally:
        bootstrapper.teardown()

    assert [broker.config.logger.params_storage, second_broker.config.logger.params_storage] == original_storages
