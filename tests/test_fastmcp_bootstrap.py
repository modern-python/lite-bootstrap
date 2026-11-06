import contextlib
import typing
import uuid
import warnings
from collections.abc import AsyncGenerator, Generator
from unittest.mock import MagicMock

import prometheus_client
import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server import create_proxy
from fastmcp.server.context import Context
from fastmcp.server.http import StarletteWithLifespan
from fastmcp.server.middleware import MiddlewareContext
from fastmcp.server.providers.addressing import hash_tool, hashed_backend_name
from fastmcp.server.transforms.tool_transform import ToolTransform
from fastmcp.tools.tool_transform import ToolTransformConfig
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, get_tracer_provider
from starlette import status
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.testclient import TestClient

from lite_bootstrap import BootstrapperNotReadyError, FastMcpBootstrapper, FastMcpConfig
from lite_bootstrap.bootstrappers import fastmcp_bootstrapper
from lite_bootstrap.bootstrappers.fastmcp_bootstrapper import (
    FastMcpLoggingMiddleware,
    FastMcpOpenTelemetryInstrument,
    FastMcpPrometheusMiddleware,
    _postprocess_http_apps,
)
from lite_bootstrap.exceptions import ConfigurationError
from lite_bootstrap.helpers.opentelemetry_asgi import build_opentelemetry_middleware
from lite_bootstrap.instruments.healthchecks_instrument import HealthProbe
from tests.conftest import (
    HEALTH_PROBE_CASES,
    HTTP_METRIC_CASES,
    emulate_package_missing,
    emulate_package_missing_with_module_reload,
    in_memory_opentelemetry_metric_reader,
    opentelemetry_http_request_count,
    prometheus_request_count,
    unregister_prometheus_request_metrics,
)


def test_fastmcp_config_default_application() -> None:
    config = FastMcpConfig()
    assert isinstance(config.application, FastMCP)


def test_fastmcp_bootstrap_returns_same_application() -> None:
    config = FastMcpConfig(service_name="test-mcp", service_version="1.2.3")
    bootstrapper = FastMcpBootstrapper(bootstrap_config=config)
    application = bootstrapper.bootstrap()
    assert application is config.application
    bootstrapper.teardown()


def test_fastmcp_bootstrapper_not_ready() -> None:
    with (
        emulate_package_missing("fastmcp"),
        pytest.raises(BootstrapperNotReadyError, match="fastmcp is not installed"),
    ):
        FastMcpBootstrapper(bootstrap_config=FastMcpConfig())


def test_fastmcp_teardown_resets_is_bootstrapped() -> None:
    bootstrapper = FastMcpBootstrapper(bootstrap_config=FastMcpConfig())
    bootstrapper.bootstrap()
    assert bootstrapper.is_bootstrapped is True
    bootstrapper.teardown()
    assert bootstrapper.is_bootstrapped is False


async def _drive_asgi_lifespan(application: typing.Any) -> list[dict[str, typing.Any]]:  # noqa: ANN401
    inbox = [{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}]
    outbox: list[dict[str, typing.Any]] = []

    async def receive() -> dict[str, typing.Any]:
        return inbox.pop(0)

    async def send(message: dict[str, typing.Any]) -> None:
        outbox.append(message)

    await application({"type": "lifespan", "asgi": {"version": "3.0"}}, receive, send)
    return outbox


async def test_fastmcp_exports_user_shutdown_span_and_preserves_lifespan_result() -> None:
    @contextlib.asynccontextmanager
    async def lifespan(_app: FastMCP) -> AsyncGenerator[dict[str, str]]:
        yield {"service": "ready"}
        with get_tracer_provider().get_tracer(__name__).start_as_current_span("user-shutdown"):
            pass

    app = FastMCP(lifespan=lifespan)

    @app.tool
    def read_state(ctx: Context) -> str:
        return ctx.lifespan_context["service"]

    bootstrapper = FastMcpBootstrapper(
        bootstrap_config=FastMcpConfig(application=app, opentelemetry_log_traces=True),
    )
    application = bootstrapper.bootstrap()
    provider = get_tracer_provider()
    assert isinstance(provider, SDKTracerProvider)
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    async with Client(application) as client:
        assert (await client.call_tool("read_state")).data == "ready"

    assert "user-shutdown" in [span.name for span in exporter.get_finished_spans()]
    assert not bootstrapper.is_bootstrapped


