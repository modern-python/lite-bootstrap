import contextlib
import dataclasses
import inspect
import json
import logging
import sys
import typing
import warnings
from collections.abc import Generator

import litestar
import pytest
import structlog
from litestar import status_codes
from litestar.config.app import AppConfig
from litestar.middleware.logging import LoggingMiddlewareConfig
from litestar.plugins import InitPluginProtocol
from litestar.plugins.opentelemetry import OpenTelemetryPlugin
from litestar.testing import TestClient
from litestar.types import Scope
from opentelemetry.metrics import get_meter_provider
from opentelemetry.sdk.metrics import MeterProvider as SDKMeterProvider
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, get_tracer_provider

from lite_bootstrap import LitestarBootstrapper, LitestarConfig, import_checker
from lite_bootstrap.bootstrappers import litestar_bootstrapper
from lite_bootstrap.bootstrappers.litestar_bootstrapper import (
    _LITESTAR_DEFAULT_REQUEST_MAX_BODY_SIZE,
    LitestarLoggingInstrument,
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
    async def get_item(item_id: int) -> dict[str, int]:
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
    async def _handler(user_id: int) -> dict[str, int]:
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


def test_build_litestar_route_details_from_scope_ignores_raw_path() -> None:
    scope = typing.cast("Scope", {"method": "POST", "path": "/fallback/path"})
    name, attrs = build_litestar_route_details_from_scope(scope)
    assert name == "POST"
    assert attrs == {}


def test_build_litestar_route_details_from_scope_no_path() -> None:
    scope = typing.cast("Scope", {"type": "lifespan"})
    name, attrs = build_litestar_route_details_from_scope(scope)
    assert name == "HTTP"
    assert attrs == {}


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
def _recorded_litestar_logs() -> Generator[list[str]]:
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
    with pytest.warns(UserWarning, match="litestar_logging_middleware_enabled") as caught:
        dataclasses.replace(litestar_config, litestar_logging_middleware_config=LoggingMiddlewareConfig())

    assert caught[0].filename == __file__


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

    try:
        application = first.bootstrap()

        with pytest.raises(ConfigurationError, match="LitestarBootstrapper"):
            second.bootstrap()

        with TestClient(app=application) as client:
            assert client.get(litestar_config.health_checks_path).status_code == status_codes.HTTP_200_OK
    finally:
        first.teardown()


def test_litestar_otel_excludes_infrastructure_paths_normalized_by_litestar(
    litestar_config: LitestarConfig,
) -> None:
    """REGRESSION #248: Litestar strips the trailing slash before the middleware sees the path.

    `health_checks_path="/custom-health/"` reaches `OpenTelemetryMiddleware` as
    `http://host/custom-health`, so an exclude entry carrying the slash never matched and the
    health check was traced anyway. The lookalike route guards the obvious over-correction:
    `ExcludeList` regex-searches unanchored, so a bare `/custom-health` prefix would also
    silence `/custom-healthy`.
    """

    @litestar.get("/custom-healthy")
    async def lookalike_handler() -> dict[str, str]:
        return {"status": "ok"}

    config = dataclasses.replace(litestar_config, application_config=AppConfig(route_handlers=[lookalike_handler]))
    application = LitestarBootstrapper(bootstrap_config=config).bootstrap()

    tracer_provider = get_tracer_provider()
    assert isinstance(tracer_provider, SDKTracerProvider)
    exporter = InMemorySpanExporter()
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))

    with TestClient(app=application) as client:
        assert client.get(config.health_checks_path).status_code == status_codes.HTTP_200_OK
        assert client.get(config.prometheus_metrics_path).status_code == status_codes.HTTP_200_OK
        assert client.get("/custom-healthy").status_code == status_codes.HTTP_200_OK

    span_names = [span.name for span in exporter.get_finished_spans()]
    assert "GET /custom-health" not in span_names
    assert "GET /custom-metrics" not in span_names
    assert "GET /custom-healthy" in span_names


def test_litestar_otel_keeps_caller_supplied_excluded_urls_as_regexes(litestar_config: LitestarConfig) -> None:
    """`opentelemetry_excluded_urls` entries are OpenTelemetry regexes, so anchoring must not touch them."""

    @litestar.get("/items/{item_id:int}")
    async def get_item(item_id: int) -> dict[str, int]:
        return {"item_id": item_id}

    config = dataclasses.replace(
        litestar_config,
        application_config=AppConfig(route_handlers=[get_item]),
        opentelemetry_excluded_urls=[r"/items/\d+$"],
    )
    application = LitestarBootstrapper(bootstrap_config=config).bootstrap()

    tracer_provider = get_tracer_provider()
    assert isinstance(tracer_provider, SDKTracerProvider)
    exporter = InMemorySpanExporter()
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))

    with TestClient(app=application) as client:
        assert client.get("/items/42").status_code == status_codes.HTTP_200_OK

    assert exporter.get_finished_spans() == ()


def _bootstrap_with_span_exporter(config: LitestarConfig) -> tuple[litestar.Litestar, InMemorySpanExporter]:
    application = LitestarBootstrapper(bootstrap_config=config).bootstrap()
    tracer_provider = get_tracer_provider()
    assert isinstance(tracer_provider, SDKTracerProvider)
    exporter = InMemorySpanExporter()
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))
    return application, exporter


