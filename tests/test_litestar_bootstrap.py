import contextlib
import dataclasses
import gc
import inspect
import json
import logging
import sys
import typing
import warnings
import weakref

import litestar
import pytest
import structlog
from litestar import status_codes
from litestar.config.app import AppConfig
from litestar.middleware.logging import LoggingMiddlewareConfig
from litestar.params import FromPath
from litestar.testing import TestClient
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import get_tracer_provider

from lite_bootstrap import LitestarBootstrapper, LitestarConfig, import_checker
from lite_bootstrap.bootstrappers.litestar_bootstrapper import (
    _LITESTAR_DEFAULT_REQUEST_MAX_BODY_SIZE,
    LitestarLoggingInstrument,
    LitestarOpenTelemetryInstrumentationMiddleware,
    build_litestar_route_details_from_scope,
    build_span_name,
)
from lite_bootstrap.exceptions import ConfigurationError
from tests.conftest import (
    CustomInstrumentor,
    SentryTestTransport,
    emulate_package_missing,
    emulate_package_missing_with_module_reload,
)


logger = structlog.getLogger(__name__)


@pytest.fixture
def litestar_config() -> LitestarConfig:
    return LitestarConfig(
        service_name="microservice",
        service_version="2.0.0",
        service_environment="test",
        service_debug=False,
        cors_allowed_origins=["http://test"],
        health_checks_path="/custom-health/",
        opentelemetry_instrumentors=[CustomInstrumentor()],
        opentelemetry_log_traces=True,
        opentelemetry_generate_health_check_spans=False,
        prometheus_metrics_path="/custom-metrics/",
        sentry_dsn="https://testdsn@localhost/1",
        sentry_additional_params={"transport": SentryTestTransport()},
        swagger_offline_docs=True,
        logging_buffer_capacity=0,
    )


def test_second_litestar_bootstrapper_on_same_config_warns_not_stacks(litestar_config: LitestarConfig) -> None:
    config_a = litestar_config
    LitestarBootstrapper(bootstrap_config=config_a)
    on_shutdown_after_first = len(config_a.application_config.on_shutdown)

    config_b = dataclasses.replace(litestar_config)  # shares the same application_config
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        LitestarBootstrapper(bootstrap_config=config_b)

    matching = [w for w in caught if "already has a lite-bootstrap teardown hook" in str(w.message)]
    assert matching, "expected warning about existing lite-bootstrap teardown hook"
    assert "cannot be used" in str(matching[0].message)
    assert "bootstrap() will raise" in str(matching[0].message)
    assert len(config_a.application_config.on_shutdown) == on_shutdown_after_first, (
        "second bootstrapper must not stack another on_shutdown teardown"
    )


def test_litestar_bootstrap(litestar_config: LitestarConfig) -> None:
    bootstrapper = LitestarBootstrapper(bootstrap_config=litestar_config)
    application = bootstrapper.bootstrap()
    assert bootstrapper.is_bootstrapped
    logger.info("testing logging", key="value")
    assert application.cors_config
    assert application.cors_config.allow_origins == litestar_config.cors_allowed_origins

    with TestClient(app=application) as test_client:
        response = test_client.get(litestar_config.health_checks_path)
        assert response.status_code == status_codes.HTTP_200_OK
        assert response.json() == {
            "health_status": True,
            "service_name": "microservice",
            "service_version": "2.0.0",
        }

        response = test_client.get(litestar_config.prometheus_metrics_path)
        assert response.status_code == status_codes.HTTP_200_OK
        assert response.text

        response = test_client.get(litestar_config.swagger_path)
        assert response.status_code == status_codes.HTTP_200_OK
        response = test_client.get(f"{litestar_config.swagger_static_path}/swagger-ui.css")
        assert response.status_code == status_codes.HTTP_200_OK

    assert not bootstrapper.is_bootstrapped


def test_litestar_bootstrapper_not_ready() -> None:
    with emulate_package_missing("litestar"), pytest.raises(RuntimeError, match="litestar is not installed"):
        LitestarBootstrapper(bootstrap_config=LitestarConfig())


