import contextlib
import functools
import logging
import socket
import threading
import typing
import warnings
from collections.abc import Generator, Mapping
from unittest.mock import AsyncMock

import fastapi
import httpx
import pytest
import sentry_sdk
import uvicorn
from fastmcp import FastMCP
from sentry_sdk import integrations as sentry_integrations
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.httpx import HttpxIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
from starlette import status
from starlette.authentication import AuthCredentials, AuthenticationBackend, SimpleUser
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.requests import HTTPConnection, Request
from starlette.responses import JSONResponse, Response
from starlette.testclient import TestClient
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.websockets import WebSocket

from lite_bootstrap import FastAPIBootstrapper, FastAPIConfig, FastMcpBootstrapper, FastMcpConfig
from lite_bootstrap.bootstrappers.fastapi_bootstrapper import FastAPISentryInstrument
from lite_bootstrap.helpers.starlette_sentry import _reporting_server_errors
from lite_bootstrap.instruments.sentry_instrument import DEFAULT_DATA_COLLECTION
from tests.conftest import SentryTestTransport


std_logger = logging.getLogger(__name__)
_REPLACED_IDENTIFIERS: typing.Final = (StarletteIntegration.identifier, FastApiIntegration.identifier)


class MappedToUnavailableError(Exception):
    pass


class CarriesUnavailableStatusError(Exception):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE


class RegisteredAfterBootstrapError(Exception):
    status_code = status.HTTP_502_BAD_GATEWAY


class _AliceBackend(AuthenticationBackend):
    async def authenticate(self, conn: HTTPConnection) -> tuple[AuthCredentials, SimpleUser]:  # noqa: ARG002
        return AuthCredentials(["authenticated"]), SimpleUser("alice")


class _HidesItsInnerApp:
    def __init__(self, app: ASGIApp) -> None:
        self._inner_app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self._inner_app(scope, receive, send)


router = fastapi.APIRouter()


@router.get("/boom")
async def boom() -> None:
    message = "boom"
    raise RuntimeError(message)


@router.get("/items/{item_id}")
async def item(item_id: int) -> None:
    raise RuntimeError(str(item_id))


@router.post("/read-json-then-boom")
async def read_json_then_boom(payload: typing.Annotated[dict[str, str], fastapi.Body()]) -> None:
    raise RuntimeError(payload["message"])


@router.post("/read-form-then-boom")
async def read_form_then_boom(message: typing.Annotated[str, fastapi.Form()]) -> None:
    raise RuntimeError(message)


@router.post("/read-raw-body-then-boom")
async def read_raw_body_then_boom(request: Request) -> None:
    raise RuntimeError((await request.body()).decode())


@router.post("/boom-without-reading-body")
async def boom_without_reading_body() -> None:
    message = "boom"
    raise RuntimeError(message)


@router.get("/http-404")
async def http_404() -> None:
    raise fastapi.HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.get("/http-503")
async def http_503() -> None:
    raise fastapi.HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)


@router.get("/mapped-503")
async def mapped_503() -> None:
    raise MappedToUnavailableError


@router.get("/carries-503")
async def carries_503() -> None:
    raise CarriesUnavailableStatusError


@router.get("/logs-then-ok")
async def logs_then_ok() -> str:
    std_logger.warning("breadcrumb from an earlier request")
    return "ok"


@router.get("/integrations")
async def integrations() -> list[str]:
    return sorted(sentry_sdk.get_client().integrations)


@router.websocket("/ws")
async def websocket_boom(websocket: WebSocket) -> None:
    await websocket.accept()
    message = "websocket boom"
    raise RuntimeError(message)


async def _respond_503(_: Request, __: Exception) -> Response:
    return Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)