def _server_spans(exporter: InMemorySpanExporter) -> list[ReadableSpan]:
    return [span for span in exporter.get_finished_spans() if span.kind == SpanKind.SERVER]


def test_litestar_otel_registers_litestars_own_plugin(litestar_config: LitestarConfig) -> None:
    config = dataclasses.replace(litestar_config, opentelemetry_metrics_endpoint="localhost:4317")
    bootstrapper = LitestarBootstrapper(bootstrap_config=config)

    try:
        bootstrapper.bootstrap()

        plugins = [plugin for plugin in config.application_config.plugins if isinstance(plugin, OpenTelemetryPlugin)]
        assert len(plugins) == 1
        assert plugins[0].config.tracer_provider is get_tracer_provider()
        assert plugins[0].config.meter_provider is get_meter_provider()
        assert isinstance(get_meter_provider(), SDKMeterProvider)
    finally:
        bootstrapper.teardown()


def test_litestar_otel_keeps_user_plugins(litestar_config: LitestarConfig) -> None:
    class UserPlugin(InitPluginProtocol):
        def on_app_init(self, app_config: AppConfig) -> AppConfig:
            return app_config

    config = dataclasses.replace(litestar_config, application_config=AppConfig(plugins=[UserPlugin()]))
    application = LitestarBootstrapper(bootstrap_config=config).bootstrap()

    assert any(isinstance(plugin, UserPlugin) for plugin in application.plugins.init)
    assert any(isinstance(plugin, OpenTelemetryPlugin) for plugin in application.plugins.init)


def test_litestar_otel_span_carries_route_template(litestar_config: LitestarConfig) -> None:
    @litestar.get("/users/{user_id:int}")
    async def get_user(user_id: int) -> dict[str, int]:
        return {"user_id": user_id}

    config = dataclasses.replace(litestar_config, application_config=AppConfig(route_handlers=[get_user]))
    application, exporter = _bootstrap_with_span_exporter(config)

    with TestClient(app=application) as client:
        assert client.get("/users/123").status_code == status_codes.HTTP_200_OK

    server_spans = _server_spans(exporter)
    assert [span.name for span in server_spans] == ["GET /users/{user_id}"]
    assert server_spans[0].attributes is not None
    assert server_spans[0].attributes["http.route"] == "/users/{user_id}"


def test_litestar_otel_unmatched_path_span_is_named_by_method_only(litestar_config: LitestarConfig) -> None:
    """A 404 never reaches the route stack, so its span must not carry the raw path that scanners vary."""
    application, exporter = _bootstrap_with_span_exporter(litestar_config)

    with TestClient(app=application) as client:
        assert client.get("/missing/abc").status_code == status_codes.HTTP_404_NOT_FOUND

    server_spans = _server_spans(exporter)
    assert [span.name for span in server_spans] == ["GET"]
    assert server_spans[0].attributes is not None
    assert "http.route" not in server_spans[0].attributes


def test_litestar_otel_honors_excluded_urls_from_environment(
    litestar_config: LitestarConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OTEL_PYTHON_LITESTAR_EXCLUDED_URLS", "/from-env")

    @litestar.get("/from-env")
    async def from_env() -> None: ...

    @litestar.get("/other")
    async def other() -> None: ...

    config = dataclasses.replace(litestar_config, application_config=AppConfig(route_handlers=[from_env, other]))
    application, exporter = _bootstrap_with_span_exporter(config)

    with TestClient(app=application) as client:
        client.get("/from-env")
        client.get("/other")

    assert [span.name for span in _server_spans(exporter)] == ["GET /other"]


def test_litestar_otel_traces_everything_when_nothing_is_excluded(litestar_config: LitestarConfig) -> None:
    """An empty exclude list compiles to a pattern matching every path, so it must never reach the plugin."""

    @litestar.get("/traced")
    async def traced() -> None: ...

    config = dataclasses.replace(
        litestar_config,
        application_config=AppConfig(route_handlers=[traced]),
        prometheus_metrics_path="",
        opentelemetry_generate_health_check_spans=True,
    )
    application, exporter = _bootstrap_with_span_exporter(config)

    with TestClient(app=application) as client:
        client.get("/traced")

    assert [span.name for span in _server_spans(exporter)] == ["GET /traced"]


def test_litestar_otel_is_skipped_without_litestars_opentelemetry_plugin(litestar_config: LitestarConfig) -> None:
    """Litestar below 2.22 has no `litestar.plugins.opentelemetry`; that must skip the instrument, not crash."""
    with emulate_package_missing_with_module_reload(
        "litestar.plugins.opentelemetry",
        ["lite_bootstrap.bootstrappers.litestar_bootstrapper"],
    ):
        with pytest.warns(UserWarning, match=r"litestar>=2\.22"):
            bootstrapper = litestar_bootstrapper.LitestarBootstrapper(bootstrap_config=litestar_config)
        bootstrapper.bootstrap()

        assert "OpenTelemetryPlugin" not in {
            type(plugin).__name__ for plugin in litestar_config.application_config.plugins
        }
