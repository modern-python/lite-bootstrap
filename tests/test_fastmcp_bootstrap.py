import typing
import uuid
import warnings
from unittest.mock import MagicMock

import prometheus_client
import pytest
from fastmcp import FastMCP
from fastmcp.server.middleware import MiddlewareContext
from starlette import status
from starlette.testclient import TestClient

from lite_bootstrap import BootstrapperNotReadyError, FastMcpBootstrapper, FastMcpConfig
from lite_bootstrap.bootstrappers.fastmcp_bootstrapper import FastMcpLoggingMiddleware
from lite_bootstrap.exceptions import ConfigurationError
from tests.conftest import emulate_package_missing, emulate_package_missing_with_module_reload


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
        "logging_buffer_capacity": 0,
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


def test_fastmcp_logging_middleware_is_mounted_by_default() -> None:
    config = _make_test_config()
    bootstrapper = FastMcpBootstrapper(bootstrap_config=config)
    application = bootstrapper.bootstrap()
    try:
        assert len(_find_mcp_logging_middleware(application)) == 1
    finally:
        bootstrapper.teardown()


def test_fastmcp_logging_middleware_disabled_via_flag() -> None:
    config = _make_test_config(logging_turn_off_middleware=True)
    bootstrapper = FastMcpBootstrapper(bootstrap_config=config)
    application = bootstrapper.bootstrap()
    try:
        assert _find_mcp_logging_middleware(application) == []
    finally:
        bootstrapper.teardown()


@pytest.mark.parametrize(
    ("package_name", "extra_config"),
    [
        ("sentry_sdk", {"sentry_dsn": "https://testdsn@localhost/1"}),
        ("structlog", {}),
        ("prometheus_client", {}),
    ],
)
def test_fastmcp_bootstrapper_with_missing_instrument_dependency(
    package_name: str, extra_config: dict[str, typing.Any]
) -> None:
    with emulate_package_missing(package_name), pytest.warns(UserWarning, match=package_name):
        FastMcpBootstrapper(bootstrap_config=FastMcpConfig(**extra_config))


def test_fastmcp_bootstrap_without_prometheus_client() -> None:
    # Regression guard mirroring the FastStream prometheus-missing test: ensures
    # FastMcpPrometheusInstrument.dependencies_installed() prevents construction-time
    # failure when prometheus_client is absent.
    with emulate_package_missing_with_module_reload(
        "prometheus_client",
        ["lite_bootstrap.bootstrappers.fastmcp_bootstrapper"],
    ):
        with pytest.warns(UserWarning, match="prometheus_client"):
            bootstrapper = FastMcpBootstrapper(bootstrap_config=FastMcpConfig())
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
