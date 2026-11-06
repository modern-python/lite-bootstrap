import contextlib
import dataclasses
import json
import logging
import re
import typing
import uuid
import warnings
from collections.abc import AsyncGenerator, Generator
from unittest.mock import patch

import fastapi
import pytest
import structlog
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.metrics import get_meter_provider
from opentelemetry.sdk.metrics import MeterProvider as SDKMeterProvider
from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, get_tracer_provider
from starlette import status
from starlette.testclient import TestClient

from lite_bootstrap import FastAPIBootstrapper, FastAPIConfig, FastMcpConfig, import_checker
from lite_bootstrap.bootstrappers import fastapi_bootstrapper
from lite_bootstrap.exceptions import ConfigurationError, InstrumentDependencyMissingWarning
from lite_bootstrap.instruments.healthchecks_instrument import HealthProbe
from lite_bootstrap.types import UNSET
from tests.conftest import (
    HEALTH_PROBE_CASES,
    CustomInstrumentor,
    SentryTestTransport,
    capture_probe_warnings,
    emulate_package_missing,
    emulate_package_missing_with_module_reload,
    failed_probe_names,
    in_memory_opentelemetry_metric_reader,
    opentelemetry_recorded_http_server_metrics,
    prometheus_recorded_path,
    prometheus_request_count,
    unregister_prometheus_request_metrics,
    warning_source_files,
)


logger = structlog.getLogger(__name__)
std_logger = logging.getLogger()


@pytest.mark.parametrize("config_class", [FastAPIConfig, FastMcpConfig])
def test_config_rejects_comma_in_opentelemetry_excluded_url(
    config_class: type[FastAPIConfig] | type[FastMcpConfig],
) -> None:
    pattern = r"/v\d{1,2}/ping$"
    with pytest.raises(ConfigurationError, match=re.escape(repr(pattern))):
        config_class(opentelemetry_excluded_urls=[pattern])


def test_origins_only_cors_allows_json_post_preflight() -> None:
    origin = "https://a.example"
    config = FastAPIConfig(cors_allowed_origins=[origin])
    application = FastAPIBootstrapper(bootstrap_config=config).bootstrap()

    with TestClient(application) as client:
        response = client.options(
            "/x",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )

    assert response.is_success
    assert response.headers["access-control-allow-origin"] == origin
    assert "POST" in response.headers["access-control-allow-methods"].split(", ")
    assert "content-type" in response.headers["access-control-allow-headers"].lower().split(", ")


@pytest.fixture
def fastapi_config() -> FastAPIConfig:
    return FastAPIConfig(
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
    )


def test_fastapi_exports_user_shutdown_span_and_preserves_lifespan_state() -> None:
    @contextlib.asynccontextmanager
    async def lifespan(_app: fastapi.FastAPI) -> AsyncGenerator[dict[str, str]]:
        yield {"service": "ready"}
        with get_tracer_provider().get_tracer(__name__).start_as_current_span("user-shutdown"):
            pass

    app = fastapi.FastAPI(lifespan=lifespan)

    @app.get("/state")
    async def read_state(request: fastapi.Request) -> str:
        return request.state.service

    bootstrapper = FastAPIBootstrapper(bootstrap_config=FastAPIConfig(application=app, opentelemetry_log_traces=True))
    application = bootstrapper.bootstrap()
    provider = get_tracer_provider()
    assert isinstance(provider, SDKTracerProvider)
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    with TestClient(application) as client:
        assert client.get("/state").json() == "ready"

    assert "user-shutdown" in [span.name for span in exporter.get_finished_spans()]
    assert not bootstrapper.is_bootstrapped


def _instrument_app_kwargs(config: FastAPIConfig) -> dict[str, typing.Any]:
    """Bootstrap with FastAPIInstrumentor stubbed, and return what it was handed."""
    with patch.object(fastapi_bootstrapper, "FastAPIInstrumentor") as mock_instrumentor:
        bootstrapper = FastAPIBootstrapper(bootstrap_config=config)
        bootstrapper.bootstrap()
        try:
            return mock_instrumentor.instrument_app.call_args.kwargs
        finally:
            bootstrapper.teardown()


def test_fastapi_opentelemetry_exclude_spans_defaults_to_dropping_the_event_spans(
    fastapi_config: FastAPIConfig,
) -> None:
    assert _instrument_app_kwargs(fastapi_config)["exclude_spans"] == ["receive", "send"]


