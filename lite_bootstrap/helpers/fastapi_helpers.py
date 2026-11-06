import pathlib
import warnings

from lite_bootstrap import import_checker
from lite_bootstrap.exceptions import ConfigurationError
from lite_bootstrap.helpers.path import is_valid_path


if import_checker.is_fastapi_installed:
    from fastapi import FastAPI, Request
    from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
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

    docs_url = app.docs_url
    redoc_url = app.redoc_url
    if not docs_url and not redoc_url:
        return

    replaced_urls = (docs_url, redoc_url)
    app.router.routes = [
        route
        for route in app.router.routes
        # Only the auto-generated docs endpoints are plain ``Route``s with a ``path``; other route
        # types (e.g. FastAPI's ``_IncludedRouter``) lack ``.path`` and must be left untouched.
        if not (isinstance(route, Route) and route.path in replaced_urls)
    ]

    static_dir_path = pathlib.Path(__file__).parent.parent / "static/fastapi_docs"
    app.mount(static_path, StaticFiles(directory=static_dir_path), name="static")

    if docs_url:

        @app.get(docs_url, include_in_schema=False)
        async def custom_swagger_ui_html(request: Request) -> HTMLResponse:
            root_path = _safe_root_path(request.scope.get("root_path", ""))
            oauth2_redirect_url = app.swagger_ui_oauth2_redirect_url
            if oauth2_redirect_url:
                oauth2_redirect_url = f"{root_path}{oauth2_redirect_url}"
            return get_swagger_ui_html(
                openapi_url=f"{root_path}{app_openapi_url}",
                title=f"{app.title} - Swagger UI",
                oauth2_redirect_url=oauth2_redirect_url,
                init_oauth=app.swagger_ui_init_oauth,
                swagger_ui_parameters=app.swagger_ui_parameters,
                swagger_js_url=f"{root_path}{static_path}/swagger-ui-bundle.js",
                swagger_css_url=f"{root_path}{static_path}/swagger-ui.css",
            )

    if redoc_url:

        @app.get(redoc_url, include_in_schema=False)
        async def redoc_html(request: Request) -> HTMLResponse:
            root_path = _safe_root_path(request.scope.get("root_path", ""))
            return get_redoc_html(
                openapi_url=f"{root_path}{app_openapi_url}",
                title=f"{app.title} - ReDoc",
                redoc_js_url=f"{root_path}{static_path}/redoc.standalone.js",
            )
