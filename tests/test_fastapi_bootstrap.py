import contextlib
import dataclasses
import json
import logging
import typing
import uuid
import warnings
from unittest.mock import patch

import fastapi
import pytest
import structlog
from starlette import status
from starlette.testclient import TestClient

from lite_bootstrap import FastAPIBootstrapper, FastAPIConfig, import_checker
from lite_bootstrap.bootstrappers import fastapi_bootstrapper
from lite_bootstrap.exceptions import ConfigurationError, InstrumentDependencyMissingWarning
from lite_bootstrap.types import UNSET
from tests.conftest import CustomInstrumentor, SentryTestTransport, emulate_package_missing, warning_source_files


logger = structlog.getLogger(__name__)
std_logger = logging.getLogger()


@pytest.fixture
def fastapi_config() -> FastAPIConfig:
    return FastAPIConfig(
        service_name="microservice",
        service_version="2.0.0",
        service_environment="test",
        service_debug=False,
        cors_allowed_origins=["http://test"],
        health_checks_path="/custom-health/",
        logging_buffer_capacity=0,
        opentelemetry_instrumentors=[CustomInstrumentor()],
        opentelemetry_log_traces=True,
        opentelemetry_generate_health_check_spans=False,
        prometheus_metrics_path="/custom-metrics/",
        sentry_dsn="https://testdsn@localhost/1",
        sentry_additional_params={"transport": SentryTestTransport()},
        swagger_offline_docs=True,
    )


def _instrument_app_kwargs(config: FastAPIConfig) -> dict[str, typing.Any]:
    """Bootstrap with FastAPIInstrumentor stubbed, and return what it was handed."""
    with patch.object(fastapi_bootstrapper, "FastAPIInstrumentor") as mock_instrumentor:
        bootstrapper = FastAPIBootstrapper(bootstrap_config=config)
        bootstrapper.bootstrap()
        try:
            return mock_instrumentor.instrument_app.call_args.kwargs
        finally:
            bootstrapper.teardown()


def test_fastapi_opentelemetry_exclude_spans_defaults_to_recording_them(fastapi_config: FastAPIConfig) -> None:
    """The default keeps every span a trace view shows today; dropping two of three is opt-in."""
    assert _instrument_app_kwargs(fastapi_config)["exclude_spans"] == []


def test_fastapi_opentelemetry_exclude_spans_reaches_the_instrumentor(fastapi_config: FastAPIConfig) -> None:
    config = dataclasses.replace(fastapi_config, opentelemetry_exclude_spans=["receive", "send"])

    assert _instrument_app_kwargs(config)["exclude_spans"] == ["receive", "send"]


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


def test_fastapi_bootstrapper_apps_and_kwargs_warning(fastapi_config: FastAPIConfig) -> None:
    with pytest.warns(UserWarning, match="application_kwargs must be used without application") as caught:
        dataclasses.replace(fastapi_config, application=fastapi.FastAPI(), application_kwargs={"title": "some title"})

    assert caught[0].filename == __file__


@pytest.mark.parametrize(
    "package_name",
    [
        "opentelemetry",
        "sentry_sdk",
        "structlog",
        "prometheus_fastapi_instrumentator",
    ],
)
def test_fastapi_bootstrapper_with_missing_instrument_dependency(
    fastapi_config: FastAPIConfig, package_name: str
) -> None:
    with emulate_package_missing(package_name), pytest.warns(UserWarning, match=package_name):
        FastAPIBootstrapper(bootstrap_config=fastapi_config)


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


def test_fastapi_config_inherits_otel_insecure_warning() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        FastAPIConfig(
            opentelemetry_endpoint="http://collector.example.com:4317",
            opentelemetry_insecure=True,
        )
    matching = [w for w in caught if "unencrypted" in str(w.message)]
    assert matching, [str(w.message) for w in caught]


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
def _bootstrapped(config: FastAPIConfig) -> typing.Iterator["fastapi.FastAPI"]:
    bootstrapper = FastAPIBootstrapper(bootstrap_config=config)
    try:
        yield bootstrapper.bootstrap()
    finally:
        bootstrapper.teardown()


@contextlib.contextmanager
def _bootstrapped_with_route(config: FastAPIConfig) -> typing.Iterator["fastapi.FastAPI"]:
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
    config = dataclasses.replace(fastapi_config, fastapi_logging_middleware_enabled=True)
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
    config = dataclasses.replace(fastapi_config, fastapi_logging_middleware_enabled=True)
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
    config = dataclasses.replace(fastapi_config, fastapi_logging_middleware_enabled=True)
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
    config = dataclasses.replace(fastapi_config, fastapi_logging_middleware_enabled=True)
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
    config = dataclasses.replace(fastapi_config, fastapi_logging_middleware_enabled=True)
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