@pytest.mark.parametrize(
    "package_name",
    [
        "opentelemetry",
        "sentry_sdk",
        "structlog",
        "prometheus_client",
    ],
)
def test_litestar_bootstrapper_with_missing_instrument_dependency(
    litestar_config: LitestarConfig, package_name: str
) -> None:
    with emulate_package_missing(package_name), pytest.warns(UserWarning, match=package_name):
        LitestarBootstrapper(bootstrap_config=litestar_config)


def test_litestar_otel_span_naming(litestar_config: LitestarConfig) -> None:
    @litestar.get("/items/{item_id:int}")
    async def get_item(item_id: FromPath[int]) -> dict[str, int]:
        return {"item_id": item_id}

    config = dataclasses.replace(litestar_config, application_config=AppConfig(route_handlers=[get_item]))
    bootstrapper = LitestarBootstrapper(bootstrap_config=config)
    application = bootstrapper.bootstrap()

    tracer_provider = get_tracer_provider()
    assert isinstance(tracer_provider, SDKTracerProvider)
    exporter = InMemorySpanExporter()
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))

    with TestClient(app=application) as client:
        response = client.get("/items/42")
        assert response.status_code == status_codes.HTTP_200_OK

    spans = exporter.get_finished_spans()
    span_names = [s.name for s in spans]
    assert any("GET /items/{item_id}" in name for name in span_names)


def test_litestar_request_logger(litestar_config: LitestarConfig) -> None:
    @litestar.get("/log-test")
    async def log_handler(request: litestar.Request) -> dict[str, str]:
        request.logger.info("test log from handler", key="value")
        return {"status": "ok"}

    config = dataclasses.replace(litestar_config, application_config=AppConfig(route_handlers=[log_handler]))
    bootstrapper = LitestarBootstrapper(bootstrap_config=config)
    application = bootstrapper.bootstrap()

    with TestClient(app=application) as client:
        response = client.get("/log-test")
        assert response.status_code == status_codes.HTTP_200_OK
        assert response.json() == {"status": "ok"}


def _scrape_prometheus_path_labels(config: LitestarConfig, handler_path: str, request_path: str) -> str:
    @litestar.get(handler_path)
    async def _handler(user_id: FromPath[int]) -> dict[str, int]:
        return {"user_id": user_id}

    config = dataclasses.replace(config, application_config=AppConfig(route_handlers=[_handler]))
    application = LitestarBootstrapper(bootstrap_config=config).bootstrap()
    with TestClient(app=application) as client:
        client.get(request_path)
        return client.get(config.prometheus_metrics_path).text


def test_litestar_prometheus_group_path_default_uses_route_template(litestar_config: LitestarConfig) -> None:
    # Default prometheus_group_path=True keeps the path label bounded to the route template,
    # so parameterized routes cannot explode metric cardinality.
    metrics = _scrape_prometheus_path_labels(litestar_config, "/gp-default/{user_id:int}", "/gp-default/1")
    assert "/gp-default/{user_id}" in metrics
    assert "/gp-default/1" not in metrics


def test_litestar_prometheus_group_path_false_records_raw_path(litestar_config: LitestarConfig) -> None:
    config = dataclasses.replace(litestar_config, prometheus_group_path=False)
    metrics = _scrape_prometheus_path_labels(config, "/gp-false/{user_id:int}", "/gp-false/7")
    assert "/gp-false/7" in metrics


def test_litestar_prometheus_additional_params_override_group_path(litestar_config: LitestarConfig) -> None:
    # prometheus_additional_params wins over the prometheus_group_path default, without a kwarg collision.
    config = dataclasses.replace(litestar_config, prometheus_additional_params={"group_path": False})
    metrics = _scrape_prometheus_path_labels(config, "/gp-override/{user_id:int}", "/gp-override/9")
    assert "/gp-override/9" in metrics


def test_build_span_name_no_route() -> None:
    assert build_span_name("GET", "") == "GET"


def test_build_litestar_route_details_from_scope_path_fallback() -> None:
    scope = {"method": "POST", "path": "/fallback/path"}
    name, attrs = build_litestar_route_details_from_scope(scope)
    assert name == "POST /fallback/path"
    assert attrs == {"http.route": "/fallback/path"}


def test_build_litestar_route_details_from_scope_no_path() -> None:
    scope = {"type": "lifespan"}
    name, attrs = build_litestar_route_details_from_scope(scope)
    assert name == "HTTP"
    assert attrs == {}


