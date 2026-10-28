import logging
import typing
import warnings
from collections.abc import Mapping
from unittest.mock import AsyncMock

import litestar
import pytest
import sentry_sdk
from litestar import status_codes
from litestar.config.app import AppConfig
from litestar.enums import RequestEncodingType
from litestar.exceptions import InternalServerException, NotFoundException
from litestar.middleware import ASGIMiddleware
from litestar.params import Body
from litestar.testing import TestClient
from litestar.types.asgi_types import ASGIApp, Receive, Scope, Send
from sentry_sdk import integrations as sentry_integrations
from sentry_sdk.integrations.httpx import HttpxIntegration
from sentry_sdk.integrations.litestar import LitestarIntegration
from sentry_sdk.utils import transaction_from_function

from lite_bootstrap import LitestarBootstrapper, LitestarConfig
from lite_bootstrap.bootstrappers.litestar_bootstrapper import LitestarSentryInstrument
from lite_bootstrap.instruments.sentry_instrument import DEFAULT_DATA_COLLECTION
from tests.conftest import SentryTestTransport


std_logger = logging.getLogger(__name__)


class MappedToNotFoundError(Exception):
    pass


class MappedToUnavailableError(Exception):
    pass


class BrokenHandlerError(Exception):
    pass


class SetUserMiddleware(ASGIMiddleware):
    async def handle(self, scope: Scope, receive: Receive, send: Send, next_app: ASGIApp) -> None:
        scope["user"] = {"id": "42", "email": "user@example.com"}
        await next_app(scope, receive, send)


@litestar.get("/boom")
async def boom() -> None:
    message = "boom"
    raise RuntimeError(message)


@litestar.post("/read-body-then-boom")
async def read_body_then_boom(data: typing.Annotated[dict[str, str], Body()]) -> None:
    raise RuntimeError(data["message"])


@litestar.post("/read-form-then-boom")
async def read_form_then_boom(
    data: typing.Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED)],
) -> None:
    raise RuntimeError(data["message"])


@litestar.post("/read-raw-body-then-boom")
async def read_raw_body_then_boom(request: litestar.Request) -> None:
    raise RuntimeError((await request.body()).decode())


@litestar.post("/boom-without-reading-body")
async def boom_without_reading_body() -> None:
    message = "boom"
    raise RuntimeError(message)


@litestar.get("/mapped-404")
async def mapped_404() -> None:
    raise MappedToNotFoundError


@litestar.get("/mapped-503")
async def mapped_503() -> None:
    raise MappedToUnavailableError


@litestar.get("/http-404")
async def http_404() -> None:
    raise NotFoundException


@litestar.get("/http-500")
async def http_500() -> None:
    raise InternalServerException


@litestar.get("/broken-handler")
async def broken_handler() -> None:
    raise BrokenHandlerError


@litestar.get("/logs-then-ok")
async def logs_then_ok() -> str:
    std_logger.warning("breadcrumb from an earlier request")
    return "ok"


@litestar.get("/integrations")
async def integrations() -> list[str]:
    return sorted(sentry_sdk.get_client().integrations)


def _respond_404(_: litestar.Request, __: Exception) -> litestar.Response[None]:
    return litestar.Response(None, status_code=status_codes.HTTP_404_NOT_FOUND)


def _respond_503(_: litestar.Request, __: Exception) -> litestar.Response[None]:
    return litestar.Response(None, status_code=status_codes.HTTP_503_SERVICE_UNAVAILABLE)


def _fail_to_respond(_: litestar.Request, __: Exception) -> litestar.Response[None]:
    message = "the exception handler failed"
    raise RuntimeError(message)


def _build_config(transport: SentryTestTransport, **overrides: typing.Any) -> LitestarConfig:  # noqa: ANN401
    sentry_additional_params = {"transport": transport, **overrides.pop("sentry_additional_params", {})}
    middleware = overrides.pop("middleware", [])
    return LitestarConfig(
        service_environment="test",
        sentry_dsn="https://testdsn@localhost/1",
        sentry_additional_params=sentry_additional_params,
        logging_buffer_capacity=0,
        application_config=AppConfig(
            route_handlers=[
                boom,
                read_body_then_boom,
                read_form_then_boom,
                read_raw_body_then_boom,
                boom_without_reading_body,
                mapped_404,
                mapped_503,
                http_404,
                http_500,
                broken_handler,
                logs_then_ok,
                integrations,
            ],
            exception_handlers={
                MappedToNotFoundError: _respond_404,
                MappedToUnavailableError: _respond_503,
                BrokenHandlerError: _fail_to_respond,
            },
            middleware=middleware,
        ),
        **overrides,
    )


