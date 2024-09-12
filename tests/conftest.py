import typing

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse
from opentelemetry.instrumentation.instrumentor import BaseInstrumentor  # type: ignore[attr-defined]


class CustomInstrumentor(BaseInstrumentor):  # type: ignore[misc]
    def instrumentation_dependencies(self) -> typing.Collection[str]:
        return []

    def _uninstrument(self, **kwargs: typing.Mapping[str, typing.Any]) -> None:
        pass


@pytest.fixture
def fastapi_app() -> FastAPI:
    app: typing.Final = FastAPI()
    router: typing.Final = APIRouter()

    @router.get("/test")
    async def for_test_endpoint() -> JSONResponse:
        return JSONResponse(content={"key": "value"})

    app.include_router(router)
    return app