async def test_fastmcp_teardown_runs_via_asgi_lifespan() -> None:
    bootstrapper = FastMcpBootstrapper(bootstrap_config=FastMcpConfig())
    application = bootstrapper.bootstrap()
    assert bootstrapper.is_bootstrapped

    sent = await _drive_asgi_lifespan(application.http_app())

    assert any(msg["type"] == "lifespan.startup.complete" for msg in sent)
    assert any(msg["type"] == "lifespan.shutdown.complete" for msg in sent)
    assert not bootstrapper.is_bootstrapped


async def test_fastmcp_logging_middleware_logs_success(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_logger = MagicMock()
    monkeypatch.setattr(
        "lite_bootstrap.bootstrappers.fastmcp_bootstrapper.fastmcp_access_logger",
        fake_logger,
    )
    middleware = FastMcpLoggingMiddleware()
    context = MiddlewareContext(
        message={"payload": "test"},
        method="tools/list",
        source="client",
        type="request",
    )

    async def call_next(received: MiddlewareContext[typing.Any]) -> dict[str, str]:
        assert received is context
        return {"status": "ok"}

    result = await middleware.on_message(context, call_next)

    assert result == {"status": "ok"}
    fake_logger.info.assert_called_once()
    call_kwargs = fake_logger.info.call_args
    assert call_kwargs.args[0] == "tools/list"
    assert call_kwargs.kwargs["mcp"] == {
        "method": "tools/list",
        "source": "client",
        "type": "request",
    }
    assert isinstance(call_kwargs.kwargs["duration"], int)


async def test_fastmcp_access_log_records_notifications(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_logger = MagicMock()
    monkeypatch.setattr(fastmcp_bootstrapper, "fastmcp_access_logger", fake_logger)
    bootstrapper = FastMcpBootstrapper(bootstrap_config=_make_test_config(logging_access_log_enabled=True))
    application = bootstrapper.bootstrap()
    try:
        async with Client(application, mode="legacy") as client:
            await client.list_tools()
    finally:
        bootstrapper.teardown()

    logged = [(call.kwargs["mcp"]["method"], call.kwargs["mcp"]["type"]) for call in fake_logger.info.call_args_list]
    assert logged == [
        ("initialize", "request"),
        ("notifications/initialized", "notification"),
        ("tools/list", "request"),
    ]


async def test_fastmcp_logging_middleware_logs_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_logger = MagicMock()
    monkeypatch.setattr(
        "lite_bootstrap.bootstrappers.fastmcp_bootstrapper.fastmcp_access_logger",
        fake_logger,
    )
    middleware = FastMcpLoggingMiddleware()
    context = MiddlewareContext(
        message={"payload": "test"},
        method="tools/call",
        source="client",
        type="request",
    )

    class CustomError(RuntimeError):
        pass

    error_message = "boom"

    async def call_next(_: MiddlewareContext[typing.Any]) -> None:
        raise CustomError(error_message)

    with pytest.raises(CustomError, match="boom"):
        await middleware.on_message(context, call_next)

    fake_logger.exception.assert_called_once()
    fake_logger.info.assert_not_called()


def _make_test_config(**overrides: typing.Any) -> FastMcpConfig:  # noqa: ANN401
    base: dict[str, typing.Any] = {
        "service_name": "test-mcp",
        "service_version": "1.2.3",
    }
    base.update(overrides)
    return FastMcpConfig(**base)


def test_fastmcp_health_check_route_serves_200_with_data() -> None:
    config = _make_test_config()
    bootstrapper = FastMcpBootstrapper(bootstrap_config=config)
    application = bootstrapper.bootstrap()
    try:
        with TestClient(application.http_app()) as test_client:
            response = test_client.get(config.health_checks_path)
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "health_status": True,
            "service_name": "test-mcp",
            "service_version": "1.2.3",
        }
    finally:
        bootstrapper.teardown()


def test_fastmcp_health_check_path_is_configurable() -> None:
    config = _make_test_config(health_checks_path="/healthz")
    bootstrapper = FastMcpBootstrapper(bootstrap_config=config)
    application = bootstrapper.bootstrap()
    try:
        with TestClient(application.http_app()) as test_client:
            response = test_client.get("/healthz")
            default_response = test_client.get("/health/")
        assert response.status_code == status.HTTP_200_OK
        assert default_response.status_code == status.HTTP_404_NOT_FOUND
    finally:
        bootstrapper.teardown()


def test_fastmcp_health_check_disabled_when_flag_false() -> None:
    config = _make_test_config(health_checks_enabled=False)
    bootstrapper = FastMcpBootstrapper(bootstrap_config=config)
    application = bootstrapper.bootstrap()
    try:
        with TestClient(application.http_app()) as test_client:
            response = test_client.get(config.health_checks_path)
        assert response.status_code == status.HTTP_404_NOT_FOUND
    finally:
        bootstrapper.teardown()


def test_fastmcp_prometheus_route_exposes_registered_metric() -> None:
    counter_name = f"fastmcp_plan_test_requests_{uuid.uuid4().hex}_total"
    counter = prometheus_client.Counter(counter_name, "FastMCP plan test counter.")
    counter.inc()

    config = _make_test_config()
    bootstrapper = FastMcpBootstrapper(bootstrap_config=config)
    application = bootstrapper.bootstrap()
    try:
        with TestClient(application.http_app()) as test_client:
            response = test_client.get(config.prometheus_metrics_path)
        assert response.status_code == status.HTTP_200_OK
        assert response.headers["content-type"].startswith(prometheus_client.CONTENT_TYPE_LATEST.split(";")[0])
        assert counter_name.encode() in response.content
    finally:
        bootstrapper.teardown()


def test_fastmcp_prometheus_path_is_configurable() -> None:
    config = _make_test_config(prometheus_metrics_path="/m")
    bootstrapper = FastMcpBootstrapper(bootstrap_config=config)
    application = bootstrapper.bootstrap()
    try:
        with TestClient(application.http_app()) as test_client:
            response = test_client.get("/m")
            default_response = test_client.get("/metrics")
        assert response.status_code == status.HTTP_200_OK
        assert default_response.status_code == status.HTTP_404_NOT_FOUND
    finally:
        bootstrapper.teardown()


def _find_mcp_logging_middleware(application: "FastMCP") -> list[FastMcpLoggingMiddleware]:
    return [m for m in application.middleware if isinstance(m, FastMcpLoggingMiddleware)]


def _mounted_logging_middleware(config: FastMcpConfig) -> list[FastMcpLoggingMiddleware]:
    bootstrapper = FastMcpBootstrapper(bootstrap_config=config)
    application = bootstrapper.bootstrap()
    try:
        return _find_mcp_logging_middleware(application)
    finally:
        bootstrapper.teardown()


def test_fastmcp_logging_middleware_is_not_mounted_by_default() -> None:
    assert _mounted_logging_middleware(_make_test_config()) == []


def test_fastmcp_logging_middleware_is_mounted_when_enabled() -> None:
    config = _make_test_config(logging_access_log_enabled=True)
    assert len(_mounted_logging_middleware(config)) == 1


def test_fastmcp_config_rejects_the_removed_turn_off_field() -> None:
    """The superseded name is gone: setting it fails at construction rather than silently.

    The default flipped, so a shim could not have been silent anyway, and a service that set the old
    field has to re-decide rather than upgrade past the change without noticing.
    """
    with pytest.raises(TypeError, match="logging_turn_off_middleware"):
        _make_test_config(logging_turn_off_middleware=True)


@pytest.mark.parametrize("overrides", [{}, {"logging_access_log_enabled": True}], ids=["default", "enabled"])
def test_fastmcp_logging_config_warns_nothing(overrides: dict[str, bool]) -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _make_test_config(**overrides)

    assert [str(one.message) for one in caught] == []


@pytest.mark.parametrize(
    ("package_name", "extra_config"),
    [
        ("sentry_sdk", {"sentry_dsn": "https://testdsn@localhost/1"}),
        ("structlog", {}),
        ("prometheus_client", {"prometheus_metrics_path": "/custom"}),
    ],
)
def test_fastmcp_bootstrapper_with_missing_instrument_dependency(
    package_name: str, extra_config: dict[str, typing.Any]
) -> None:
    with emulate_package_missing(package_name), pytest.warns(UserWarning, match=package_name):
        FastMcpBootstrapper(bootstrap_config=FastMcpConfig(**extra_config))


def test_fastmcp_bootstrapper_runs_without_sentry_sdk() -> None:
    with emulate_package_missing_with_module_reload(
        "sentry_sdk",
        ["lite_bootstrap.instruments.sentry_instrument", "lite_bootstrap.bootstrappers.fastmcp_bootstrapper"],
    ):
        with pytest.warns(UserWarning, match="sentry_sdk"):
            bootstrapper = fastmcp_bootstrapper.FastMcpBootstrapper(
                bootstrap_config=fastmcp_bootstrapper.FastMcpConfig(sentry_dsn="https://testdsn@localhost/1")
            )
        bootstrapper.bootstrap()
        bootstrapper.teardown()


def test_fastmcp_bootstrap_without_prometheus_client() -> None:
    # Regression guard mirroring the FastStream prometheus-missing test: ensures
    # FastMcpPrometheusInstrument.dependencies_installed() prevents construction-time
    # failure when prometheus_client is absent.
    with emulate_package_missing_with_module_reload(
        "prometheus_client",
        ["lite_bootstrap.bootstrappers.fastmcp_bootstrapper"],
    ):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            bootstrapper = FastMcpBootstrapper(bootstrap_config=FastMcpConfig())
        assert not caught
        bootstrapper.bootstrap()
        bootstrapper.teardown()


def test_second_fastmcp_bootstrapper_on_same_app_warns_not_stacks() -> None:
    application = FastMCP()
    config_a = FastMcpConfig(application=application, service_name="a")
    bootstrapper_a = FastMcpBootstrapper(bootstrap_config=config_a)
    providers_after_first = list(application.providers)

    config_b = FastMcpConfig(application=application, service_name="b")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        FastMcpBootstrapper(bootstrap_config=config_b)

    matching = [w for w in caught if "already has a lite-bootstrap teardown hook" in str(w.message)]
    assert matching, "expected warning about existing lite-bootstrap teardown hook"
    assert list(application.providers) == providers_after_first, (
        "second bootstrapper must not stack another _TeardownProvider"
    )

    bootstrapper_a.teardown()


def test_fastmcp_bootstrap_without_structlog() -> None:
    # Regression guard: FastMcpLoggingInstrument.bootstrap() must short-circuit
    # the middleware registration when structlog is absent, because the
    # middleware references fastmcp_access_logger which only exists inside
    # the structlog guard.
    with emulate_package_missing_with_module_reload(
        "structlog",
        ["lite_bootstrap.bootstrappers.fastmcp_bootstrapper"],
    ):
        with pytest.warns(UserWarning, match="structlog"):
            bootstrapper = FastMcpBootstrapper(bootstrap_config=FastMcpConfig())
        bootstrapper.bootstrap()
        bootstrapper.teardown()


def test_second_fastmcp_bootstrapper_bootstrap_raises() -> None:
    application = FastMCP()
    first = FastMcpBootstrapper(bootstrap_config=FastMcpConfig(application=application, service_name="a"))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        second = FastMcpBootstrapper(bootstrap_config=FastMcpConfig(application=application, service_name="b"))

    try:
        first.bootstrap()
        with pytest.raises(ConfigurationError, match="FastMcpBootstrapper"):
            second.bootstrap()
    finally:
        first.teardown()


def _count_opentelemetry_middlewares(http_application: Starlette) -> int:
    return sum(middleware.cls is build_opentelemetry_middleware for middleware in http_application.user_middleware)


def _server_spans(exporter: InMemorySpanExporter) -> list[ReadableSpan]:
    return [span for span in exporter.get_finished_spans() if span.kind == SpanKind.SERVER]


@contextlib.contextmanager
def _bootstrapped_with_span_exporter(
    **overrides: typing.Any,  # noqa: ANN401
) -> Generator[tuple[FastMcpBootstrapper, FastMCP, InMemorySpanExporter]]:
    """Trace with health-check spans on, since the health route is the cheapest request these tests send."""
    config_overrides: typing.Final = {"opentelemetry_generate_health_check_spans": True, **overrides}
    bootstrapper = FastMcpBootstrapper(
        bootstrap_config=_make_test_config(opentelemetry_log_traces=True, **config_overrides)
    )
    application = bootstrapper.bootstrap()
    tracer_provider = get_tracer_provider()
    assert isinstance(tracer_provider, SDKTracerProvider)
    exporter = InMemorySpanExporter()
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))
    try:
        yield bootstrapper, application, exporter
    finally:
        bootstrapper.teardown()


