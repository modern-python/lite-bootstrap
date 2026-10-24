import logging
import typing
import warnings
from collections.abc import Iterator, Mapping
from unittest.mock import AsyncMock, patch

import litestar
import pytest
import sentry_sdk
from litestar import status_codes
from litestar.config.app import AppConfig
from litestar.exceptions import InternalServerException, NotFoundException
from litestar.testing import TestClient
from sentry_sdk import integrations as sentry_integrations
from sentry_sdk.integrations.httpx import HttpxIntegration
from sentry_sdk.integrations.litestar import LitestarIntegration
from sentry_sdk.utils import transaction_from_function

from lite_bootstrap import LitestarBootstrapper, LitestarConfig
from lite_bootstrap.bootstrappers.litestar_bootstrapper import LitestarSentryInstrument
from tests.conftest import SentryTestTransport


std_logger = logging.getLogger(__name__)


@pytest.fixture(autouse=True)
def _litestar_integration_not_yet_installed() -> Iterator[None]:
    """Start each test as a fresh process would, with Sentry's LitestarIntegration not installed.

    sentry-sdk records installed integrations process-wide, and ``disabled_integrations`` cannot remove one
    that an earlier ``sentry_sdk.init`` installed. Other test modules bootstrap Litestar with it on.
    """
    identifier: typing.Final = LitestarIntegration.identifier
    registries: typing.Final = (
        sentry_integrations._processed_integrations,  # noqa: SLF001
        sentry_integrations._installed_integrations,  # noqa: SLF001
    )
    was_in: typing.Final = [identifier in registry for registry in registries]
    registries[1].discard(identifier)
    yield
    for registry, was_there in zip(registries, was_in, strict=True):
        (registry.add if was_there else registry.discard)(identifier)


class MappedToNotFoundError(Exception):
    pass


class MappedToUnavailableError(Exception):
    pass


class BrokenHandlerError(Exception):
    pass


@litestar.get("/boom")
async def boom() -> None:
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
    std_logger.info("breadcrumb from an earlier request")
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
    return LitestarConfig(
        service_environment="test",
        sentry_dsn="https://testdsn@localhost/1",
        sentry_additional_params=sentry_additional_params,
        sentry_lean_error_capture=overrides.pop("sentry_lean_error_capture", True),
        logging_buffer_capacity=0,
        application_config=AppConfig(
            route_handlers=[
                boom,
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


def test_lean_capture_reports_unhandled_exception_with_request_data(sentry_mock: SentryTestTransport) -> None:
    application = LitestarBootstrapper(bootstrap_config=_build_config(sentry_mock)).bootstrap()
    with TestClient(app=application, raise_server_exceptions=False) as test_client:
        response = test_client.get("/boom?page=2", headers={"x-real-ip": "10.0.0.1", "user-agent": "tests"})

    assert response.status_code == status_codes.HTTP_500_INTERNAL_SERVER_ERROR
    [event] = _error_events(sentry_mock)
    exception = event["exception"]["values"][-1]
    assert exception["type"] == "RuntimeError"
    assert exception["mechanism"] == {"type": "litestar", "handled": False}
    assert event["request"]["method"] == "GET"
    assert event["request"]["url"] == "http://testserver.local/boom"
    assert event["request"]["query_string"] == "page=2"
    assert event["request"]["headers"]["x-real-ip"] == "[Filtered]"
    assert event["request"]["headers"]["user-agent"] == "tests"
    assert event["transaction"] == transaction_from_function(boom.fn)
    assert event["transaction_info"] == {"source": "component"}


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


def test_lean_capture_sends_sensitive_headers_when_pii_is_allowed(sentry_mock: SentryTestTransport) -> None:
    config = _build_config(sentry_mock, sentry_additional_params={"send_default_pii": True})
    application = LitestarBootstrapper(bootstrap_config=config).bootstrap()
    with TestClient(app=application, raise_server_exceptions=False) as test_client:
        test_client.get("/boom", headers={"x-real-ip": "10.0.0.1"})

    [event] = _error_events(sentry_mock)
    assert event["request"]["headers"]["x-real-ip"] == "10.0.0.1"


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


def test_lean_capture_reports_once_when_litestar_logs_the_exception(sentry_mock: SentryTestTransport) -> None:
    assert _request(sentry_mock, "/boom", service_debug=True) == [status_codes.HTTP_500_INTERNAL_SERVER_ERROR]
    assert _exception_types(sentry_mock) == ["RuntimeError"]


def test_lean_capture_replaces_the_litestar_integration(sentry_mock: SentryTestTransport) -> None:
    application = LitestarBootstrapper(bootstrap_config=_build_config(sentry_mock)).bootstrap()
    with TestClient(app=application) as test_client:
        active = test_client.get("/integrations").json()

    assert LitestarIntegration.identifier not in active
    assert "logging" in active


def _sentry_init_kwargs(config: LitestarConfig) -> Mapping[str, typing.Any]:
    instrument: typing.Final = LitestarSentryInstrument(bootstrap_config=config)
    with patch.object(sentry_sdk, "init") as sentry_init:
        instrument.bootstrap()
    return sentry_init.call_args.kwargs


def test_default_capture_keeps_the_litestar_integration(sentry_mock: SentryTestTransport) -> None:
    config = _build_config(sentry_mock, sentry_lean_error_capture=False)

    assert "disabled_integrations" not in _sentry_init_kwargs(config)
    assert config.application_config.middleware == []
    assert config.application_config.after_exception == []


def test_lean_capture_keeps_user_disabled_integrations(sentry_mock: SentryTestTransport) -> None:
    httpx_integration = HttpxIntegration()
    config = _build_config(sentry_mock, sentry_additional_params={"disabled_integrations": [httpx_integration]})

    assert _sentry_init_kwargs(config)["disabled_integrations"] == [httpx_integration, LitestarIntegration]


def test_lean_capture_warns_when_an_earlier_init_installed_the_litestar_integration(
    sentry_mock: SentryTestTransport,
) -> None:
    sentry_integrations._installed_integrations.add(LitestarIntegration.identifier)  # noqa: SLF001
    bootstrapper = LitestarBootstrapper(bootstrap_config=_build_config(sentry_mock))

    with pytest.warns(UserWarning, match="installed by an earlier sentry_sdk.init"):
        bootstrapper.bootstrap()
    bootstrapper.teardown()


def test_lean_capture_warns_that_traces_sample_rate_gets_no_request_transactions(
    sentry_mock: SentryTestTransport,
) -> None:
    with pytest.warns(UserWarning, match="sentry_traces_sample_rate"):
        _build_config(sentry_mock, sentry_traces_sample_rate=1.0)


def test_lean_capture_warns_that_a_supplied_litestar_integration_is_dropped(
    sentry_mock: SentryTestTransport,
) -> None:
    with pytest.warns(UserWarning, match="LitestarIntegration"):
        _build_config(sentry_mock, sentry_integrations=[LitestarIntegration()])


def test_default_capture_does_not_warn_about_lean_settings(sentry_mock: SentryTestTransport) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        _build_config(
            sentry_mock,
            sentry_lean_error_capture=False,
            sentry_traces_sample_rate=1.0,
            sentry_integrations=[LitestarIntegration()],
        )