class _NotWeakrefable:
    __slots__ = ()

    async def __call__(self, scope: object, receive: object, send: object) -> None:  # noqa: ARG002
        return None


async def test_litestar_otel_apps_cache_skips_non_weakrefable_app() -> None:
    """Apps that don't support weak references are called but not cached."""
    tracer_provider = TracerProvider()
    middleware = LitestarOpenTelemetryInstrumentationMiddleware(
        tracer_provider=tracer_provider,
        excluded_urls=set(),
    )

    non_weakrefable_app = _NotWeakrefable()
    # Confirm the key really is non-weakrefable so the test is meaningful.
    with pytest.raises(TypeError):
        weakref.ref(non_weakrefable_app)

    # Call handle() twice with the non-weakrefable next_app. Both calls must succeed
    # (TypeError suppressed on both lookup and store) and the cache stays empty.
    scope: dict = {"type": "lifespan"}
    await middleware.handle(scope, object(), object(), non_weakrefable_app)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
    await middleware.handle(scope, object(), object(), non_weakrefable_app)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]

    assert len(middleware._otel_apps) == 0  # noqa: SLF001


def test_litestar_otel_apps_cache_evicts_dead_refs() -> None:
    tracer_provider = TracerProvider()
    middleware = LitestarOpenTelemetryInstrumentationMiddleware(
        tracer_provider=tracer_provider,
        excluded_urls=set(),
    )

    async def transient_app(scope: dict, receive: object, send: object) -> None:  # noqa: ARG001
        return None  # pragma: no cover

    weak_app = weakref.ref(transient_app)
    middleware._otel_apps[transient_app] = "marker"  # noqa: SLF001  # ty: ignore[invalid-assignment]
    assert weak_app() is not None
    assert len(middleware._otel_apps) == 1  # noqa: SLF001

    del transient_app
    gc.collect()

    assert weak_app() is None
    assert len(middleware._otel_apps) == 0  # noqa: SLF001


def test_litestar_bootstrap_without_prometheus_client() -> None:
    # Regression: `import lite_bootstrap` with the `litestar` extra but not
    # prometheus_client crashed because litestar_bootstrapper imported
    # `litestar.plugins.prometheus` (which imports prometheus_client) under the
    # is_litestar_installed guard alone. Evict the cached litestar.plugins.prometheus
    # submodules so the module reload re-runs the real import path (otherwise the
    # cached submodule short-circuits it and the bug is masked).
    prom_submodules = [name for name in list(sys.modules) if name.startswith("litestar.plugins.prometheus")]
    saved = {name: sys.modules.pop(name) for name in prom_submodules}
    try:
        with emulate_package_missing_with_module_reload(
            "prometheus_client",
            ["lite_bootstrap.bootstrappers.litestar_bootstrapper"],
        ):
            assert import_checker.is_prometheus_client_installed is False
    finally:
        sys.modules.update(saved)


class _RecordingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


@contextlib.contextmanager
def _recorded_litestar_logs() -> typing.Iterator[list[str]]:
    """Record Litestar's rendered log lines.

    Enter this inside the TestClient context: Litestar's StructLoggingConfig runs dictConfig at
    startup, which drops handlers attached earlier, and MemoryLoggerFactory sets propagate=False,
    so the handler has to sit on the "litestar" logger itself.
    """
    handler = _RecordingHandler()
    litestar_logger = logging.getLogger("litestar")
    litestar_logger.addHandler(handler)
    try:
        yield handler.lines
    finally:
        litestar_logger.removeHandler(handler)


def _access_log_records(log_lines: list[str]) -> list[dict[str, typing.Any]]:
    """Return the LoggingMiddleware lines among the recorded structlog lines."""
    records = [json.loads(log_line) for log_line in log_lines]
    return [record for record in records if record.get("event") in {"HTTP Request", "HTTP Response"}]


def _post_password(config: LitestarConfig) -> list[str]:
    """Bootstrap, POST credentials, and return the log lines Litestar emitted for that request."""

    @litestar.post("/login")
    async def _login_handler(data: dict[str, str]) -> dict[str, str]:
        return data

    config = dataclasses.replace(config, application_config=AppConfig(route_handlers=[_login_handler]))
    application = LitestarBootstrapper(bootstrap_config=config).bootstrap()
    with TestClient(app=application) as client, _recorded_litestar_logs() as log_lines:
        response = client.post("/login", json={"username": "user", "password": "hunter2"})
        assert response.status_code == status_codes.HTTP_201_CREATED
    return log_lines


