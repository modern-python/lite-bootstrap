import pathlib
import typing

from lite_bootstrap import import_checker


if import_checker.is_fastapi_installed:
    from fastapi import FastAPI, Request
    from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html, get_swagger_ui_oauth2_redirect_html
    from fastapi.responses import HTMLResponse
    from fastapi.staticfiles import StaticFiles
    from starlette.routing import Route


def enable_offline_docs(
    app: "FastAPI",
    static_path: str,
) -> None:
    if not (app_openapi_url := app.openapi_url):
        msg = "No app.openapi_url specified"
        raise RuntimeError(msg)

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
        root_path = request.scope.get("root_path", "").rstrip("/")
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
    async def redoc_html() -> HTMLResponse:
        return get_redoc_html(
            openapi_url=app_openapi_url,
            title=f"{app.title} - ReDoc",
            redoc_js_url=f"{static_path}/redoc.standalone.js",
        )