def _build_config(transport: SentryTestTransport, **overrides: typing.Any) -> FastAPIConfig:  # noqa: ANN401
    sentry_additional_params = {"transport": transport, **overrides.pop("sentry_additional_params", {})}
    application = fastapi.FastAPI(
        exception_handlers={MappedToUnavailableError: _respond_503, CarriesUnavailableStatusError: _respond_503}
    )
    application.include_router(router)
    if overrides.pop("hide_inner_app", False):
        application.add_middleware(_HidesItsInnerApp)
    if overrides.pop("authenticated", False):
        application.add_middleware(AuthenticationMiddleware, backend=_AliceBackend())
    return FastAPIConfig(
        service_environment="test",
        sentry_dsn="https://testdsn@localhost/1",
        sentry_additional_params=sentry_additional_params,
        application=application,
        **overrides,
    )


def _error_events(transport: SentryTestTransport) -> list[dict[str, typing.Any]]:
    events = (
        typing.cast("dict[str, typing.Any] | None", envelope.get_event()) for envelope in transport.mock_envelopes
    )
    return [event for event in events if event is not None and "exception" in event]


def _exception_types(transport: SentryTestTransport) -> list[str]:
    return [event["exception"]["values"][-1]["type"] for event in _error_events(transport)]


def _bootstrap(transport: SentryTestTransport, **overrides: typing.Any) -> fastapi.FastAPI:  # noqa: ANN401
    return FastAPIBootstrapper(bootstrap_config=_build_config(transport, **overrides)).bootstrap()


def _request(transport: SentryTestTransport, *paths: str, **overrides: typing.Any) -> list[int]:  # noqa: ANN401
    with TestClient(app=_bootstrap(transport, **overrides), raise_server_exceptions=False) as test_client:
        return [test_client.get(path).status_code for path in paths]


def _active_integrations(transport: SentryTestTransport, **overrides: typing.Any) -> list[str]:  # noqa: ANN401
    with TestClient(app=_bootstrap(transport, **overrides)) as test_client:
        return test_client.get("/integrations").json()


def _sentry_init_kwargs(config: FastAPIConfig) -> Mapping[str, typing.Any]:
    return FastAPISentryInstrument(bootstrap_config=config)._build_init_params()  # noqa: SLF001


def test_lean_capture_is_the_default_on_fastapi_while_tracing_is_off(sentry_mock: SentryTestTransport) -> None:
    application = fastapi.FastAPI()
    application.include_router(router)
    bootstrapped = FastAPIBootstrapper(
        bootstrap_config=FastAPIConfig(
            sentry_dsn="https://testdsn@localhost/1",
            sentry_additional_params={"transport": sentry_mock},
            application=application,
        )
    ).bootstrap()
    with TestClient(app=bootstrapped, raise_server_exceptions=False) as test_client:
        active = test_client.get("/integrations").json()
        test_client.get("/boom")

    assert not set(_REPLACED_IDENTIFIERS) & set(active)
    [event] = _error_events(sentry_mock)
    assert event["request"]["url"] == "http://testserver/boom"


@pytest.mark.parametrize(
    "tracing_overrides",
    [
        pytest.param({"sentry_traces_sample_rate": 0.0}, id="sentry_traces_sample_rate"),
        pytest.param({"sentry_additional_params": {"traces_sample_rate": 0.5}}, id="traces_sample_rate"),
        pytest.param({"sentry_additional_params": {"traces_sampler": lambda _: 0.5}}, id="traces_sampler"),
    ],
)
def test_default_keeps_the_starlette_integrations_while_tracing_is_on(
    sentry_mock: SentryTestTransport, tracing_overrides: dict[str, typing.Any]
) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        active = _active_integrations(sentry_mock, **tracing_overrides)

    assert set(_REPLACED_IDENTIFIERS) <= set(active)


def test_lean_capture_turned_off_keeps_the_starlette_integrations(sentry_mock: SentryTestTransport) -> None:
    config = _build_config(sentry_mock, sentry_lean_error_capture=False)
    active = _active_integrations(sentry_mock, sentry_lean_error_capture=False)

    assert "disabled_integrations" not in _sentry_init_kwargs(config)
    assert set(_REPLACED_IDENTIFIERS) <= set(active)


