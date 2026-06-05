import pathlib
import typing
import warnings

from lite_bootstrap import import_checker
from lite_bootstrap.exceptions import ConfigurationError
from lite_bootstrap.helpers.path import is_valid_path


if import_checker.is_fastapi_installed:
    from fastapi import FastAPI, Request
    from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html, get_swagger_ui_oauth2_redirect_html
    from fastapi.responses import HTMLResponse
    from fastapi.staticfiles import StaticFiles
    from starlette.routing import Route


def _safe_root_path(scope_root_path: str) -> str:
    """Strip trailing slash and validate against the project's path allowlist.

    An empty ``root_path`` is the normal case (no proxy prefix) and is allowed without warning.
    Any other path that fails the ``is_valid_path`` regex is rejected (falls back to empty) so
    that proxy-header-derived root paths can't inject HTML into the offline-docs response.
    """
    candidate = scope_root_path.rstrip("/")
    if not candidate:
        return ""
    if not is_valid_path(candidate):
        warnings.warn(
            f"root_path {candidate!r} contains characters outside the valid-path allowlist; "
            "falling back to empty root_path to prevent HTML injection in offline docs.",
            stacklevel=3,
        )
        return ""
    return candidate


def enable_offline_docs(
    app: "FastAPI",
    static_path: str,
) -> None:
    if not (app_openapi_url := app.openapi_url):
        msg = "No app.openapi_url specified"
        raise ConfigurationError(msg)

    docs_url: str = app.docs_url or "/docs"
    redoc_url: str = app.redoc_url or "/redoc"
    swagger_ui_oauth2_redirect_url: str = app.swagger_ui_oauth2_redirect_url or "/docs/oauth2-redirect"

    app.router.routes = [
        route
        for route in app.router.routes
        if typing.cast(Route, route).path not in (docs_url, redoc_url, swagger_ui_oauth2_redirect_url)
    ]

    static_dir_path = pathlib.Path(__file__).parent.parent / "static/fastapi_docs"
    app.mount(static_path, StaticFiles(directory=static_dir_path), name="static")

    @app.get(docs_url, include_in_schema=False)
    async def custom_swagger_ui_html(request: Request) -> HTMLResponse:
        root_path = _safe_root_path(request.scope.get("root_path", ""))
        return get_swagger_ui_html(
            openapi_url=f"{root_path}{app_openapi_url}",
            title=f"{app.title} - Swagger UI",
            oauth2_redirect_url=app.swagger_ui_oauth2_redirect_url,
            swagger_js_url=f"{root_path}{static_path}/swagger-ui-bundle.js",
            swagger_css_url=f"{root_path}{static_path}/swagger-ui.css",
        )

    @app.get(swagger_ui_oauth2_redirect_url, include_in_schema=False)
    async def swagger_ui_redirect() -> HTMLResponse:
        return get_swagger_ui_oauth2_redirect_html()

    @app.get(redoc_url, include_in_schema=False)
    async def redoc_html(request: Request) -> HTMLResponse:
        root_path = _safe_root_path(request.scope.get("root_path", ""))
        return get_redoc_html(
            openapi_url=f"{root_path}{app_openapi_url}",
            title=f"{app.title} - ReDoc",
            redoc_js_url=f"{root_path}{static_path}/redoc.standalone.js",
        )
