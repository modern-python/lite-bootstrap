import typing

from lite_bootstrap import import_checker


if import_checker.is_fastapi_opentelemetry_installed or import_checker.is_fastmcp_opentelemetry_installed:
    from opentelemetry.instrumentation.asgi import OpenTelemetryMiddleware
    from starlette._utils import get_route_path

if typing.TYPE_CHECKING:
    from starlette.types import ASGIApp, Receive, Scope, Send


class ExcludeInfrastructureTelemetry:
    def __init__(self, app: "OpenTelemetryMiddleware", excluded_paths: set[str]) -> None:
        self.app = app
        self.excluded_paths = tuple(path for value in excluded_paths if (path := value.rstrip("/")))

    async def __call__(self, scope: "Scope", receive: "Receive", send: "Send") -> None:
        if scope["type"] in ("http", "websocket"):
            path = get_route_path(scope)
            if any(path == excluded or path.startswith(excluded + "/") for excluded in self.excluded_paths):
                await self.app.app(scope, receive, send)
                return
        await self.app(scope, receive, send)


def build_opentelemetry_middleware(
    app: "ASGIApp",
    *,
    infrastructure_paths: set[str],
    **kwargs: typing.Any,  # noqa: ANN401
) -> ExcludeInfrastructureTelemetry:
    return ExcludeInfrastructureTelemetry(OpenTelemetryMiddleware(app, **kwargs), infrastructure_paths)