def test_lean_capture_reports_unhandled_exception_with_request_data(sentry_mock: SentryTestTransport) -> None:
    with TestClient(app=_bootstrap(sentry_mock), raise_server_exceptions=False) as test_client:
        response = test_client.get("/items/7?page=2", headers={"x-real-ip": "10.0.0.1", "user-agent": "tests"})

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    [event] = _error_events(sentry_mock)
    exception = event["exception"]["values"][-1]
    assert exception["type"] == "RuntimeError"
    assert (exception["mechanism"]["type"], exception["mechanism"]["handled"]) == ("starlette", False)
    assert event["request"]["method"] == "GET"
    assert event["request"]["url"] == "http://testserver/items/7"
    assert event["request"]["query_string"] == "page=2"
    assert event["request"]["headers"]["x-real-ip"] == "[Filtered]"
    assert event["request"]["headers"]["user-agent"] == "tests"
    assert "env" not in event["request"]
    assert event["transaction"] == "/items/{item_id}"
    assert event["transaction_info"] == {"source": "route"}


def test_lean_capture_filters_cookies_through_data_collection(sentry_mock: SentryTestTransport) -> None:
    with TestClient(
        app=_bootstrap(sentry_mock), raise_server_exceptions=False, cookies={"theme": "dark", "session": "s3cr3t"}
    ) as test_client:
        test_client.get("/boom")

    [event] = _error_events(sentry_mock)
    assert event["request"]["cookies"] == {"theme": "dark", "session": "[Filtered]"}
    assert event["request"]["headers"]["cookie"] == "[Filtered]"


def test_lean_capture_sends_no_cookies_when_data_collection_turns_them_off(sentry_mock: SentryTestTransport) -> None:
    data_collection = {**DEFAULT_DATA_COLLECTION, "cookies": {"mode": "off"}}
    application = _bootstrap(sentry_mock, sentry_additional_params={"data_collection": data_collection})
    with TestClient(app=application, raise_server_exceptions=False, cookies={"theme": "dark"}) as test_client:
        test_client.get("/boom")

    [event] = _error_events(sentry_mock)
    assert "cookies" not in event["request"]


@pytest.mark.parametrize(
    ("user_info", "expected_user"),
    [
        pytest.param(False, None, id="user-info-off"),
        pytest.param(True, {"username": "alice"}, id="user-info-on"),
    ],
)
def test_lean_capture_attaches_the_authenticated_user_only_when_data_collection_allows_it(
    sentry_mock: SentryTestTransport, user_info: bool, expected_user: dict[str, str] | None
) -> None:
    data_collection = {**DEFAULT_DATA_COLLECTION, "user_info": user_info}
    _request(sentry_mock, "/boom", sentry_additional_params={"data_collection": data_collection}, authenticated=True)

    [event] = _error_events(sentry_mock)
    assert event.get("user") == expected_user


def test_lean_capture_attaches_the_client_address_only_when_data_collection_allows_it(
    sentry_mock: SentryTestTransport,
) -> None:
    data_collection = {**DEFAULT_DATA_COLLECTION, "user_info": True}
    _request(sentry_mock, "/boom", sentry_additional_params={"data_collection": data_collection})

    [event] = _error_events(sentry_mock)
    assert event["request"]["env"] == {"REMOTE_ADDR": "testclient"}