def test_fastmcp_otel_span_carries_route_template() -> None:
    with (
        _bootstrapped_with_span_exporter() as (bootstrapper, application, exporter),
        TestClient(application.http_app()) as client,
    ):
        assert client.get(bootstrapper.bootstrap_config.health_checks_path).status_code == status.HTTP_200_OK
        client.post("/mcp", json={})

    server_spans = _server_spans(exporter)
    health_checks_path = bootstrapper.bootstrap_config.health_checks_path
    assert [span.name for span in server_spans] == [f"GET {health_checks_path}", "POST /mcp"]
    assert [(span.attributes or {}).get("http.route") for span in server_spans] == [health_checks_path, "/mcp"]


def test_fastmcp_otel_unmatched_path_span_is_named_by_method_only() -> None:
    with (
        _bootstrapped_with_span_exporter() as (_, application, exporter),
        TestClient(application.http_app()) as client,
    ):
        assert client.get("/missing/abc").status_code == status.HTTP_404_NOT_FOUND

    server_spans = _server_spans(exporter)
    assert [span.name for span in server_spans] == ["GET"]
    assert "http.route" not in (server_spans[0].attributes or {})


def test_fastmcp_otel_excludes_infrastructure_and_configured_paths() -> None:
    with (
        _bootstrapped_with_span_exporter(
            health_checks_path="/custom-health/",
            opentelemetry_generate_health_check_spans=False,
            opentelemetry_excluded_urls=["/mcp"],
        ) as (bootstrapper, application, exporter),
        TestClient(application.http_app()) as client,
    ):
        client.get("/custom-health/")
        client.get("/custom-health")
        client.get(bootstrapper.bootstrap_config.prometheus_metrics_path)
        client.post("/mcp", json={})
        client.get("/custom-healthy")

    assert [span.name for span in _server_spans(exporter)] == ["GET"]


