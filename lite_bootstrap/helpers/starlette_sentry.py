import contextlib
import dataclasses
import inspect
import json
import typing
import urllib.parse

from lite_bootstrap import import_checker
from lite_bootstrap.instruments.sentry_instrument import (
    SENTRY_FAILED_REQUEST_STATUS_CODES,
    capture_request_exception,
    read_sentry_trace_headers,
    should_collect_request_body,
)


if typing.TYPE_CHECKING:
    from sentry_sdk import _types as sentry_types
    from starlette.routing import BaseRoute
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

if import_checker.is_starlette_installed and import_checker.is_sentry_installed:
    import sentry_sdk
    from sentry_sdk import sessions
    from sentry_sdk.data_collection import _apply_key_value_collection_filtering
    from sentry_sdk.integrations._asgi_common import _get_request_data, _RootPathInPath
    from sentry_sdk.integrations._wsgi_common import request_body_within_bounds
    from sentry_sdk.integrations.starlette import StarletteIntegration
    from sentry_sdk.utils import AnnotatedValue
    from starlette.concurrency import run_in_threadpool
    from starlette.datastructures import Headers
    from starlette.middleware.exceptions import ExceptionMiddleware
    from starlette.requests import HTTPConnection
    from starlette.routing import Host, Match, Mount, Route, WebSocketRoute


_CAPTURED_SCOPE_TYPES: typing.Final = frozenset({"http", "websocket"})
_USER_ATTRIBUTES: typing.Final = ("username", "id", "email")


@dataclasses.dataclass(slots=True)
class _ReceivedBody:
    chunks: list[bytes] = dataclasses.field(default_factory=list)
    complete: bool = False
    size: int = 0
    exceeded_limit: bool = False

    def recording(self, receive: "Receive") -> "Receive":
        async def receive_and_record() -> "Message":
            message: typing.Final = await receive()
            if message["type"] == "http.request" and not self.exceeded_limit:
                chunk = message.get("body", b"")
                self.size += len(chunk)
                if request_body_within_bounds(sentry_sdk.get_client(), self.size):
                    if chunk:
                        self.chunks.append(chunk)
                    self.complete = not message.get("more_body", False)
                else:
                    self.chunks.clear()
                    self.complete = False
                    self.exceeded_limit = True
            return message

        return receive_and_record

    def parse(self, scope: "Scope") -> typing.Any:  # noqa: ANN401
        """Return the body the application read in full, parsed as its content type says."""
        body: typing.Final = b"".join(self.chunks)
        if not (self.complete and body):
            return None
        media_type: typing.Final = Headers(scope=scope).get("content-type", "").partition(";")[0].strip().lower()
        if media_type == "application/json" or media_type.endswith("+json"):
            with contextlib.suppress(ValueError):
                return json.loads(body)
        if media_type == "application/x-www-form-urlencoded":
            return dict(urllib.parse.parse_qsl(body.decode("latin-1"), keep_blank_values=True))
        if media_type.startswith("multipart/"):
            return AnnotatedValue.removed_because_raw_data()
        return body.decode("utf-8", errors="replace")


def _read_user(scope: "Scope") -> dict[str, typing.Any]:
    user: typing.Final = scope.get("user")
    return {name: value for name in _USER_ATTRIBUTES if (value := getattr(user, name, None))}


def enrich_sentry_event_from_starlette_scope(
    event: "sentry_types.Event", scope: "Scope", received_body: _ReceivedBody | None
) -> "sentry_types.Event":
    data_collection: typing.Final = sentry_sdk.get_client().options["data_collection"]
    request_data: typing.Final = _get_request_data(scope, root_path_in_path=_RootPathInPath.EITHER)
    if cookies := _apply_key_value_collection_filtering(
        items=HTTPConnection(scope).cookies, behaviour=data_collection["cookies"]
    ):
        request_data["cookies"] = cookies
    if received_body is not None and (body := received_body.parse(scope)) is not None:
        request_data["data"] = body
    event["request"] = {**event.get("request", {}), **request_data}
    if data_collection["user_info"] and (user := _read_user(scope)):
        event.setdefault("user", user)
    return event


