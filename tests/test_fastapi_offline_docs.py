from http import HTTPStatus

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lite_bootstrap.fastapi_offline_docs.main import enable_offline_docs


def test_fastapi_offline_docs() -> None:
    docs_url = "/api/n/docs"
    redoc_url = "/api/k/redoc"
    static_files_handler = "/static2"

    app = FastAPI(title="Tests", docs_url=docs_url, redoc_url=redoc_url)
    enable_offline_docs(app, static_files_handler=static_files_handler)

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
    app: FastAPI = FastAPI(title="Tests", root_path="/some-root-path")
    enable_offline_docs(app)

    with TestClient(app, root_path="/some-root-path") as client:
        resp = client.get("/docs")
        assert resp.status_code == HTTPStatus.OK
        assert "/some-root-path/static/swagger-ui.css" in resp.text
        assert "/some-root-path/static/swagger-ui-bundle.js" in resp.text


def test_fastapi_offline_docs_raises_without_openapi_url() -> None:
    app = FastAPI(openapi_url=None)

    with pytest.raises(RuntimeError, match="No app.openapi_url specified"):
        enable_offline_docs(app)