def test_fastapi_opentelemetry_exclude_spans_reaches_the_instrumentor(fastapi_config: FastAPIConfig) -> None:
    config = dataclasses.replace(fastapi_config, opentelemetry_exclude_spans=[])

    assert _instrument_app_kwargs(config)["exclude_spans"] == []


def test_fastapi_bootstrap(fastapi_config: FastAPIConfig) -> None:
    bootstrapper = FastAPIBootstrapper(bootstrap_config=fastapi_config)
    application = bootstrapper.bootstrap()
    assert bootstrapper.is_bootstrapped
    logger.info("testing logging", key="value")

    with TestClient(application) as test_client:
        response = test_client.get(fastapi_config.health_checks_path)
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"health_status": True, "service_name": "microservice", "service_version": "2.0.0"}

        response = test_client.get(fastapi_config.prometheus_metrics_path)
        assert response.status_code == status.HTTP_200_OK
        assert response.text

        response = test_client.get(str(application.docs_url))
        assert response.status_code == status.HTTP_200_OK
        assert response.text

        response = test_client.get(str(application.redoc_url))
        assert response.status_code == status.HTTP_200_OK
        assert response.text

    assert not bootstrapper.is_bootstrapped


def test_fastapi_bootstrap_std_logger(fastapi_config: FastAPIConfig, capsys: pytest.CaptureFixture[str]) -> None:
    bootstrapper = FastAPIBootstrapper(bootstrap_config=fastapi_config)
    application = bootstrapper.bootstrap()

    @application.get("/")
    async def home() -> str:
        std_logger.info("std logger")
        logger.info("structlog logger")
        return ""

    with TestClient(application) as test_client:
        test_client.get("/")

    stdout = capsys.readouterr().out
    assert '"event":"std logger","level":"info","logger":"root"' in stdout
    assert stdout.count("std logger") == 1


def test_fastapi_bootstrapper_not_ready() -> None:
    with emulate_package_missing("fastapi"), pytest.raises(RuntimeError, match="fastapi is not installed"):
        FastAPIBootstrapper(bootstrap_config=FastAPIConfig())


def test_fastapi_bootstrapper_docs_url_differ(fastapi_config: FastAPIConfig) -> None:
    new_config = dataclasses.replace(fastapi_config, application=fastapi.FastAPI(docs_url="/custom-docs/"))
    bootstrapper = FastAPIBootstrapper(bootstrap_config=new_config)
    with pytest.warns(UserWarning, match="swagger_path differs from docs_url"):
        bootstrapper.bootstrap()
    bootstrapper.teardown()


def test_offline_docs_respect_both_disabled_routes() -> None:
    app = fastapi.FastAPI(docs_url=None, redoc_url=None)
    config = FastAPIConfig(application=app, swagger_offline_docs=True)
    bootstrapper = FastAPIBootstrapper(bootstrap_config=config)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        application = bootstrapper.bootstrap()

    with TestClient(application) as client:
        assert client.get("/docs").status_code == status.HTTP_404_NOT_FOUND
        assert client.get("/redoc").status_code == status.HTTP_404_NOT_FOUND

    assert not caught


def test_offline_swagger_ui_works_with_redoc_disabled() -> None:
    app = fastapi.FastAPI(redoc_url=None)
    config = FastAPIConfig(application=app, swagger_offline_docs=True)

    with TestClient(FastAPIBootstrapper(bootstrap_config=config).bootstrap()) as client:
        response = client.get("/docs")
        assert response.status_code == status.HTTP_200_OK
        assert f"{config.swagger_static_path}/swagger-ui-bundle.js" in response.text
        assert client.get("/redoc").status_code == status.HTTP_404_NOT_FOUND


def test_fastapi_bootstrapper_apps_and_kwargs_warning(fastapi_config: FastAPIConfig) -> None:
    with pytest.warns(UserWarning, match="application_kwargs must be used without application") as caught:
        dataclasses.replace(fastapi_config, application=fastapi.FastAPI(), application_kwargs={"title": "some title"})

    assert caught[0].filename == __file__


@pytest.mark.parametrize(
    "package_name",
    [
        "opentelemetry.trace",
        "sentry_sdk",
        "structlog",
        "prometheus_fastapi_instrumentator",
    ],
)
def test_fastapi_bootstrapper_with_missing_instrument_dependency(
    fastapi_config: FastAPIConfig, package_name: str
) -> None:
    with emulate_package_missing(package_name), pytest.warns(UserWarning, match=package_name.removesuffix(".trace")):
        FastAPIBootstrapper(bootstrap_config=fastapi_config)


