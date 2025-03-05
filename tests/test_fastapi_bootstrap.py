from fastapi import FastAPI
from starlette import status
from starlette.testclient import TestClient

from lite_bootstrap.bootstraps.fastapi_bootstrap import (
    FastAPIBootstrap,
    FastAPIOpenTelemetryInstrument,
    FastAPISentryInstrument,
)
from tests.conftest import CustomInstrumentor


def test_fastapi_bootstrap(fastapi_app: FastAPI) -> None:
    fastapi_bootstrap = FastAPIBootstrap(
        app=fastapi_app,
        instruments=[
            FastAPIOpenTelemetryInstrument(
                endpoint="localhost",
                service_name="test_service",
                instrumentors=[CustomInstrumentor()],
            ),
            FastAPISentryInstrument(
                dsn="https://testdsn@test.sentry.com/1",
            ),
        ],
    )
    fastapi_bootstrap.bootstrap()
    fastapi_bootstrap.teardown()

    response = TestClient(fastapi_app).get("/test")
    assert response.status_code == status.HTTP_200_OK

    fastapi_bootstrap.teardown()