@pytest.mark.parametrize(
    ("http_bodies", "path", "request_kwargs", "expected_data"),
    [
        pytest.param([], "/read-json-then-boom", {"json": {"message": "boom"}}, None, id="bodies-off"),
        pytest.param(
            ["incoming_request"],
            "/read-json-then-boom",
            {"json": {"message": "boom"}},
            {"message": "boom"},
            id="json-read-by-handler",
        ),
        pytest.param(
            ["incoming_request"],
            "/read-form-then-boom",
            {"data": {"message": "boom"}},
            {"message": "boom"},
            id="form-read-by-handler",
        ),
        pytest.param(
            ["incoming_request"], "/read-raw-body-then-boom", {"content": b"boom"}, "boom", id="raw-read-by-handler"
        ),
        pytest.param(
            ["incoming_request"],
            "/read-raw-body-then-boom",
            {"content": b"{", "headers": {"content-type": "application/json"}},
            "{",
            id="invalid-json-read-by-handler",
        ),
        pytest.param(
            ["incoming_request"],
            "/read-raw-body-then-boom",
            {"files": {"upload": ("boom.txt", b"boom")}},
            "",
            id="multipart-read-by-handler",
        ),
        pytest.param(
            ["incoming_request"],
            "/boom-without-reading-body",
            {"json": {"message": "boom"}},
            None,
            id="not-read-by-handler",
        ),
    ],
)
def test_lean_capture_attaches_only_a_body_the_handler_already_read(
    sentry_mock: SentryTestTransport,
    http_bodies: list[str],
    path: str,
    request_kwargs: dict[str, typing.Any],
    expected_data: dict[str, str] | str | None,
) -> None:
    data_collection = {**DEFAULT_DATA_COLLECTION, "http_bodies": http_bodies}
    application = _bootstrap(sentry_mock, sentry_additional_params={"data_collection": data_collection})
    with TestClient(app=application, raise_server_exceptions=False) as test_client:
        test_client.post(path, **request_kwargs)

    [event] = _error_events(sentry_mock)
    assert event["request"].get("data") == expected_data


async def test_lean_capture_continues_an_incoming_sentry_trace(sentry_mock: SentryTestTransport) -> None:
    # Called without TestClient: sentry-sdk's httpx integration would overwrite the outgoing sentry-trace.
    trace_id = "771a43a4192642f0b136d5159a501700"
    application = _bootstrap(sentry_mock)
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/boom",
        "raw_path": b"/boom",
        "root_path": "",
        "query_string": b"",
        "headers": [(b"host", b"testserver"), (b"sentry-trace", f"{trace_id}-1234567890abcdef-1".encode())],
        "client": ("127.0.0.1", 1),
        "server": ("testserver", 80),
        "state": {},
    }
    receive = AsyncMock(return_value={"type": "http.request", "body": b"", "more_body": False})

    with contextlib.suppress(RuntimeError):
        await application(scope, receive, AsyncMock())

    [event] = _error_events(sentry_mock)
    assert event["contexts"]["trace"]["trace_id"] == trace_id


def test_lean_capture_skips_client_http_exceptions(sentry_mock: SentryTestTransport) -> None:
    assert _request(sentry_mock, "/http-404", "/no-such-route") == [
        status.HTTP_404_NOT_FOUND,
        status.HTTP_404_NOT_FOUND,
    ]
    assert _error_events(sentry_mock) == []


def test_lean_capture_reports_server_http_exceptions_as_handled(sentry_mock: SentryTestTransport) -> None:
    assert _request(sentry_mock, "/http-503") == [status.HTTP_503_SERVICE_UNAVAILABLE]

    [event] = _error_events(sentry_mock)
    exception = event["exception"]["values"][-1]
    assert exception["type"] == "HTTPException"
    assert (exception["mechanism"]["type"], exception["mechanism"]["handled"]) == ("starlette", True)
    assert event["request"]["url"] == "http://testserver/http-503"


def test_lean_capture_reports_a_handled_exception_by_its_status_code_not_the_response(
    sentry_mock: SentryTestTransport,
) -> None:
    assert _request(sentry_mock, "/mapped-503", "/carries-503") == [
        status.HTTP_503_SERVICE_UNAVAILABLE,
        status.HTTP_503_SERVICE_UNAVAILABLE,
    ]
    assert _exception_types(sentry_mock) == ["CarriesUnavailableStatusError"]


def test_lean_capture_reports_handled_exceptions_of_a_handler_added_after_bootstrap(
    sentry_mock: SentryTestTransport,
) -> None:
    application = _bootstrap(sentry_mock)
    application.add_exception_handler(RegisteredAfterBootstrapError, _respond_503)

    @application.get("/registered-after-bootstrap")
    async def registered_after_bootstrap() -> None:
        raise RegisteredAfterBootstrapError

    with TestClient(app=application, raise_server_exceptions=False) as test_client:
        assert test_client.get("/registered-after-bootstrap").status_code == status.HTTP_503_SERVICE_UNAVAILABLE

    assert _exception_types(sentry_mock) == ["RegisteredAfterBootstrapError"]