def _is_async_callable(handler: typing.Callable[..., typing.Any]) -> bool:
    return inspect.iscoroutinefunction(handler) or (
        callable(handler) and inspect.iscoroutinefunction(type(handler).__call__)
    )


def _reporting_server_errors(handler: typing.Callable[..., typing.Any]) -> typing.Callable[..., typing.Any]:
    is_async: typing.Final = _is_async_callable(handler)

    async def report_then_handle(connection: "HTTPConnection", exception: Exception) -> typing.Any:  # noqa: ANN401
        status_code: typing.Final = getattr(exception, "status_code", None)
        if isinstance(status_code, int) and status_code in SENTRY_FAILED_REQUEST_STATUS_CODES:
            capture_request_exception(exception, mechanism_type=StarletteIntegration.identifier, handled=True)
        if is_async:
            return await handler(connection, exception)
        return await run_in_threadpool(handler, connection, exception)

    return report_then_handle


def _report_handled_server_errors(application: "ASGIApp") -> None:
    """Report exceptions that ExceptionMiddleware turns into a 5xx response, as ``StarletteIntegration`` does.

    Starlette builds its middleware stack inside out on the first request, so the ``ExceptionMiddleware``
    below this one already holds every handler the application registered, including those added after
    bootstrap.
    """
    inner: ASGIApp | None = application
    while inner is not None and not isinstance(inner, ExceptionMiddleware):
        inner = getattr(inner, "app", None)
    if inner is None:
        return
    handlers: typing.Final = inner._exception_handlers  # noqa: SLF001
    for exception_class, handler in handlers.items():
        handlers[exception_class] = _reporting_server_errors(handler)
    status_handlers: typing.Final = inner._status_handlers  # noqa: SLF001
    for status_code, handler in status_handlers.items():
        status_handlers[status_code] = _reporting_server_errors(handler)


def _find_route_path(scope: "Scope", routes: "typing.Sequence[BaseRoute]") -> str | None:
    for route in routes:
        match, child_scope = route.matches(scope)
        if match != Match.FULL:
            continue
        if isinstance(route, Host):
            return _find_route_path({**scope, **child_scope}, route.routes)
        if isinstance(route, Mount):
            child_path = _find_route_path({**scope, **child_scope}, route.routes)
            return None if child_path is None else route.path + child_path
        if isinstance(route, (Route, WebSocketRoute)):
            return route.path
        return None
    return None


class StarletteSentryCaptureMiddleware:
    """Report request errors to Sentry without ``StarletteIntegration``, pure ASGI."""

    def __init__(self, app: "ASGIApp", routes: "typing.Sequence[BaseRoute] | None" = None) -> None:
        self.app = app
        self.routes = routes
        _report_handled_server_errors(app)

    async def __call__(self, scope: "Scope", receive: "Receive", send: "Send") -> None:
        if scope["type"] not in _CAPTURED_SCOPE_TYPES:
            await self.app(scope, receive, send)
            return

        routing_scope = dict(scope)
        received_body: _ReceivedBody | None = None
        if scope["type"] == "http" and should_collect_request_body(Headers(scope=scope).get("content-length")):
            received_body = _ReceivedBody()
            receive = received_body.recording(receive)

        with (
            sentry_sdk.isolation_scope() as sentry_scope,
            sessions.track_session(sentry_scope, session_mode="request"),
        ):
            sentry_scope.clear_breadcrumbs()
            sentry_scope.generate_propagation_context(read_sentry_trace_headers(scope["headers"]))

            def enrich(event: "sentry_types.Event", _: "sentry_types.Hint") -> "sentry_types.Event":
                event = enrich_sentry_event_from_starlette_scope(event, scope, received_body)
                if "transaction" not in event:
                    route_path = (
                        _find_route_path(routing_scope, self.routes)
                        if self.routes is not None
                        else getattr(scope.get("route"), "path", None)
                    )
                    if route_path is not None:
                        event["transaction"] = route_path
                        event["transaction_info"] = {"source": "route"}
                return event

            sentry_scope.add_event_processor(enrich)
            try:
                await self.app(scope, receive, send)
            except Exception as exception:
                capture_request_exception(exception, mechanism_type=StarletteIntegration.identifier, handled=False)
                raise