def test_litestar_access_logging_disabled_by_default(litestar_config: LitestarConfig) -> None:
    log_lines = _post_password(litestar_config)

    assert _access_log_records(log_lines) == []
    assert not any("hunter2" in log_line for log_line in log_lines)


def test_litestar_access_logging_opt_in_emits_access_logs(litestar_config: LitestarConfig) -> None:
    log_lines = _post_password(dataclasses.replace(litestar_config, litestar_logging_middleware_enabled=True))

    events = [record["event"] for record in _access_log_records(log_lines)]
    assert "HTTP Request" in events
    assert "HTTP Response" in events


def test_litestar_access_logging_logs_metadata_only(litestar_config: LitestarConfig) -> None:
    log_lines = _post_password(dataclasses.replace(litestar_config, litestar_logging_middleware_enabled=True))

    assert not any("hunter2" in log_line for log_line in log_lines)
    records = _access_log_records(log_lines)
    assert records
    for record in records:
        assert not {"body", "headers", "cookies", "query"} & record.keys()
    request_records = [record for record in records if record["event"] == "HTTP Request"]
    assert request_records
    assert request_records[0]["path"] == "/login"
    assert request_records[0]["method"] == "POST"


def test_litestar_access_logging_excludes_infrastructure_paths(litestar_config: LitestarConfig) -> None:
    config = dataclasses.replace(litestar_config, litestar_logging_middleware_enabled=True)
    application = LitestarBootstrapper(bootstrap_config=config).bootstrap()

    with TestClient(app=application) as client, _recorded_litestar_logs() as log_lines:
        assert client.get(config.swagger_path).status_code == status_codes.HTTP_200_OK
        assert client.get(f"{config.swagger_static_path}/swagger-ui.css").status_code == status_codes.HTTP_200_OK
        assert client.get(config.health_checks_path).status_code == status_codes.HTTP_200_OK
        assert client.get(config.prometheus_metrics_path).status_code == status_codes.HTTP_200_OK

    assert _access_log_records(log_lines) == []


def test_litestar_access_logging_keeps_lookalike_paths(litestar_config: LitestarConfig) -> None:
    @litestar.get("/custom-healthy")
    async def lookalike_handler() -> dict[str, str]:
        return {"status": "ok"}

    config = dataclasses.replace(
        litestar_config,
        litestar_logging_middleware_enabled=True,
        application_config=AppConfig(route_handlers=[lookalike_handler]),
    )
    application = LitestarBootstrapper(bootstrap_config=config).bootstrap()

    with TestClient(app=application) as client, _recorded_litestar_logs() as log_lines:
        assert client.get("/custom-healthy").status_code == status_codes.HTTP_200_OK

    request_records = [record for record in _access_log_records(log_lines) if record["event"] == "HTTP Request"]
    assert [record["path"] for record in request_records] == ["/custom-healthy"]


def test_litestar_access_logging_custom_config_replaces_defaults(litestar_config: LitestarConfig) -> None:
    custom_config = LoggingMiddlewareConfig(
        request_log_fields=("path", "query"),
        response_log_fields=("status_code",),
    )
    log_lines = _post_password(
        dataclasses.replace(
            litestar_config,
            litestar_logging_middleware_enabled=True,
            litestar_logging_middleware_config=custom_config,
        )
    )

    request_records = [record for record in _access_log_records(log_lines) if record["event"] == "HTTP Request"]
    assert request_records
    assert "query" in request_records[0]
    assert "method" not in request_records[0]


def test_litestar_logging_middleware_config_without_flag_warns(litestar_config: LitestarConfig) -> None:
    with pytest.warns(UserWarning, match="litestar_logging_middleware_enabled"):
        dataclasses.replace(litestar_config, litestar_logging_middleware_config=LoggingMiddlewareConfig())


