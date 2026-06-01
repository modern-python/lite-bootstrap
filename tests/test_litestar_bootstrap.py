import dataclasses

import litestar
import pytest
import structlog
from litestar import status_codes
from litestar.config.app import AppConfig
from litestar.params import FromPath
from litestar.testing import TestClient
from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import get_tracer_provider

from lite_bootstrap import LitestarBootstrapper, LitestarConfig
from lite_bootstrap.bootstrappers.litestar_bootstrapper import build_litestar_route_details_from_scope, build_span_name
from tests.conftest import CustomInstrumentor, SentryTestTransport, emulate_package_missing


logger = structlog.getLogger(__name__)


@pytest.fixture
def litestar_config() -> LitestarConfig:
    return LitestarConfig(
        service_name="microservice",
        service_version="2.0.0",
        service_environment="test",
        service_debug=False,
        cors_allowed_origins=["http://test"],
        health_checks_path="/custom-health/",
        opentelemetry_instrumentors=[CustomInstrumentor()],
        opentelemetry_log_traces=True,
        opentelemetry_generate_health_check_spans=False,
        prometheus_metrics_path="/custom-metrics/",
        sentry_dsn="https://testdsn@localhost/1",
        sentry_additional_params={"transport": SentryTestTransport()},
        swagger_offline_docs=True,
        logging_buffer_capacity=0,
    )


def test_litestar_bootstrap(litestar_config: LitestarConfig) -> None:
    bootstrapper = LitestarBootstrapper(bootstrap_config=litestar_config)
    application = bootstrapper.bootstrap()
    assert bootstrapper.is_bootstrapped
    logger.info("testing logging", key="value")
    assert application.cors_config
    assert application.cors_config.allow_origins == litestar_config.cors_allowed_origins

    with TestClient(app=application) as test_client:
        response = test_client.get(litestar_config.health_checks_path)
        assert response.status_code == status_codes.HTTP_200_OK
        assert response.json() == {
            "health_status": True,
            "service_name": "microservice",
            "service_version": "2.0.0",
        }

        response = test_client.get(litestar_config.prometheus_metrics_path)
        assert response.status_code == status_codes.HTTP_200_OK
        assert response.text

        response = test_client.get(litestar_config.swagger_path)
        assert response.status_code == status_codes.HTTP_200_OK
        response = test_client.get(f"{litestar_config.swagger_static_path}/swagger-ui.css")
        assert response.status_code == status_codes.HTTP_200_OK

    assert not bootstrapper.is_bootstrapped


def test_litestar_bootstrapper_not_ready() -> None:
    with emulate_package_missing("litestar"), pytest.raises(RuntimeError, match="litestar is not installed"):
        LitestarBootstrapper(bootstrap_config=LitestarConfig())


@pytest.mark.parametrize(
    "package_name",
    [
        "opentelemetry",
        "sentry_sdk",
        "structlog",
        "prometheus_client",
    ],
)
def test_litestar_bootstrapper_with_missing_instrument_dependency(
    litestar_config: LitestarConfig, package_name: str
) -> None:
    with emulate_package_missing(package_name), pytest.warns(UserWarning, match=package_name):
        LitestarBootstrapper(bootstrap_config=litestar_config)


def test_litestar_otel_span_naming(litestar_config: LitestarConfig) -> None:
    @litestar.get("/items/{item_id:int}")
    async def get_item(item_id: FromPath[int]) -> dict[str, int]:
        return {"item_id": item_id}

    config = dataclasses.replace(litestar_config, application_config=AppConfig(route_handlers=[get_item]))
    bootstrapper = LitestarBootstrapper(bootstrap_config=config)
    application = bootstrapper.bootstrap()

    tracer_provider = get_tracer_provider()
    assert isinstance(tracer_provider, SDKTracerProvider)
    exporter = InMemorySpanExporter()
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))

    with TestClient(app=application) as client:
        response = client.get("/items/42")
        assert response.status_code == status_codes.HTTP_200_OK

    spans = exporter.get_finished_spans()
    span_names = [s.name for s in spans]
    assert any("GET /items/{item_id}" in name for name in span_names)


def test_litestar_request_logger(litestar_config: LitestarConfig) -> None:
    @litestar.get("/log-test")
    async def log_handler(request: litestar.Request) -> dict[str, str]:
        request.logger.info("test log from handler", key="value")
        return {"status": "ok"}

    config = dataclasses.replace(litestar_config, application_config=AppConfig(route_handlers=[log_handler]))
    bootstrapper = LitestarBootstrapper(bootstrap_config=config)
    application = bootstrapper.bootstrap()

    with TestClient(app=application) as client:
        response = client.get("/log-test")
        assert response.status_code == status_codes.HTTP_200_OK
        assert response.json() == {"status": "ok"}


def test_build_span_name_no_route() -> None:
    assert build_span_name("GET", "") == "GET"


def test_build_litestar_route_details_from_scope_path_fallback() -> None:
    scope = {"method": "POST", "path": "/fallback/path"}
    name, attrs = build_litestar_route_details_from_scope(scope)
    assert name == "POST /fallback/path"
    assert attrs == {"http.route": "/fallback/path"}


def test_build_litestar_route_details_from_scope_no_path() -> None:
    scope = {"type": "lifespan"}
    name, attrs = build_litestar_route_details_from_scope(scope)
    assert name == "HTTP"
    assert attrs == {}