def test_lean_capture_reports_only_escaping_exceptions_when_an_inner_middleware_hides_its_app(
    sentry_mock: SentryTestTransport,
) -> None:
    assert _request(sentry_mock, "/http-503", "/boom", hide_inner_app=True) == [
        status.HTTP_503_SERVICE_UNAVAILABLE,
        status.HTTP_500_INTERNAL_SERVER_ERROR,
    ]
    assert _exception_types(sentry_mock) == ["RuntimeError"]


def test_lean_capture_reports_a_websocket_exception(sentry_mock: SentryTestTransport) -> None:
    with (
        TestClient(app=_bootstrap(sentry_mock)) as test_client,
        contextlib.ExitStack() as stack,
        pytest.raises(RuntimeError, match="websocket boom"),
    ):
        stack.enter_context(test_client.websocket_connect("/ws"))

    [event] = _error_events(sentry_mock)
    assert event["exception"]["values"][-1]["value"] == "websocket boom"
    assert event["request"]["url"] == "ws://testserver/ws"


def test_lean_capture_keeps_breadcrumbs_to_their_own_request(sentry_mock: SentryTestTransport) -> None:
    _request(sentry_mock, "/logs-then-ok", "/boom")

    [event] = _error_events(sentry_mock)
    messages = [crumb.get("message") for crumb in event.get("breadcrumbs", {}).get("values", [])]
    assert "breadcrumb from an earlier request" not in messages


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@contextlib.contextmanager
def _served_by_uvicorn(application: fastapi.FastAPI) -> Generator[str]:
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(application, host="127.0.0.1", port=port, lifespan="off"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        while not server.started:
            thread.join(0.01)
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join()


@pytest.mark.parametrize("lean_error_capture", [True, False])
def test_one_event_per_failing_request_when_uvicorn_logs_the_exception(
    sentry_mock: SentryTestTransport, lean_error_capture: bool
) -> None:
    application = _bootstrap(sentry_mock, sentry_lean_error_capture=lean_error_capture)
    with _served_by_uvicorn(application) as base_url:
        response = httpx.get(f"{base_url}/boom")

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert _exception_types(sentry_mock) == ["RuntimeError"]


_AUTO_ENABLED_IN_THE_TEST_ENVIRONMENT: typing.Final = frozenset({"aiohttp", "httpx", "redis"})


def test_lean_capture_leaves_auto_enabling_integrations_off_and_still_reports(sentry_mock: SentryTestTransport) -> None:
    with TestClient(app=_bootstrap(sentry_mock), raise_server_exceptions=False) as test_client:
        active = test_client.get("/integrations").json()
        test_client.get("/boom")

    assert not _AUTO_ENABLED_IN_THE_TEST_ENVIRONMENT & set(active)
    [event] = _error_events(sentry_mock)
    assert event["request"]["url"] == "http://testserver/boom"


def test_integration_capture_keeps_auto_enabling_integrations(sentry_mock: SentryTestTransport) -> None:
    active = _active_integrations(sentry_mock, sentry_lean_error_capture=False)

    assert set(active) >= _AUTO_ENABLED_IN_THE_TEST_ENVIRONMENT


def test_forced_lean_capture_leaves_auto_enabling_integrations_off_while_tracing_is_on(
    sentry_mock: SentryTestTransport,
) -> None:
    with pytest.warns(UserWarning, match="Sentry tracing"):
        config = _build_config(sentry_mock, sentry_lean_error_capture=True, sentry_traces_sample_rate=1.0)

    assert _sentry_init_kwargs(config)["auto_enabling_integrations"] is False


def test_fastmcp_lean_capture_leaves_mcp_integration_off(sentry_mock: SentryTestTransport) -> None:
    bootstrapper = FastMcpBootstrapper(bootstrap_config=_build_fastmcp_config(sentry_mock))
    application = bootstrapper.bootstrap()
    with TestClient(application.http_app()) as test_client:
        active = test_client.get("/integrations").json()

    assert "mcp" not in active


def test_lean_capture_replaces_the_starlette_integrations(sentry_mock: SentryTestTransport) -> None:
    active = _active_integrations(sentry_mock, sentry_lean_error_capture=True)

    assert not set(_REPLACED_IDENTIFIERS) & set(active)
    assert "logging" in active


def test_lean_capture_keeps_user_disabled_integrations(sentry_mock: SentryTestTransport) -> None:
    httpx_integration = HttpxIntegration()
    config = _build_config(sentry_mock, sentry_additional_params={"disabled_integrations": [httpx_integration]})

    assert _sentry_init_kwargs(config)["disabled_integrations"] == [
        httpx_integration,
        StarletteIntegration,
        FastApiIntegration,
    ]


def test_lean_capture_warns_when_an_earlier_init_installed_the_starlette_integration(
    sentry_mock: SentryTestTransport,
) -> None:
    sentry_integrations._installed_integrations.add(StarletteIntegration.identifier)  # noqa: SLF001
    bootstrapper = FastAPIBootstrapper(
        bootstrap_config=_build_config(sentry_mock, sentry_auto_enabling_integrations=True)
    )

    with pytest.warns(UserWarning, match="installed by an earlier sentry_sdk.init"):
        bootstrapper.bootstrap()
    bootstrapper.teardown()


def test_lean_capture_ignores_an_earlier_installed_starlette_integration_while_auto_enabling_is_off(
    sentry_mock: SentryTestTransport,
) -> None:
    sentry_integrations._installed_integrations.add(StarletteIntegration.identifier)  # noqa: SLF001

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        active = _active_integrations(sentry_mock)

    assert StarletteIntegration.identifier not in active


def test_forced_lean_capture_warns_that_traces_sample_rate_gets_no_request_transactions(
    sentry_mock: SentryTestTransport,
) -> None:
    with pytest.warns(UserWarning, match="Sentry tracing"):
        config = _build_config(sentry_mock, sentry_lean_error_capture=True, sentry_traces_sample_rate=1.0)

    assert _sentry_init_kwargs(config)["disabled_integrations"] == [StarletteIntegration, FastApiIntegration]


@pytest.mark.parametrize("integration", [StarletteIntegration, FastApiIntegration])
def test_default_keeps_a_supplied_starlette_integration(
    sentry_mock: SentryTestTransport, integration: type[StarletteIntegration]
) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        active = _active_integrations(sentry_mock, sentry_integrations=[integration()])

    assert integration.identifier in active


def test_forced_lean_capture_warns_that_a_supplied_starlette_integration_is_dropped(
    sentry_mock: SentryTestTransport,
) -> None:
    with pytest.warns(UserWarning, match="FastApiIntegration"):
        _build_config(sentry_mock, sentry_lean_error_capture=True, sentry_integrations=[FastApiIntegration()])


def test_integration_capture_does_not_warn_about_lean_settings(sentry_mock: SentryTestTransport) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        _build_config(
            sentry_mock,
            sentry_lean_error_capture=False,
            sentry_traces_sample_rate=1.0,
            sentry_integrations=[StarletteIntegration()],
        )


def _build_fastmcp_config(transport: SentryTestTransport, **overrides: typing.Any) -> FastMcpConfig:  # noqa: ANN401
    application: FastMCP[typing.Any] = FastMCP()

    @application.custom_route("/boom", methods=["GET"])
    async def boom(_: Request) -> JSONResponse:
        message = "boom"
        raise RuntimeError(message)

    @application.tool
    def add(a: int, b: int) -> int:
        message = f"tool boom {a + b}"
        raise RuntimeError(message)

    @application.custom_route("/integrations", methods=["GET"])
    async def integrations(_: Request) -> JSONResponse:
        return JSONResponse(sorted(sentry_sdk.get_client().integrations))

    return FastMcpConfig(
        service_environment="test",
        sentry_dsn="https://testdsn@localhost/1",
        sentry_additional_params={"transport": transport},
        prometheus_metrics_path="",
        application=application,
        **overrides,
    )


def test_lean_capture_is_the_default_on_fastmcp_while_tracing_is_off(sentry_mock: SentryTestTransport) -> None:
    bootstrapper = FastMcpBootstrapper(bootstrap_config=_build_fastmcp_config(sentry_mock))
    application = bootstrapper.bootstrap()
    with TestClient(application.http_app(), raise_server_exceptions=False) as test_client:
        active = test_client.get("/integrations").json()
        response = test_client.get("/boom?page=2")

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert StarletteIntegration.identifier not in active
    [event] = _error_events(sentry_mock)
    assert event["request"]["url"] == "http://testserver/boom"
    assert event["request"]["query_string"] == "page=2"
    assert event["transaction"] == "/boom"


def test_fastmcp_lean_capture_teardown_restores_http_app(sentry_mock: SentryTestTransport) -> None:
    bootstrapper = FastMcpBootstrapper(bootstrap_config=_build_fastmcp_config(sentry_mock))
    application = bootstrapper.bootstrap()
    assert "http_app" in vars(application)

    bootstrapper.teardown()

    assert "http_app" not in vars(application)


def test_fastmcp_lean_capture_turned_off_leaves_http_app_alone(sentry_mock: SentryTestTransport) -> None:
    bootstrapper = FastMcpBootstrapper(
        bootstrap_config=_build_fastmcp_config(sentry_mock, sentry_lean_error_capture=False)
    )
    application = bootstrapper.bootstrap()
    with TestClient(application.http_app()) as test_client:
        active = test_client.get("/integrations").json()
    bootstrapper.teardown()

    assert "http_app" not in vars(application)
    assert StarletteIntegration.identifier in active


@pytest.mark.parametrize("lean_error_capture", [True, False])
def test_one_event_per_failing_fastmcp_tool_call(sentry_mock: SentryTestTransport, lean_error_capture: bool) -> None:
    bootstrapper = FastMcpBootstrapper(
        bootstrap_config=_build_fastmcp_config(sentry_mock, sentry_lean_error_capture=lean_error_capture)
    )
    application = bootstrapper.bootstrap()
    with TestClient(application.http_app(stateless_http=True, json_response=True)) as test_client:
        response = test_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "add", "arguments": {"a": 1, "b": 2}},
            },
            headers={"accept": "application/json, text/event-stream"},
        )
    bootstrapper.teardown()

    assert response.json()["result"]["isError"] is True
    [event] = _error_events(sentry_mock)
    assert event["exception"]["values"][-1]["value"] == "tool boom 3"
    assert event["request"]["url"] == "http://testserver/mcp"