def test_litestar_access_logging_excluded_paths_drops_degenerate_and_duplicates(
    litestar_config: LitestarConfig,
) -> None:
    # swagger_path is empty (dropped), swagger_static_path is a bare "/" (degenerate, dropped even
    # though swagger_offline_docs is on), and prometheus_metrics_path duplicates health_checks_path
    # once both are stripped of trailing slashes.
    config = dataclasses.replace(
        litestar_config,
        swagger_path="",
        swagger_offline_docs=True,
        swagger_static_path="/",
        health_checks_path="/api/",
        prometheus_metrics_path="/api",
    )
    instrument = LitestarLoggingInstrument(bootstrap_config=config)

    excluded_paths = instrument._build_logging_middleware_excluded_paths()  # noqa: SLF001

    assert excluded_paths == [r"^/api(?:/|$)"]
    middleware_config = instrument._build_logging_middleware_config()  # noqa: SLF001
    assert middleware_config.exclude == excluded_paths


def test_litestar_access_logging_excluded_paths_none_when_all_degenerate(
    litestar_config: LitestarConfig,
) -> None:
    config = dataclasses.replace(
        litestar_config,
        swagger_path="",
        swagger_offline_docs=True,
        swagger_static_path="/",
        health_checks_path="/",
        prometheus_metrics_path="",
    )
    instrument = LitestarLoggingInstrument(bootstrap_config=config)

    assert instrument._build_logging_middleware_excluded_paths() == []  # noqa: SLF001
    assert instrument._build_logging_middleware_config().exclude is None  # noqa: SLF001


def test_litestar_bootstrap_fills_unset_request_max_body_size(litestar_config: LitestarConfig) -> None:
    @litestar.post("/echo")
    async def echo_handler(data: dict[str, str]) -> dict[str, str]:
        return data

    config = dataclasses.replace(litestar_config, application_config=AppConfig(route_handlers=[echo_handler]))
    application = LitestarBootstrapper(bootstrap_config=config).bootstrap()

    with TestClient(app=application) as client:
        response = client.post("/echo", json={"key": "value"})

    assert response.status_code == status_codes.HTTP_201_CREATED
    assert response.json() == {"key": "value"}
    assert application.request_max_body_size == _LITESTAR_DEFAULT_REQUEST_MAX_BODY_SIZE


def test_litestar_bootstrap_keeps_explicit_request_max_body_size(litestar_config: LitestarConfig) -> None:
    explicit_max_body_size = 42

    @litestar.post("/echo")
    async def echo_handler(data: dict[str, str]) -> dict[str, str]:
        return data  # pragma: no cover -- body exceeds the limit before this runs

    config = dataclasses.replace(
        litestar_config,
        application_config=AppConfig(route_handlers=[echo_handler], request_max_body_size=explicit_max_body_size),
    )
    application = LitestarBootstrapper(bootstrap_config=config).bootstrap()

    with TestClient(app=application) as client:
        response = client.post("/echo", json={"key": "value" * explicit_max_body_size})

    assert response.status_code == status_codes.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    assert application.request_max_body_size == explicit_max_body_size


def test_litestar_bootstrap_keeps_explicit_unlimited_request_max_body_size(litestar_config: LitestarConfig) -> None:
    config = dataclasses.replace(litestar_config, application_config=AppConfig(request_max_body_size=None))
    application = LitestarBootstrapper(bootstrap_config=config).bootstrap()

    with TestClient(app=application):
        assert application.request_max_body_size is None


def test_litestar_default_request_max_body_size_matches_litestar() -> None:
    """Guard: our constant must stay equal to the default Litestar's own __init__ applies."""
    litestar_default = inspect.signature(litestar.Litestar.__init__).parameters["request_max_body_size"].default

    assert litestar_default == _LITESTAR_DEFAULT_REQUEST_MAX_BODY_SIZE


def test_second_litestar_bootstrapper_bootstrap_raises(litestar_config: LitestarConfig) -> None:
    first = LitestarBootstrapper(bootstrap_config=litestar_config)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        second = LitestarBootstrapper(bootstrap_config=dataclasses.replace(litestar_config))

    application = first.bootstrap()

    with pytest.raises(ConfigurationError, match="LitestarBootstrapper"):
        second.bootstrap()

    with TestClient(app=application) as client:
        assert client.get(litestar_config.health_checks_path).status_code == status_codes.HTTP_200_OK