def _span_kinds_for_one_health_check(**overrides: typing.Any) -> list[SpanKind]:  # noqa: ANN401
    with (
        _bootstrapped_with_span_exporter(**overrides) as (bootstrapper, application, exporter),
        TestClient(application.http_app()) as client,
    ):
        assert client.get(bootstrapper.bootstrap_config.health_checks_path).status_code == status.HTTP_200_OK

    return [span.kind for span in exporter.get_finished_spans()]


def test_fastmcp_otel_exclude_spans_defaults_to_only_the_server_span() -> None:
    assert _span_kinds_for_one_health_check() == [SpanKind.SERVER]


def test_fastmcp_otel_exclude_spans_emptied_records_the_event_spans() -> None:
    assert SpanKind.INTERNAL in _span_kinds_for_one_health_check(opentelemetry_exclude_spans=[])


def test_fastmcp_otel_instruments_every_http_app_once() -> None:
    with _bootstrapped_with_span_exporter() as (bootstrapper, application, _):
        first_http_application = application.http_app()
        second_http_application = application.http_app(path="/other")
        instrument = next(one for one in bootstrapper.instruments if isinstance(one, FastMcpOpenTelemetryInstrument))
        instrument._instrument_http_app(first_http_application)  # noqa: SLF001

    assert _count_opentelemetry_middlewares(first_http_application) == 1
    assert _count_opentelemetry_middlewares(second_http_application) == 1


