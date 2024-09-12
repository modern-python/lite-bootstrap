from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette import status

from lite_bootstrap.fastapi_bootstrap import FastAPIBootstrap
from lite_bootstrap.opentelemetry_bootstrap import OpenTelemetryBootstrap
from lite_bootstrap.sentry_bootstrap import SentryBootstrap
from tests.conftest import CustomInstrumentor


def test_fastapi_bootstrap(fastapi_app: FastAPI) -> None:
    fastapi_bootstrap = FastAPIBootstrap(
        app=fastapi_app,
        opentelemetry=OpenTelemetryBootstrap(
            endpoint="localhost",
            service_name="test_service",
            instruments=[CustomInstrumentor()],
        ),
        sentry=SentryBootstrap(sentry_dsn="https://testdsn@test.sentry.com/1"),
    )
    fastapi_bootstrap.bootstrap_init()
    fastapi_bootstrap.teardown()


def test_fastapi_bootstrap_with_request(fastapi_app: FastAPI) -> None:
    fastapi_bootstrap = FastAPIBootstrap(
        app=fastapi_app,
        opentelemetry=OpenTelemetryBootstrap(
            endpoint="",
            service_name="test_service",
            instruments=[CustomInstrumentor()],
        ),
        sentry=SentryBootstrap(sentry_dsn=""),
    )
    fastapi_bootstrap.bootstrap_init()
    response = TestClient(fastapi_app).get("/test")
    assert response.status_code == status.HTTP_200_OK

    fastapi_bootstrap.teardown()