@pytest.mark.parametrize("metrics_path", [None, "/custom"])
def test_fastapi_missing_prometheus_is_quiet_only_for_the_default_path(
    metrics_path: str | None, caplog: pytest.LogCaptureFixture
) -> None:
    config = FastAPIConfig() if metrics_path is None else FastAPIConfig(prometheus_metrics_path=metrics_path)
    with emulate_package_missing("prometheus_client"), warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        bootstrapper = FastAPIBootstrapper(bootstrap_config=config)
    try:
        assert not any(
            isinstance(instrument, fastapi_bootstrapper.FastAPIPrometheusInstrument)
            for instrument in bootstrapper.instruments
        )
        if metrics_path is None:
            assert not caught
            assert not caplog.records
            assert any(
                instrument is fastapi_bootstrapper.FastAPIPrometheusInstrument
                for instrument, _reason in bootstrapper.skipped_instruments
            )
        else:
            assert [warning.category for warning in caught] == [InstrumentDependencyMissingWarning]
            assert "prometheus" in str(caught[0].message)
            assert "prometheus" in caplog.text
    finally:
        bootstrapper.teardown()


def test_fastapi_bootstrapper_runs_without_sentry_sdk(fastapi_config: FastAPIConfig) -> None:
    with emulate_package_missing_with_module_reload(
        "sentry_sdk",
        ["lite_bootstrap.instruments.sentry_instrument", "lite_bootstrap.bootstrappers.fastapi_bootstrapper"],
    ):
        with pytest.warns(UserWarning, match="sentry_sdk"):
            bootstrapper = fastapi_bootstrapper.FastAPIBootstrapper(bootstrap_config=fastapi_config)
        bootstrapper.bootstrap()
        bootstrapper.teardown()


def test_second_fastapi_bootstrapper_on_same_app_warns_not_stacks(fastapi_config: FastAPIConfig) -> None:
    application = fastapi.FastAPI()
    config_a = dataclasses.replace(fastapi_config, application=application)
    FastAPIBootstrapper(bootstrap_config=config_a)
    lifespan_after_first = application.router.lifespan_context

    config_b = dataclasses.replace(fastapi_config, application=application)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        FastAPIBootstrapper(bootstrap_config=config_b)

    matching = [w for w in caught if "already has a lite-bootstrap teardown hook" in str(w.message)]
    assert matching, "expected warning about existing lite-bootstrap teardown hook"
    assert application.router.lifespan_context is lifespan_after_first, (
        "second bootstrapper must not re-wrap the lifespan"
    )


def test_app_property_raises_when_application_unset() -> None:
    # Build a config and forcibly reset application to UNSET to simulate the
    # invariant violation `FastAPIConfig.app` guards.
    config = FastAPIConfig()
    object.__setattr__(config, "application", UNSET)
    with pytest.raises(TypeError, match="application is UNSET"):
        _ = config.app


@pytest.mark.parametrize(
    ("config_kwargs", "expected_debug"),
    [
        pytest.param({}, False, id="default"),
        pytest.param({"service_debug": True}, True, id="service-debug-on"),
    ],
)
def test_built_app_debug_follows_service_debug(config_kwargs: dict[str, typing.Any], expected_debug: bool) -> None:
    assert FastAPIConfig(**config_kwargs).app.debug is expected_debug


def test_user_supplied_app_keeps_title_version_debug() -> None:
    user_app = fastapi.FastAPI(title="user-title", version="9.9.9", debug=False)
    config = FastAPIConfig(
        application=user_app,
        service_name="lite-name",
        service_version="1.0.0",
        service_debug=True,
    )
    assert config.application is user_app
    assert user_app.title == "user-title"
    assert user_app.version == "9.9.9"
    assert user_app.debug is False


def test_second_fastapi_bootstrapper_bootstrap_raises(fastapi_config: FastAPIConfig) -> None:
    application = fastapi.FastAPI()
    first = FastAPIBootstrapper(bootstrap_config=dataclasses.replace(fastapi_config, application=application))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        second = FastAPIBootstrapper(bootstrap_config=dataclasses.replace(fastapi_config, application=application))

    try:
        first.bootstrap()
        routes_after_first = len(application.routes)

        with pytest.raises(ConfigurationError, match="FastAPIBootstrapper"):
            second.bootstrap()

        assert len(application.routes) == routes_after_first, (
            "a refused second bootstrap must not register duplicate routes"
        )
    finally:
        first.teardown()