async def _respond_with(status_code: int, _: Request, __: Exception) -> Response:
    return Response(status_code=status_code)


def test_lean_capture_reports_through_a_partial_exception_handler(sentry_mock: SentryTestTransport) -> None:
    config = _build_fastmcp_config(sentry_mock)

    @config.application.custom_route("/carries-503", methods=["GET"])
    async def carries_503(_: Request) -> JSONResponse:
        raise CarriesUnavailableStatusError

    bootstrapper = FastMcpBootstrapper(bootstrap_config=config)
    http_application = bootstrapper.bootstrap().http_app()
    http_application.add_exception_handler(
        CarriesUnavailableStatusError, functools.partial(_respond_with, status.HTTP_503_SERVICE_UNAVAILABLE)
    )
    with TestClient(http_application) as test_client:
        response = test_client.get("/carries-503")
    bootstrapper.teardown()

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert _exception_types(sentry_mock) == ["CarriesUnavailableStatusError"]


async def test_lean_capture_runs_a_sync_exception_handler_in_a_worker_thread(sentry_mock: SentryTestTransport) -> None:
    FastAPIBootstrapper(bootstrap_config=_build_config(sentry_mock)).bootstrap()
    handler_threads: list[threading.Thread] = []

    def respond(_: Request, __: Exception) -> Response:
        handler_threads.append(threading.current_thread())
        return Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    response = await _reporting_server_errors(respond)(AsyncMock(), CarriesUnavailableStatusError())

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert handler_threads != [threading.current_thread()]
    assert _exception_types(sentry_mock) == ["CarriesUnavailableStatusError"]