def test_fastmcp_otel_teardown_restores_http_app() -> None:
    with _bootstrapped_with_span_exporter() as (_, application, _):
        assert "http_app" in vars(application)

    assert "http_app" not in vars(application)
    assert _count_opentelemetry_middlewares(application.http_app()) == 0


def test_fastmcp_otel_leaves_http_app_alone_when_not_configured() -> None:
    bootstrapper = FastMcpBootstrapper(bootstrap_config=_make_test_config())
    application = bootstrapper.bootstrap()
    try:
        assert _count_opentelemetry_middlewares(application.http_app()) == 0
    finally:
        bootstrapper.teardown()


def test_fastmcp_otel_is_skipped_without_asgi_instrumentation() -> None:
    with emulate_package_missing_with_module_reload(
        "opentelemetry.instrumentation.asgi",
        ["lite_bootstrap.bootstrappers.fastmcp_bootstrapper"],
    ):
        with pytest.warns(UserWarning, match="opentelemetry-instrumentation-asgi"):
            bootstrapper = fastmcp_bootstrapper.FastMcpBootstrapper(
                bootstrap_config=_make_test_config(opentelemetry_log_traces=True)
            )
        application = bootstrapper.bootstrap()
        try:
            assert _count_opentelemetry_middlewares(application.http_app()) == 0
        finally:
            bootstrapper.teardown()