def test_swagger_warning_points_at_the_bootstrap_call_site(fastapi_config: FastAPIConfig) -> None:
    """INVARIANT: a warning raised while an instrument bootstraps names the user's bootstrap() line.

    FastAPISwaggerInstrument.bootstrap() is called straight from the loop in
    BaseBootstrapper.bootstrap(), one frame shallower than an instrument that calls
    super().bootstrap() first. A literal stacklevel pins one of those two depths and misses the
    other, naming lite_bootstrap's own source instead. This test and the OpenTelemetry one below
    are a pair: each covers one depth, and either passing alone proves nothing.
    """
    new_config = dataclasses.replace(fastapi_config, application=fastapi.FastAPI(docs_url="/custom-docs/"))
    bootstrapper = FastAPIBootstrapper(bootstrap_config=new_config)
    try:
        with pytest.warns(UserWarning, match="swagger_path differs from docs_url") as caught:
            bootstrapper.bootstrap()
    finally:
        bootstrapper.teardown()

    assert warning_source_files(caught, UserWarning) == [__file__]


def test_missing_exporter_warning_points_at_the_bootstrap_call_site(fastapi_config: FastAPIConfig) -> None:
    """INVARIANT: the deeper super().bootstrap() shape names the user's bootstrap() line as well.

    FastAPIOpenTelemetryInstrument.bootstrap() calls super().bootstrap() before the warning is
    raised, so the user's frame sits one deeper than for the swagger instrument above. Any
    instrument that grows or loses a super() call shifts that depth again; only a rule that finds
    the first frame outside lite_bootstrap survives it.
    """
    new_config = dataclasses.replace(fastapi_config, opentelemetry_endpoint="localhost:4317")
    bootstrapper = FastAPIBootstrapper(bootstrap_config=new_config)
    try:
        with (
            patch.object(import_checker, "is_otlp_grpc_exporter_installed", False),
            pytest.warns(InstrumentDependencyMissingWarning) as caught,
        ):
            bootstrapper.bootstrap()
    finally:
        bootstrapper.teardown()

    assert warning_source_files(caught, InstrumentDependencyMissingWarning) == [__file__]