def _error_events(transport: SentryTestTransport) -> list[dict[str, typing.Any]]:
    events = (
        typing.cast("dict[str, typing.Any] | None", envelope.get_event()) for envelope in transport.mock_envelopes
    )
    return [event for event in events if event is not None and "exception" in event]


def _exception_types(transport: SentryTestTransport) -> list[str]:
    return [event["exception"]["values"][-1]["type"] for event in _error_events(transport)]


def _request(transport: SentryTestTransport, *paths: str, **overrides: typing.Any) -> list[int]:  # noqa: ANN401
    application = LitestarBootstrapper(bootstrap_config=_build_config(transport, **overrides)).bootstrap()
    with TestClient(app=application, raise_server_exceptions=False) as test_client:
        return [test_client.get(path).status_code for path in paths]


def _active_integrations(transport: SentryTestTransport, **overrides: typing.Any) -> list[str]:  # noqa: ANN401
    application = LitestarBootstrapper(bootstrap_config=_build_config(transport, **overrides)).bootstrap()
    with TestClient(app=application) as test_client:
        return test_client.get("/integrations").json()


def test_lean_capture_is_the_default_while_tracing_is_off(sentry_mock: SentryTestTransport) -> None:
    application = LitestarBootstrapper(
        bootstrap_config=LitestarConfig(
            sentry_dsn="https://testdsn@localhost/1",
            sentry_additional_params={"transport": sentry_mock},
            logging_buffer_capacity=0,
            application_config=AppConfig(route_handlers=[boom, integrations]),
        )
    ).bootstrap()
    with TestClient(app=application, raise_server_exceptions=False) as test_client:
        active = test_client.get("/integrations").json()
        test_client.get("/boom")

    assert LitestarIntegration.identifier not in active
    [event] = _error_events(sentry_mock)
    assert event["request"]["url"] == "http://testserver.local/boom"


@pytest.mark.parametrize(
    "tracing_overrides",
    [
        pytest.param({"sentry_traces_sample_rate": 0.0}, id="sentry_traces_sample_rate"),
        pytest.param({"sentry_additional_params": {"traces_sample_rate": 0.5}}, id="traces_sample_rate"),
        pytest.param({"sentry_additional_params": {"traces_sampler": lambda _: 0.5}}, id="traces_sampler"),
    ],
)
def test_default_keeps_the_litestar_integration_while_tracing_is_on(
    sentry_mock: SentryTestTransport, tracing_overrides: dict[str, typing.Any]
) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        active = _active_integrations(sentry_mock, **tracing_overrides)

    assert LitestarIntegration.identifier in active


def test_lean_capture_turned_off_keeps_the_litestar_integration(sentry_mock: SentryTestTransport) -> None:
    config = _build_config(sentry_mock, sentry_lean_error_capture=False)
    active = _active_integrations(sentry_mock, sentry_lean_error_capture=False)

    assert "disabled_integrations" not in _sentry_init_kwargs(config)
    assert LitestarIntegration.identifier in active


def test_lean_capture_reports_unhandled_exception_with_request_data(sentry_mock: SentryTestTransport) -> None:
    application = LitestarBootstrapper(bootstrap_config=_build_config(sentry_mock)).bootstrap()
    with TestClient(app=application, raise_server_exceptions=False) as test_client:
        response = test_client.get("/boom?page=2", headers={"x-real-ip": "10.0.0.1", "user-agent": "tests"})

    assert response.status_code == status_codes.HTTP_500_INTERNAL_SERVER_ERROR
    [event] = _error_events(sentry_mock)
    exception = event["exception"]["values"][-1]
    assert exception["type"] == "RuntimeError"
    assert (exception["mechanism"]["type"], exception["mechanism"]["handled"]) == ("litestar", False)
    assert event["request"]["method"] == "GET"
    assert event["request"]["url"] == "http://testserver.local/boom"
    assert event["request"]["query_string"] == "page=2"
    assert event["request"]["headers"]["x-real-ip"] == "[Filtered]"
    assert event["request"]["headers"]["user-agent"] == "tests"
    assert "env" not in event["request"]
    assert event["transaction"] == transaction_from_function(boom.fn)
    assert event["transaction_info"] == {"source": "component"}


def test_lean_capture_filters_cookies_through_data_collection(sentry_mock: SentryTestTransport) -> None:
    application = LitestarBootstrapper(bootstrap_config=_build_config(sentry_mock)).bootstrap()
    with TestClient(
        app=application, raise_server_exceptions=False, cookies={"theme": "dark", "session": "s3cr3t"}
    ) as test_client:
        test_client.get("/boom")

    [event] = _error_events(sentry_mock)
    assert event["request"]["cookies"] == {"theme": "dark", "session": "[Filtered]"}
    assert event["request"]["headers"]["cookie"] == "[Filtered]"