@pytest.fixture(autouse=True)
def _unregister_request_metrics() -> None:
    unregister_prometheus_request_metrics()


def _http_request_counts(**overrides: typing.Any) -> tuple[int, float]:  # noqa: ANN401
    """Return the OpenTelemetry and Prometheus request counts after one request."""
    config = _make_test_config(**overrides)
    path = f"/items-{uuid.uuid4().hex}"

    @config.application.custom_route(path, methods=["GET"])
    async def items(_request: Request) -> Response:
        return Response("ok")

    with in_memory_opentelemetry_metric_reader() as reader:
        bootstrapper = FastMcpBootstrapper(bootstrap_config=config)
        application = bootstrapper.bootstrap()
    try:
        with TestClient(application.http_app()) as client:
            assert client.get(path).status_code == status.HTTP_200_OK
        return opentelemetry_http_request_count(reader), prometheus_request_count(
            "http_requests_total", "handler", path
        )
    finally:
        bootstrapper.teardown()


@pytest.mark.parametrize(("overrides", "expected"), HTTP_METRIC_CASES)
def test_fastmcp_http_metrics_are_recorded_once(overrides: dict[str, typing.Any], expected: tuple[int, int]) -> None:
    assert _http_request_counts(**overrides) == expected


def test_fastmcp_prometheus_keeps_tool_metrics_and_metrics_route_while_opentelemetry_records_http_metrics() -> None:
    config: typing.Final = _make_test_config(opentelemetry_metrics_endpoint="localhost:4317")
    with in_memory_opentelemetry_metric_reader():
        bootstrapper = FastMcpBootstrapper(bootstrap_config=config)
        application = bootstrapper.bootstrap()
    try:
        assert any(isinstance(middleware, FastMcpPrometheusMiddleware) for middleware in application.middleware)
        with TestClient(application.http_app()) as client:
            assert client.get(config.prometheus_metrics_path).status_code == status.HTTP_200_OK
    finally:
        bootstrapper.teardown()


def _sample_value(name: str, labels: dict[str, str]) -> float:
    return prometheus_client.REGISTRY.get_sample_value(name, labels) or 0.0


def _http_requests_total(handler: str, method: str = "GET", status_group: str = "2xx") -> float:
    return _sample_value("http_requests_total", {"handler": handler, "method": method, "status": status_group})


def test_fastmcp_prometheus_excludes_infrastructure_and_user_paths() -> None:
    health_path = f"/health-{uuid.uuid4().hex}/"
    normal_path = f"{health_path}report"
    excluded_path = "/excluded"
    config = _make_test_config(
        health_checks_path=health_path,
        prometheus_instrumentator_additional_params={"excluded_handlers": [f"^{excluded_path}$"]},
    )

    @config.application.custom_route(normal_path, methods=["GET"])
    @config.application.custom_route(excluded_path, methods=["GET"])
    async def items(_request: Request) -> Response:
        return Response("ok")

    bootstrapper = FastMcpBootstrapper(bootstrap_config=config)
    application = bootstrapper.bootstrap()
    try:
        with TestClient(application.http_app()) as client:
            for path in (health_path, config.prometheus_metrics_path, excluded_path, normal_path):
                assert client.get(path).is_success
            client.get("/missing")
    finally:
        bootstrapper.teardown()

    assert _http_requests_total(health_path) == 0
    assert _http_requests_total(config.prometheus_metrics_path) == 0
    assert _http_requests_total(excluded_path) == 0
    assert _http_requests_total(normal_path) == 1
    assert _http_requests_total("none", status_group="4xx") == 1


def test_fastmcp_prometheus_counts_requests_of_every_http_app() -> None:
    path = f"/items-{uuid.uuid4().hex}"
    config = _make_test_config()

    @config.application.custom_route(path, methods=["GET"])
    async def items(_request: Request) -> Response:
        return Response("ok")

    bootstrapper = FastMcpBootstrapper(bootstrap_config=config)
    application = bootstrapper.bootstrap()
    try:
        for http_application in (application.http_app(), application.http_app(path="/other")):
            with TestClient(http_application) as client:
                client.get(path)
    finally:
        bootstrapper.teardown()

    expected_requests = 2
    assert _http_requests_total(path) == expected_requests