class RecordingAccessLogger:
    """Stands in for the module-level access logger.

    Asserting through `logging_extra_processors` is not sound here: `_configure_foreign_loggers`
    registers those processors a second time inside the root handler's ProcessorFormatter, so a
    capture sees either the event dict or the already-rendered JSON depending on what an earlier
    bootstrap left in structlog's global configuration.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, typing.Any]]] = []

    def info(self, event: str, **kwargs: object) -> None:
        self.calls.append(("info", event, dict(kwargs)))

    def exception(self, event: str, **kwargs: object) -> None:
        self.calls.append(("exception", event, dict(kwargs)))


@pytest.fixture
def access_logger() -> typing.Iterator[RecordingAccessLogger]:
    recorder = RecordingAccessLogger()
    with patch.object(fastapi_bootstrapper, "fastapi_access_logger", recorder):
        yield recorder


@contextlib.contextmanager
def _bootstrapped(config: FastAPIConfig) -> Generator["fastapi.FastAPI"]:
    bootstrapper = FastAPIBootstrapper(bootstrap_config=config)
    try:
        yield bootstrapper.bootstrap()
    finally:
        bootstrapper.teardown()


@contextlib.contextmanager
def _bootstrapped_with_route(config: FastAPIConfig) -> Generator["fastapi.FastAPI"]:
    with _bootstrapped(config) as application:

        @application.post("/items/{item_id}")
        async def create_item(item_id: str, payload: dict[str, typing.Any]) -> dict[str, typing.Any]:
            return {"item_id": item_id, "echo": payload}

        yield application


def test_fastapi_access_log_is_off_by_default(
    fastapi_config: FastAPIConfig, access_logger: RecordingAccessLogger
) -> None:
    with _bootstrapped_with_route(fastapi_config) as application, TestClient(application) as test_client:
        test_client.post("/items/abc", json={"a": 1})

    assert access_logger.calls == []


def test_fastapi_access_log_records_the_request_when_enabled(
    fastapi_config: FastAPIConfig, access_logger: RecordingAccessLogger
) -> None:
    config = dataclasses.replace(fastapi_config, logging_access_log_enabled=True)
    with _bootstrapped_with_route(config) as application, TestClient(application) as test_client:
        test_client.post("/items/abc", json={"a": 1})

    assert len(access_logger.calls) == 1
    level, event, fields = access_logger.calls[0]
    assert (level, event) == ("info", "http_request")
    assert fields["http"] == {
        "method": "POST",
        "path": "/items/abc",
        "content_type": "application/json",
        "path_params": {"item_id": "abc"},
        "status_code": status.HTTP_200_OK,
    }
    assert fields["duration"] > 0


def test_fastapi_access_log_never_records_bodies(
    fastapi_config: FastAPIConfig, access_logger: RecordingAccessLogger
) -> None:
    """INVARIANT: the access log records a fixed set of metadata fields, never bodies.

    Litestar's middleware shipped this defect (54c8ad9): its defaults logged full bodies, putting
    credentials into the log. Pinning the field set, not just one secret, is what stops a later
    change quietly adding headers, cookies or a body back.
    """
    config = dataclasses.replace(fastapi_config, logging_access_log_enabled=True)
    secret = f"secret-{uuid.uuid4().hex}"
    with _bootstrapped_with_route(config) as application, TestClient(application) as test_client:
        response = test_client.post("/items/abc", json={"password": secret})
    assert secret in response.text  # the body really did carry it, both ways

    assert len(access_logger.calls) == 1
    fields = access_logger.calls[0][2]
    assert set(fields) == {"http", "duration"}
    assert set(fields["http"]) == {"method", "path", "content_type", "path_params", "status_code"}
    assert secret not in json.dumps(access_logger.calls, default=str)


@pytest.mark.parametrize(
    "path_attribute",
    ["health_checks_path", "prometheus_metrics_path", "swagger_path", "swagger_static_path"],
)
def test_fastapi_access_log_excludes_infrastructure_paths(
    fastapi_config: FastAPIConfig, access_logger: RecordingAccessLogger, path_attribute: str
) -> None:
    config = dataclasses.replace(fastapi_config, logging_access_log_enabled=True)
    with _bootstrapped_with_route(config) as application, TestClient(application) as test_client:
        test_client.get(getattr(config, path_attribute))

    assert access_logger.calls == []


def test_fastapi_access_log_excluded_paths_cover_every_sibling(fastapi_config: FastAPIConfig) -> None:
    """INVARIANT: every sibling path the policy names reaches the built exclusion set.

    ADR-0002 keeps this policy in one method and answers the rename risk with exactly this test:
    renaming a sibling field would otherwise stop the exclusion silently.
    """
    instrument = fastapi_bootstrapper.FastAPILoggingInstrument(bootstrap_config=fastapi_config)
    excluded = instrument._build_excluded_paths()  # noqa: SLF001

    for path_attribute in ("swagger_path", "swagger_static_path", "health_checks_path", "prometheus_metrics_path"):
        assert getattr(fastapi_config, path_attribute).rstrip("/") in excluded, path_attribute


def test_fastapi_access_log_keeps_lookalike_paths(
    fastapi_config: FastAPIConfig, access_logger: RecordingAccessLogger
) -> None:
    """A route merely sharing a prefix with an excluded path is still logged."""
    config = dataclasses.replace(fastapi_config, logging_access_log_enabled=True)
    lookalike_path = f"{config.health_checks_path.rstrip('/')}y"
    with _bootstrapped(config) as application:

        @application.get(lookalike_path)
        async def lookalike() -> str:
            return "not a health check"

        with TestClient(application) as test_client:
            assert test_client.get(lookalike_path).status_code == status.HTTP_200_OK

    assert len(access_logger.calls) == 1
    assert access_logger.calls[0][2]["http"]["path"] == lookalike_path


def test_fastapi_access_log_records_a_raising_request(
    fastapi_config: FastAPIConfig, access_logger: RecordingAccessLogger
) -> None:
    config = dataclasses.replace(fastapi_config, logging_access_log_enabled=True)
    with _bootstrapped(config) as application:

        @application.get("/boom")
        async def boom() -> str:
            msg = "boom"
            raise RuntimeError(msg)

        with TestClient(application) as test_client, pytest.raises(RuntimeError, match="boom"):
            test_client.get("/boom")

    assert len(access_logger.calls) == 1
    level, _, fields = access_logger.calls[0]
    assert level == "exception"
    # No response ever started, so there is no status to report.
    assert fields["http"]["status_code"] is None


def test_fastapi_otel_hands_the_instrumentor_the_meter_provider(fastapi_config: FastAPIConfig) -> None:
    """The FastAPI instrumentor builds duration histograms, which reach a no-op provider unasked."""
    config = dataclasses.replace(fastapi_config, opentelemetry_metrics_endpoint="localhost:4317")
    bootstrapper = FastAPIBootstrapper(bootstrap_config=config)

    with patch.object(fastapi_bootstrapper.FastAPIInstrumentor, "instrument_app") as mock_instrument_app:
        try:
            bootstrapper.bootstrap()
        finally:
            with patch.object(fastapi_bootstrapper.FastAPIInstrumentor, "uninstrument_app"):
                bootstrapper.teardown()

    assert mock_instrument_app.call_args.kwargs["meter_provider"] is get_meter_provider()
    assert isinstance(get_meter_provider(), SDKMeterProvider)


def test_fastapi_prometheus_excludes_infrastructure_and_user_paths() -> None:
    unregister_prometheus_request_metrics()
    suffix = uuid.uuid4().hex
    normal_path = f"/health-{suffix}/report"
    excluded_path = f"/excluded-{suffix}"
    config = FastAPIConfig(
        health_checks_path=f"/health-{suffix}",
        prometheus_metrics_path=f"/metrics-{suffix}",
        prometheus_instrumentator_additional_params={"excluded_handlers": [f"^{excluded_path}$"]},
    )

    async def items() -> list[int]:
        return [1]

    for path in (normal_path, excluded_path):
        config.app.add_api_route(path, items, methods=["GET"])
    application = FastAPIBootstrapper(bootstrap_config=config).bootstrap()
    with TestClient(application) as client:
        for path in (config.health_checks_path, config.prometheus_metrics_path, excluded_path, normal_path):
            assert client.get(path).is_success

    for path in (config.health_checks_path, config.prometheus_metrics_path, excluded_path):
        assert prometheus_request_count("http_requests_total", "handler", path) == 0
    assert prometheus_request_count("http_requests_total", "handler", normal_path) == 1


def _http_metric_sets_one_request_moves(config: FastAPIConfig) -> tuple[bool, bool]:
    """Return whether one request reached OpenTelemetry's HTTP metrics and Prometheus's, in that order."""
    path: typing.Final = f"/items-{uuid.uuid4().hex}"
    application: typing.Final = config.app
    unregister_prometheus_request_metrics()

    @application.get(path)
    async def items() -> str:
        return "ok"

    with in_memory_opentelemetry_metric_reader() as reader:
        bootstrapper = FastAPIBootstrapper(bootstrap_config=config)
        bootstrapper.bootstrap()
    try:
        with TestClient(application) as client:
            assert client.get(path).status_code == status.HTTP_200_OK
        return opentelemetry_recorded_http_server_metrics(reader), prometheus_recorded_path(path)
    finally:
        bootstrapper.teardown()


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        pytest.param({"opentelemetry_metrics_endpoint": "localhost:4317"}, (True, False), id="both-keeps-otel"),
        pytest.param(
            {
                "opentelemetry_metrics_endpoint": "http://localhost:4318/v1/metrics",
                "opentelemetry_exporter_protocol": "http",
            },
            (True, False),
            id="both-keeps-otel-over-http",
        ),
        pytest.param(
            {"opentelemetry_metrics_endpoint": "localhost:4317", "prometheus_http_metrics_enabled": True},
            (True, True),
            id="both-restored",
        ),
        pytest.param({}, (False, True), id="prometheus-alone"),
        pytest.param(
            {"opentelemetry_metrics_endpoint": "localhost:4317", "prometheus_metrics_path": ""},
            (True, False),
            id="otel-alone",
        ),
        pytest.param({"prometheus_http_metrics_enabled": False}, (False, False), id="prometheus-http-off"),
    ],
)
def test_fastapi_http_metrics_are_recorded_once(
    fastapi_config: FastAPIConfig, overrides: dict[str, typing.Any], expected: tuple[bool, bool]
) -> None:
    assert _http_metric_sets_one_request_moves(dataclasses.replace(fastapi_config, **overrides)) == expected


def test_fastapi_prometheus_keeps_http_metrics_when_the_otlp_metric_exporter_is_missing(
    fastapi_config: FastAPIConfig,
) -> None:
    config = dataclasses.replace(fastapi_config, opentelemetry_metrics_endpoint="localhost:4317")
    with (
        patch.object(import_checker, "is_otlp_grpc_exporter_installed", new=False),
        pytest.warns(InstrumentDependencyMissingWarning, match="gRPC OTLP exporter is not installed"),
    ):
        assert _http_metric_sets_one_request_moves(config) == (False, True)


def test_fastapi_prometheus_still_serves_metrics_while_opentelemetry_records_http_metrics(
    fastapi_config: FastAPIConfig,
) -> None:
    config = dataclasses.replace(fastapi_config, opentelemetry_metrics_endpoint="localhost:4317")
    with in_memory_opentelemetry_metric_reader():
        bootstrapper = FastAPIBootstrapper(bootstrap_config=config)
        application = bootstrapper.bootstrap()
    try:
        with TestClient(application) as client:
            assert client.get(config.prometheus_metrics_path).status_code == status.HTTP_200_OK
    finally:
        bootstrapper.teardown()


def _server_span_names_for(
    config: FastAPIConfig, paths: typing.Iterable[str], *, host: str = "testserver", root_path: str = ""
) -> list[str]:
    application = config.app

    @application.get("/api/custom-metrics/report")
    async def metrics_report() -> str:
        return "ok"

    @application.get("/custom-healthy")
    async def custom_healthy() -> str:
        return "ok"

    @application.get("/from-env")
    async def from_env() -> str:
        return "ok"

    bootstrapper = FastAPIBootstrapper(bootstrap_config=config)
    bootstrapped_application = bootstrapper.bootstrap()
    tracer_provider = get_tracer_provider()
    assert isinstance(tracer_provider, SDKTracerProvider)
    exporter = InMemorySpanExporter()
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))
    try:
        with TestClient(bootstrapped_application, root_path=root_path) as client:
            for path in paths:
                client.get(path, headers={"host": host}, follow_redirects=False)
    finally:
        bootstrapper.teardown()
    return [span.name for span in exporter.get_finished_spans() if span.kind == SpanKind.SERVER]


def test_fastapi_otel_excludes_derived_paths_only_where_they_match_whole_segments(
    fastapi_config: FastAPIConfig,
) -> None:
    """REGRESSION: `/custom-metrics/` was searched anywhere in the URL, silencing `/api/custom-metrics/report`."""
    span_names = _server_span_names_for(
        fastapi_config,
        ["/custom-metrics/", "/custom-health/", "/api/custom-metrics/report", "/custom-healthy"],
    )

    assert sorted(span_names) == ["GET /api/custom-metrics/report", "GET /custom-healthy"]


def test_fastapi_otel_leaves_the_health_check_untraced_by_default() -> None:
    config = FastAPIConfig(
        service_name="microservice",
        health_checks_path="/custom-health/",
        opentelemetry_log_traces=True,
    )

    assert _server_span_names_for(config, ["/custom-health/", "/custom-healthy"]) == ["GET /custom-healthy"]


def test_fastapi_otel_host_header_cannot_exclude_a_work_request(fastapi_config: FastAPIConfig) -> None:
    assert _server_span_names_for(fastapi_config, ["/custom-healthy"], host="x/custom-health") == [
        "GET /custom-healthy"
    ]


def test_fastapi_otel_excludes_health_under_root_path(fastapi_config: FastAPIConfig) -> None:
    assert _server_span_names_for(fastapi_config, ["/api/custom-health/", "/api/custom-healthy"], root_path="/api") == [
        "GET /custom-healthy"
    ]


@pytest.mark.parametrize("environment_variable", ["OTEL_PYTHON_FASTAPI_EXCLUDED_URLS", "OTEL_PYTHON_EXCLUDED_URLS"])
def test_fastapi_otel_honors_excluded_urls_from_environment(
    fastapi_config: FastAPIConfig, monkeypatch: pytest.MonkeyPatch, environment_variable: str
) -> None:
    for one_variable in ("OTEL_PYTHON_FASTAPI_EXCLUDED_URLS", "OTEL_PYTHON_EXCLUDED_URLS"):
        monkeypatch.delenv(one_variable, raising=False)
    monkeypatch.setenv(environment_variable, "/from-env")

    span_names = _server_span_names_for(fastapi_config, ["/from-env", "/custom-healthy"])

    assert span_names == ["GET /custom-healthy"]


@pytest.mark.parametrize(("probes", "expected_status", "expected_health_status", "expected_failed"), HEALTH_PROBE_CASES)
def test_fastapi_health_check_runs_probes(
    fastapi_config: FastAPIConfig,
    probes: dict[str, HealthProbe],
    expected_status: int,
    expected_health_status: bool,
    expected_failed: list[str],
) -> None:
    config = dataclasses.replace(fastapi_config, health_checks_probes=probes)
    bootstrapper = FastAPIBootstrapper(bootstrap_config=config)
    application = bootstrapper.bootstrap()
    with capture_probe_warnings() as probe_warnings, TestClient(application) as test_client:
        response = test_client.get(config.health_checks_path)

    assert response.status_code == expected_status
    assert response.json() == {
        "health_status": expected_health_status,
        "service_name": "microservice",
        "service_version": "2.0.0",
    }
    assert failed_probe_names(probe_warnings) == expected_failed


def test_built_app_title_and_version_fall_back_when_unset() -> None:
    application = FastAPIConfig().app
    assert application.title == "micro-service"
    assert application.version == "1.0.0"


def test_empty_observability_paths_disable_routes() -> None:
    config = FastAPIConfig(health_checks_path="", prometheus_metrics_path="")
    with _bootstrapped(config) as application, TestClient(application) as client:
        assert client.get("/health/").status_code == status.HTTP_404_NOT_FOUND
        assert client.get("/metrics").status_code == status.HTTP_404_NOT_FOUND
        assert client.get("/").status_code == status.HTTP_404_NOT_FOUND


def test_fastapi_docs_url_conflict_names_canonical_setting() -> None:
    with pytest.raises(ConfigurationError, match="swagger_path"):
        FastAPIConfig(application_kwargs={"docs_url": "/custom"})


def test_fastapi_shutdown_keeps_lifespan_error_when_exporter_shutdown_fails() -> None:
    primary = ValueError("user shutdown failed")

    @contextlib.asynccontextmanager
    async def lifespan(_: fastapi.FastAPI) -> AsyncGenerator[None]:
        yield
        raise primary

    config = FastAPIConfig(application=fastapi.FastAPI(lifespan=lifespan), opentelemetry_log_traces=True)
    app = FastAPIBootstrapper(config).bootstrap()
    provider = get_tracer_provider()
    with (
        patch.object(provider, "shutdown", side_effect=RuntimeError("exporter shutdown failed")),
        pytest.raises(ValueError, match="user shutdown failed") as caught,
        TestClient(app),
    ):
        pass
    assert caught.value is primary
    assert any("exporter shutdown failed" in note for note in caught.value.__notes__)


def test_fastapi_metrics_endpoint_conflict_names_canonical_setting() -> None:
    config = FastAPIConfig(prometheus_expose_additional_params={"endpoint": "/custom"})
    with pytest.raises(ConfigurationError, match="prometheus_metrics_path"):
        FastAPIBootstrapper(config).bootstrap()


@pytest.mark.parametrize("stack_already_built", [False, True])
def test_fastapi_excludes_infrastructure_temporarily_from_borrowed_tracing(stack_already_built: bool) -> None:
    app = fastapi.FastAPI()

    @app.get("/work")
    async def work() -> str:
        return "ok"

    provider = SDKTracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider, exclude_spans=["receive", "send"])
    external_builder = app.build_middleware_stack
    client = TestClient(app)
    if stack_already_built:
        assert client.get("/work").status_code == status.HTTP_200_OK
        exporter.clear()

    config = FastAPIConfig(
        application=app,
        logging_enabled=False,
        opentelemetry_log_traces=True,
        prometheus_http_metrics_enabled=False,
    )
    bootstrapper = FastAPIBootstrapper(config)
    try:
        bootstrapper.bootstrap()
        for path in (config.health_checks_path, config.prometheus_metrics_path, "/work"):
            assert client.get(path).status_code == status.HTTP_200_OK
        assert [span.name for span in exporter.get_finished_spans()] == ["GET /work"]

        bootstrapper.teardown()
        assert app.build_middleware_stack is external_builder
        exporter.clear()
        assert client.get(config.prometheus_metrics_path).status_code == status.HTTP_200_OK
        assert [span.name for span in exporter.get_finished_spans()] == [f"GET {config.prometheus_metrics_path}"]
    finally:
        bootstrapper.teardown()
        FastAPIInstrumentor.uninstrument_app(app)
        provider.shutdown()


def test_fastapi_instrumentation_failure_rolls_back_tracer_provider() -> None:
    config = FastAPIConfig(logging_enabled=False, opentelemetry_log_traces=True, opentelemetry_excluded_urls=["["])
    bootstrapper = FastAPIBootstrapper(config)
    with (
        patch.object(SDKTracerProvider, "shutdown", autospec=True, side_effect=SDKTracerProvider.shutdown) as shutdown,
        pytest.raises(re.error),
    ):
        bootstrapper.bootstrap()
    shutdown.assert_called_once_with(get_tracer_provider())
