import typing

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient as FastAPITestClient
from litestar import get
from litestar.config.app import AppConfig
from litestar.testing import TestClient as LitestarTestClient
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from starlette import status

from lite_bootstrap import FastAPIBootstrapper, FastAPIConfig, LitestarBootstrapper, LitestarConfig
from tests.conftest import in_memory_opentelemetry_metric_reader, opentelemetry_recorded_http_server_metrics


@pytest.mark.parametrize("framework", ["fastapi", "litestar"])
@pytest.mark.parametrize("external_setup", ["none", "before", "after"])
def test_metrics_only_framework_tracing_uses_only_an_existing_external_provider(
    framework: str, external_setup: str
) -> None:
    external = TracerProvider()
    exporter = InMemorySpanExporter()
    external.add_span_processor(SimpleSpanProcessor(exporter))
    if external_setup == "before":
        trace.set_tracer_provider(external)

    async def recording() -> dict[str, bool]:
        return {"recording": trace.get_current_span().is_recording()}

    config_params: dict[str, typing.Any] = {
        "opentelemetry_metrics_endpoint": "localhost:4317",
        "logging_enabled": False,
        "prometheus_metrics_path": "",
    }
    if framework == "fastapi":
        app = FastAPI()
        app.get("/recording")(recording)
        bootstrapper = FastAPIBootstrapper(bootstrap_config=FastAPIConfig(application=app, **config_params))
    else:
        config = LitestarConfig(
            application_config=AppConfig(route_handlers=[get("/recording")(recording)]), **config_params
        )
        bootstrapper = LitestarBootstrapper(bootstrap_config=config)

    try:
        with in_memory_opentelemetry_metric_reader() as reader:
            application = bootstrapper.bootstrap()
            if external_setup == "none":
                assert not isinstance(trace.get_tracer_provider(), TracerProvider)
            elif external_setup == "after":
                trace.set_tracer_provider(external)
            client_context = (
                FastAPITestClient(application) if isinstance(application, FastAPI) else LitestarTestClient(application)
            )
            with client_context as client:
                response = client.get("/recording")
                assert response.status_code == status.HTTP_200_OK
                assert response.json() == {"recording": external_setup == "before"}
                assert opentelemetry_recorded_http_server_metrics(reader)
            assert bool(exporter.get_finished_spans()) is (external_setup == "before")
    finally:
        bootstrapper.teardown()
        external.shutdown()
