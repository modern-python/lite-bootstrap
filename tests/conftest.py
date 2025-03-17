import typing

import pytest
from fastapi import FastAPI
from opentelemetry.instrumentation.instrumentor import BaseInstrumentor  # type: ignore[attr-defined]

from lite_bootstrap.service_config import ServiceConfig


class CustomInstrumentor(BaseInstrumentor):  # type: ignore[misc]
    def instrumentation_dependencies(self) -> typing.Collection[str]:
        return []

    def _uninstrument(self, **kwargs: typing.Mapping[str, typing.Any]) -> None:
        pass


@pytest.fixture
def fastapi_app() -> FastAPI:
    return FastAPI()


@pytest.fixture
def service_config() -> ServiceConfig:
    return ServiceConfig(
        service_name="microservice",
        service_version="2.0.0",
        service_environment="test",
    )