def test_lean_capture_sends_no_cookies_when_data_collection_turns_them_off(sentry_mock: SentryTestTransport) -> None:
    data_collection = {**DEFAULT_DATA_COLLECTION, "cookies": {"mode": "off"}}
    config = _build_config(sentry_mock, sentry_additional_params={"data_collection": data_collection})
    application = LitestarBootstrapper(bootstrap_config=config).bootstrap()
    with TestClient(app=application, raise_server_exceptions=False, cookies={"theme": "dark"}) as test_client:
        test_client.get("/boom")

    [event] = _error_events(sentry_mock)
    assert "cookies" not in event["request"]


@pytest.mark.parametrize(
    ("user_info", "expected_user"),
    [
        pytest.param(False, None, id="user-info-off"),
        pytest.param(True, {"id": "42", "email": "user@example.com"}, id="user-info-on"),
    ],
)
def test_lean_capture_attaches_the_scope_user_only_when_data_collection_allows_it(
    sentry_mock: SentryTestTransport, user_info: bool, expected_user: dict[str, str] | None
) -> None:
    data_collection = {**DEFAULT_DATA_COLLECTION, "user_info": user_info}
    _request(
        sentry_mock,
        "/boom",
        sentry_additional_params={"data_collection": data_collection},
        middleware=[SetUserMiddleware()],
    )

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
        pytest.param([], "/read-body-then-boom", {"json": {"message": "boom"}}, None, id="bodies-off"),
        pytest.param(
            ["incoming_request"],
            "/read-body-then-boom",
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
    config = _build_config(sentry_mock, sentry_additional_params={"data_collection": data_collection})
    application = LitestarBootstrapper(bootstrap_config=config).bootstrap()
    with TestClient(app=application, raise_server_exceptions=False) as test_client:
        test_client.post(path, **request_kwargs)

    [event] = _error_events(sentry_mock)
    assert event["request"].get("data") == expected_data


async def test_lean_capture_continues_an_incoming_sentry_trace(sentry_mock: SentryTestTransport) -> None:
    # Called without TestClient: sentry-sdk's httpx integration would overwrite the outgoing sentry-trace.
    trace_id = "771a43a4192642f0b136d5159a501700"
    application = LitestarBootstrapper(bootstrap_config=_build_config(sentry_mock)).bootstrap()
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

    await application(scope, receive, AsyncMock())  # ty: ignore[invalid-argument-type]

    [event] = _error_events(sentry_mock)
    assert event["contexts"]["trace"]["trace_id"] == trace_id


def test_lean_capture_skips_exception_mapped_to_4xx(sentry_mock: SentryTestTransport) -> None:
    assert _request(sentry_mock, "/mapped-404") == [status_codes.HTTP_404_NOT_FOUND]
    assert _error_events(sentry_mock) == []


def test_lean_capture_reports_exception_mapped_to_5xx(sentry_mock: SentryTestTransport) -> None:
    assert _request(sentry_mock, "/mapped-503") == [status_codes.HTTP_503_SERVICE_UNAVAILABLE]
    assert _exception_types(sentry_mock) == ["MappedToUnavailableError"]


def test_lean_capture_skips_client_http_exceptions(sentry_mock: SentryTestTransport) -> None:
    assert _request(sentry_mock, "/http-404", "/no-such-route") == [
        status_codes.HTTP_404_NOT_FOUND,
        status_codes.HTTP_404_NOT_FOUND,
    ]
    assert _error_events(sentry_mock) == []


def test_lean_capture_reports_server_http_exceptions(sentry_mock: SentryTestTransport) -> None:
    assert _request(sentry_mock, "/http-500") == [status_codes.HTTP_500_INTERNAL_SERVER_ERROR]
    assert _exception_types(sentry_mock) == ["InternalServerException"]


def test_lean_capture_reports_both_exceptions_when_the_handler_fails(sentry_mock: SentryTestTransport) -> None:
    assert _request(sentry_mock, "/broken-handler") == [status_codes.HTTP_500_INTERNAL_SERVER_ERROR]
    assert _exception_types(sentry_mock) == ["BrokenHandlerError", "RuntimeError"]


def test_lean_capture_keeps_breadcrumbs_to_their_own_request(sentry_mock: SentryTestTransport) -> None:
    _request(sentry_mock, "/logs-then-ok", "/boom")

    [event] = _error_events(sentry_mock)
    messages = [crumb.get("message") for crumb in event.get("breadcrumbs", {}).get("values", [])]
    assert "breadcrumb from an earlier request" not in messages


@pytest.mark.parametrize("service_debug", [False, True])
def test_lean_capture_reports_once_when_litestar_logs_the_exception(
    sentry_mock: SentryTestTransport, service_debug: bool
) -> None:
    assert _request(sentry_mock, "/boom", service_debug=service_debug) == [status_codes.HTTP_500_INTERNAL_SERVER_ERROR]
    assert _exception_types(sentry_mock) == ["RuntimeError"]


_AUTO_ENABLED_IN_THE_TEST_ENVIRONMENT: typing.Final = frozenset({"aiohttp", "httpx", "redis"})


def test_lean_capture_leaves_auto_enabling_integrations_off_and_still_reports(sentry_mock: SentryTestTransport) -> None:
    application = LitestarBootstrapper(bootstrap_config=_build_config(sentry_mock)).bootstrap()
    with TestClient(app=application, raise_server_exceptions=False) as test_client:
        active = test_client.get("/integrations").json()
        test_client.get("/boom")

    assert not _AUTO_ENABLED_IN_THE_TEST_ENVIRONMENT & set(active)
    [event] = _error_events(sentry_mock)
    assert event["request"]["url"] == "http://testserver.local/boom"


def test_integration_capture_keeps_auto_enabling_integrations(sentry_mock: SentryTestTransport) -> None:
    active = _active_integrations(sentry_mock, sentry_lean_error_capture=False)

    assert set(active) >= _AUTO_ENABLED_IN_THE_TEST_ENVIRONMENT


def test_lean_capture_replaces_the_litestar_integration(sentry_mock: SentryTestTransport) -> None:
    active = _active_integrations(sentry_mock, sentry_lean_error_capture=True)

    assert LitestarIntegration.identifier not in active
    assert "logging" in active


def _sentry_init_kwargs(config: LitestarConfig) -> Mapping[str, typing.Any]:
    return LitestarSentryInstrument(bootstrap_config=config)._build_init_params()  # noqa: SLF001


def test_lean_capture_keeps_user_disabled_integrations(sentry_mock: SentryTestTransport) -> None:
    httpx_integration = HttpxIntegration()
    config = _build_config(sentry_mock, sentry_additional_params={"disabled_integrations": [httpx_integration]})

    assert _sentry_init_kwargs(config)["disabled_integrations"] == [httpx_integration, LitestarIntegration]


def test_lean_capture_warns_when_an_earlier_init_installed_the_litestar_integration(
    sentry_mock: SentryTestTransport,
) -> None:
    sentry_integrations._installed_integrations.add(LitestarIntegration.identifier)  # noqa: SLF001
    bootstrapper = LitestarBootstrapper(
        bootstrap_config=_build_config(sentry_mock, sentry_auto_enabling_integrations=True)
    )

    with pytest.warns(UserWarning, match="installed by an earlier sentry_sdk.init"):
        bootstrapper.bootstrap()
    bootstrapper.teardown()


def test_lean_capture_ignores_an_earlier_installed_litestar_integration_while_auto_enabling_is_off(
    sentry_mock: SentryTestTransport,
) -> None:
    sentry_integrations._installed_integrations.add(LitestarIntegration.identifier)  # noqa: SLF001

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        active = _active_integrations(sentry_mock)

    assert LitestarIntegration.identifier not in active


def test_forced_lean_capture_warns_that_traces_sample_rate_gets_no_request_transactions(
    sentry_mock: SentryTestTransport,
) -> None:
    with pytest.warns(UserWarning, match="Sentry tracing"):
        config = _build_config(sentry_mock, sentry_lean_error_capture=True, sentry_traces_sample_rate=1.0)

    assert _sentry_init_kwargs(config)["disabled_integrations"] == [LitestarIntegration]


def test_default_keeps_a_supplied_litestar_integration(sentry_mock: SentryTestTransport) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        active = _active_integrations(sentry_mock, sentry_integrations=[LitestarIntegration()])

    assert LitestarIntegration.identifier in active


def test_forced_lean_capture_warns_that_a_supplied_litestar_integration_is_dropped(
    sentry_mock: SentryTestTransport,
) -> None:
    with pytest.warns(UserWarning, match="LitestarIntegration"):
        _build_config(sentry_mock, sentry_lean_error_capture=True, sentry_integrations=[LitestarIntegration()])


def test_integration_capture_does_not_warn_about_lean_settings(sentry_mock: SentryTestTransport) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        _build_config(
            sentry_mock,
            sentry_lean_error_capture=False,
            sentry_traces_sample_rate=1.0,
            sentry_integrations=[LitestarIntegration()],
        )
