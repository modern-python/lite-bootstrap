from http import HTTPStatus

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lite_bootstrap.helpers.fastapi_helpers import enable_offline_docs


def test_fastapi_offline_docs() -> None:
    docs_url = "/api/n/docs"
    redoc_url = "/api/k/redoc"
    static_files_handler = "/static2"

    app = FastAPI(title="Tests", docs_url=docs_url, redoc_url=redoc_url)
    enable_offline_docs(app, static_path=static_files_handler)

    with TestClient(app) as client:
        resp = client.get(docs_url)
        assert resp.status_code == HTTPStatus.OK
        assert f'<link type="text/css" rel="stylesheet" href="{static_files_handler}/swagger-ui.css">' in resp.text
        assert f'<script src="{static_files_handler}/swagger-ui-bundle.js">' in resp.text

        resp = client.get(redoc_url)
        assert resp.status_code == HTTPStatus.OK
        assert f'<script src="{static_files_handler}/redoc.standalone.js">' in resp.text

        resp = client.get("/docs/oauth2-redirect")
        assert resp.status_code == HTTPStatus.OK


def test_fastapi_offline_docs_root_path() -> None:
    app = FastAPI(
        title="Tests",
        root_path="/some-root-path",
        docs_url="/custom_docs",
        swagger_ui_oauth2_redirect_url=None,
    )
    enable_offline_docs(app, static_path="/static")

    with TestClient(app, root_path="/some-root-path") as client:
        response = client.get("/custom_docs")
        assert response.status_code == HTTPStatus.OK
        assert "/some-root-path/static/swagger-ui.css" in response.text
        assert "/some-root-path/static/swagger-ui-bundle.js" in response.text
        assert "oauth2RedirectUrl" not in response.text

        response = client.get("/some-root-path/static/swagger-ui.css")
        assert response.status_code == HTTPStatus.OK

        response = client.get("/redoc")
        assert response.status_code == HTTPStatus.OK
        assert "/some-root-path/static/redoc.standalone.js" in response.text
        assert "/some-root-path/openapi.json" in response.text


@pytest.mark.parametrize(
    "swagger_setting",
    [
        '"clientId": "public-demo"',
        '"usePkceWithAuthorizationCodeGrant": true',
        '"persistAuthorization": true',
        "oauth2RedirectUrl: window.location.origin + '/api/docs/oauth2-redirect'",
    ],
)
def test_offline_swagger_preserves_native_settings(swagger_setting: str) -> None:
    app = FastAPI(
        swagger_ui_init_oauth={"clientId": "public-demo", "usePkceWithAuthorizationCodeGrant": True},
        swagger_ui_parameters={"persistAuthorization": True},
    )
    with TestClient(app, root_path="/api") as client:
        native_response = client.get("/docs")

    enable_offline_docs(app, static_path="/static")
    with TestClient(app, root_path="/api") as client:
        offline_response = client.get("/docs")

    assert native_response.status_code == offline_response.status_code == HTTPStatus.OK
    assert swagger_setting in native_response.text
    assert swagger_setting in offline_response.text


def test_fastapi_offline_docs_raises_without_openapi_url() -> None:
    app = FastAPI(openapi_url=None)

    with pytest.raises(RuntimeError, match=r"No app.openapi_url specified"):
        enable_offline_docs(app, static_path="/static")


def test_offline_docs_rejects_unsafe_root_path() -> None:
    malicious_root = "/foo</script><script>alert(1)</script>"
    app = FastAPI(title="Tests", root_path=malicious_root, docs_url="/custom_docs", redoc_url="/custom_redoc")
    enable_offline_docs(app, static_path="/static")

    with TestClient(app, root_path=malicious_root) as client:
        with pytest.warns(UserWarning, match="root_path"):
            swagger_response = client.get("/custom_docs")
        with pytest.warns(UserWarning, match="root_path"):
            redoc_response = client.get("/custom_redoc")

    assert swagger_response.status_code == HTTPStatus.OK
    assert "<script>alert(1)</script>" not in swagger_response.text
    assert "/static/swagger-ui.css" in swagger_response.text  # falls back to empty root_path

    assert redoc_response.status_code == HTTPStatus.OK
    assert "<script>alert(1)</script>" not in redoc_response.text
    assert "/static/redoc.standalone.js" in redoc_response.text  # falls back to empty root_path