def test_fastmcp_prometheus_teardown_restores_http_app() -> None:
    bootstrapper = FastMcpBootstrapper(bootstrap_config=_make_test_config())
    application = bootstrapper.bootstrap()
    assert "http_app" in vars(application)

    bootstrapper.teardown()

    assert "http_app" not in vars(application)


def _retained_tool_metric_samples() -> int:
    return sum(
        len(metric.samples)
        for metric in prometheus_client.REGISTRY.collect()
        if metric.name.startswith("fastmcp_tool_call")
    )


@pytest.mark.parametrize("name_prefix", ["missing", "000000000000_missing"])
async def test_fastmcp_prometheus_unknown_tools_do_not_retain_metric_samples(name_prefix: str) -> None:
    bootstrapper = FastMcpBootstrapper(bootstrap_config=_make_test_config(logging_enabled=False))
    application = bootstrapper.bootstrap()
    samples_before = _retained_tool_metric_samples()
    missing_prefix = f"{name_prefix}_{uuid.uuid4().hex}"
    try:
        async with Client(application) as client:
            for index in range(100):
                with pytest.raises(ToolError, match="Unknown tool"):
                    await client.call_tool(f"{missing_prefix}_{index}")
    finally:
        bootstrapper.teardown()

    assert _retained_tool_metric_samples() == samples_before


async def test_fastmcp_prometheus_hashed_proxy_aliases_share_metric_samples() -> None:
    remote = FastMCP()
    tool_name = f"echo_{uuid.uuid4().hex}"
    tool_hash = hash_tool("metrics", tool_name)

    def echo() -> str:
        return "ok"

    remote.tool(echo, name=tool_name, meta={"fastmcp": {"tool_hash": tool_hash}, "ui": {"visibility": ["app"]}})
    bootstrapper = FastMcpBootstrapper(
        bootstrap_config=_make_test_config(application=create_proxy(remote), logging_enabled=False)
    )
    application = bootstrapper.bootstrap()
    metric_label = hashed_backend_name("metrics", tool_name)
    try:
        async with Client(application) as client:
            await client.call_tool(metric_label)
            samples_after_first_call = _retained_tool_metric_samples()
            for index in range(100):
                result = await client.call_tool(f"{tool_hash}_alias_{index}")
                assert result.data == "ok"
            assert _retained_tool_metric_samples() == samples_after_first_call
    finally:
        bootstrapper.teardown()

    expected_calls = 101
    assert _sample_value("fastmcp_tool_calls_total", {"tool": metric_label, "status": "success"}) == expected_calls
    assert _sample_value("fastmcp_tool_call_duration_seconds_count", {"tool": metric_label}) == expected_calls


@pytest.mark.parametrize("tool_source", ["registered", "mounted", "transformed", "hashed"])
async def test_fastmcp_prometheus_counts_tool_calls(tool_source: str) -> None:
    bootstrapper = FastMcpBootstrapper(bootstrap_config=_make_test_config())
    application = bootstrapper.bootstrap()
    echo_name = f"echo_{uuid.uuid4().hex}"
    failing_name = f"failing_{uuid.uuid4().hex}"

    def echo(text: str) -> str:
        return text

    def failing() -> str:
        message = "boom"
        raise ValueError(message)

    tool_server = FastMCP() if tool_source == "mounted" else application
    for tool_function, tool_name in ((echo, echo_name), (failing, failing_name)):
        meta = (
            {"fastmcp": {"tool_hash": hash_tool("metrics", tool_name)}, "ui": {"visibility": ["app"]}}
            if tool_source == "hashed"
            else None
        )
        tool_server.tool(tool_function, name=tool_name, meta=meta)
    if tool_source == "mounted":
        application.mount(tool_server, namespace="mounted")
        echo_name = f"mounted_{echo_name}"
        failing_name = f"mounted_{failing_name}"
    elif tool_source == "transformed":
        application.add_transform(
            ToolTransform(
                {
                    echo_name: ToolTransformConfig(name=f"renamed_{echo_name}"),
                    failing_name: ToolTransformConfig(name=f"renamed_{failing_name}"),
                }
            )
        )
        echo_name = f"renamed_{echo_name}"
        failing_name = f"renamed_{failing_name}"
    elif tool_source == "hashed":
        echo_name = hashed_backend_name("metrics", echo_name)
        failing_name = hashed_backend_name("metrics", failing_name)
    try:
        async with Client(application) as client:
            await client.call_tool(echo_name, {"text": "hi"})
            await client.call_tool(echo_name, {"text": "hi"})
            with pytest.raises(ToolError):
                await client.call_tool(failing_name, {})
    finally:
        bootstrapper.teardown()

    expected_successes = 2
    assert _sample_value("fastmcp_tool_calls_total", {"tool": echo_name, "status": "success"}) == expected_successes
    assert _sample_value("fastmcp_tool_calls_total", {"tool": failing_name, "status": "error"}) == 1
    assert _sample_value("fastmcp_tool_calls_total", {"tool": echo_name, "status": "error"}) == 0
    assert _sample_value("fastmcp_tool_calls_total", {"tool": failing_name, "status": "success"}) == 0
    assert _sample_value("fastmcp_tool_call_duration_seconds_count", {"tool": echo_name}) == expected_successes
    assert _sample_value("fastmcp_tool_call_duration_seconds_count", {"tool": failing_name}) == 1


def test_fastmcp_prometheus_tool_metrics_can_be_disabled() -> None:
    bootstrapper = FastMcpBootstrapper(
        bootstrap_config=_make_test_config(fastmcp_prometheus_tool_metrics_enabled=False)
    )
    application = bootstrapper.bootstrap()
    try:
        assert not [one for one in application.middleware if isinstance(one, FastMcpPrometheusMiddleware)]
    finally:
        bootstrapper.teardown()


def test_fastmcp_prometheus_is_skipped_without_instrumentator() -> None:
    with emulate_package_missing_with_module_reload(
        "prometheus_fastapi_instrumentator",
        ["lite_bootstrap.bootstrappers.fastmcp_bootstrapper"],
    ):
        with pytest.warns(UserWarning, match="prometheus_fastapi_instrumentator"):
            bootstrapper = fastmcp_bootstrapper.FastMcpBootstrapper(bootstrap_config=_make_test_config())
        application = bootstrapper.bootstrap()
        try:
            assert "http_app" not in vars(application)
        finally:
            bootstrapper.teardown()


def test_fastmcp_http_app_postprocessors_chain_and_restore_in_reverse() -> None:
    application = FastMCP()
    applied: list[str] = []

    def postprocessor(name: str) -> typing.Callable[[StarletteWithLifespan], StarletteWithLifespan]:
        def postprocess(http_application: StarletteWithLifespan) -> StarletteWithLifespan:
            applied.append(name)
            return http_application

        return postprocess

    restore_first = _postprocess_http_apps(application, postprocessor("first"))
    restore_second = _postprocess_http_apps(application, postprocessor("second"))
    application.http_app()
    assert applied == ["first", "second"]

    restore_second()
    applied.clear()
    application.http_app()
    assert applied == ["first"]

    restore_first()
    assert "http_app" not in vars(application)


def test_fastmcp_otel_honors_excluded_urls_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OTEL_PYTHON_EXCLUDED_URLS", raising=False)
    monkeypatch.setenv("OTEL_PYTHON_STARLETTE_EXCLUDED_URLS", "/mcp")
    with (
        _bootstrapped_with_span_exporter() as (bootstrapper, application, exporter),
        TestClient(application.http_app()) as client,
    ):
        client.post("/mcp", json={})
        client.get(bootstrapper.bootstrap_config.health_checks_path)

    assert [span.name for span in _server_spans(exporter)] == [
        f"GET {bootstrapper.bootstrap_config.health_checks_path}"
    ]


@pytest.mark.parametrize(("probe", "expected_status", "expected_health_status"), HEALTH_PROBE_CASES)
def test_fastmcp_health_check_runs_probes(
    probe: HealthProbe,
    expected_status: int,
    expected_health_status: bool,
) -> None:
    config = _make_test_config(health_checks_probes={"cache": probe})
    bootstrapper = FastMcpBootstrapper(bootstrap_config=config)
    application = bootstrapper.bootstrap()
    try:
        with TestClient(application.http_app()) as test_client:
            response = test_client.get(config.health_checks_path)
    finally:
        bootstrapper.teardown()

    assert response.status_code == expected_status
    assert response.json() == {
        "health_status": expected_health_status,
        "service_name": "test-mcp",
        "service_version": "1.2.3",
    }
