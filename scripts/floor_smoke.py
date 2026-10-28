"""Bootstrap smoke at the declared dependency floors.

Run against an environment resolved with `uv pip install --resolution lowest-direct`,
so every direct dependency sits at the floor `pyproject.toml` declares. Takes one
target naming the bootstrapper to exercise. Exits non-zero on failure.

An import check is not enough: half the floors this repo carries were found by a call
made during bootstrap or teardown, not by a missing module. So each target builds a
config with every instrument its extras can supply, bootstraps, exercises the calls
that set a floor, and tears down.

`InstrumentSkippedWarning` is escalated to an error, because an instrument that
degrades to a silent skip would let a too-low floor pass as success.

Not a pytest test: conftest.py hard-imports opentelemetry, sentry_sdk and structlog,
which most of these targets do not install.
"""

import asyncio
import contextlib
import sys
import typing
import warnings

from lite_bootstrap import (
    FastAPIBootstrapper,
    FastAPIConfig,
    FastMcpBootstrapper,
    FastMcpConfig,
    FastStreamBootstrapper,
    FastStreamConfig,
    FreeBootstrapper,
    FreeConfig,
    InstrumentSkippedWarning,
    LitestarBootstrapper,
    LitestarConfig,
    import_checker,
)
from lite_bootstrap.instruments.logging_factory import StructuredLogPayload, _serialize_log_to_string


if import_checker.is_opentelemetry_installed:
    from opentelemetry import trace

if import_checker.is_fastapi_installed:
    import fastapi

if import_checker.is_fastmcp_installed:
    from starlette.requests import Request
    from starlette.responses import Response

if import_checker.is_litestar_installed:
    import litestar
    from litestar.config.app import AppConfig
    from litestar.testing import TestClient

if import_checker.is_sentry_installed:
    import sentry_sdk

    class DroppingTransport(sentry_sdk.Transport):
        """Keep sentry configured without a server: teardown's flush would otherwise retry for minutes."""

        def capture_envelope(self, envelope: object) -> None:
            """Drop the envelope."""


OTLP_ENDPOINT: typing.Final = "localhost:4317"
PYROSCOPE_ENDPOINT: typing.Final = "http://localhost:4040"
SENTRY_DSN: typing.Final = "https://testdsn@localhost/1"
SENTRY_PARAMS: typing.Final = {"transport": DroppingTransport()} if import_checker.is_sentry_installed else {}
HEALTH_PATH: typing.Final = "/floor-health/"


def _emit_span() -> None:
    """Force _format_span -> ReadableSpan.to_json(indent=None) through the console exporter."""
    with trace.get_tracer("floor-smoke").start_as_current_span("floor-smoke-span"):
        pass


def _check_orjson_serializer() -> None:
    payload = StructuredLogPayload.parse(_serialize_log_to_string({"event": "floor ok", "level": "info", "n": 1}))
    assert payload is not None
    assert payload.message == "floor ok"
    assert payload.extra == {"n": 1}


async def _drive_lifespan(application: typing.Any) -> None:  # noqa: ANN401
    """Run the ASGI lifespan through startup and shutdown without a test client."""
    queue: asyncio.Queue[dict] = asyncio.Queue()
    await queue.put({"type": "lifespan.startup"})

    async def receive() -> dict:
        return await queue.get()

    async def send(message: dict) -> None:
        if message["type"] == "lifespan.startup.complete":
            await queue.put({"type": "lifespan.shutdown"})
        elif message["type"].endswith(".failed"):
            raise RuntimeError(message)

    await application({"type": "lifespan", "state": {}}, receive, send)


async def _request_status(application: typing.Any, path: str) -> int:  # noqa: ANN401
    """Send one GET through an ASGI application without a test client, which would need httpx."""
    statuses: list[int] = []

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict) -> None:
        if message["type"] == "http.response.start":
            statuses.append(message["status"])

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": [(b"host", b"floor-smoke")],
        "client": ("127.0.0.1", 1),
        "server": ("floor-smoke", 80),
        "state": {},
    }
    with contextlib.suppress(RuntimeError):
        await application(scope, receive, send)
    return statuses[0]


def _free() -> None:
    bootstrapper = FreeBootstrapper(
        bootstrap_config=FreeConfig(
            service_name="floor-smoke",
            service_version="1.0.0",
            service_environment="test",
            logging_buffer_capacity=0,
            sentry_dsn=SENTRY_DSN,
            sentry_additional_params=SENTRY_PARAMS,
            sentry_tags={"floor": "smoke"},
            pyroscope_endpoint=PYROSCOPE_ENDPOINT,
            opentelemetry_endpoint=OTLP_ENDPOINT,
            opentelemetry_metrics_endpoint=OTLP_ENDPOINT,
            opentelemetry_log_traces=True,
        )
    )
    bootstrapper.bootstrap()
    try:
        _emit_span()
        if import_checker.is_orjson_installed:
            _check_orjson_serializer()
    finally:
        bootstrapper.teardown()


def _fastapi_lean_sentry_capture() -> None:
    """Send one failing request through lean error capture, whose scope and session calls have floors too."""
    application = fastapi.FastAPI()

    @application.get("/floor-error")
    async def floor_error() -> None:
        message = "floor smoke"
        raise RuntimeError(message)

    bootstrapper = FastAPIBootstrapper(
        bootstrap_config=FastAPIConfig(
            service_name="floor-smoke",
            service_version="1.0.0",
            logging_buffer_capacity=0,
            sentry_dsn=SENTRY_DSN,
            sentry_additional_params=SENTRY_PARAMS,
            application=application,
        )
    )
    expected_status = 500
    assert asyncio.run(_request_status(bootstrapper.bootstrap(), "/floor-error")) == expected_status
    bootstrapper.teardown()


def _fastapi() -> None:
    if import_checker.is_sentry_installed:
        _fastapi_lean_sentry_capture()
    bootstrapper = FastAPIBootstrapper(
        bootstrap_config=FastAPIConfig(
            service_name="floor-smoke",
            service_version="1.0.0",
            service_debug=False,
            logging_buffer_capacity=0,
            cors_allowed_origins=["http://test"],
            health_checks_path=HEALTH_PATH,
            health_checks_include_in_schema=True,
            swagger_offline_docs=True,
            sentry_dsn=SENTRY_DSN,
            sentry_additional_params=SENTRY_PARAMS,
            pyroscope_endpoint=PYROSCOPE_ENDPOINT,
            opentelemetry_endpoint=OTLP_ENDPOINT,
            opentelemetry_metrics_endpoint=OTLP_ENDPOINT,
            opentelemetry_log_traces=True,
        )
    )
    application = bootstrapper.bootstrap()
    # Generating the schema puts HealthCheckTypedDict through pydantic as a response model,
    # which is the typing-extensions use ADR-0005 records.
    assert application.openapi()["paths"]
    assert application.url_path_for("health_check_handler") == HEALTH_PATH
    _emit_span()
    # Teardown runs inside the lifespan the bootstrapper chained onto the application.
    asyncio.run(_drive_lifespan(application))


def _litestar_lean_sentry_capture() -> None:
    """Send one failing request through lean error capture, whose scope and session calls have floors too."""

    @litestar.get("/floor-error")
    async def floor_error() -> None:
        message = "floor smoke"
        raise RuntimeError(message)

    bootstrapper = LitestarBootstrapper(
        bootstrap_config=LitestarConfig(
            service_name="floor-smoke",
            service_version="1.0.0",
            service_debug=False,
            logging_buffer_capacity=0,
            sentry_dsn=SENTRY_DSN,
            sentry_additional_params=SENTRY_PARAMS,
            application_config=AppConfig(route_handlers=[floor_error]),
        )
    )
    with TestClient(app=bootstrapper.bootstrap(), raise_server_exceptions=False) as test_client:
        expected_status = 500
        assert test_client.get("/floor-error").status_code == expected_status


def _litestar() -> None:
    if import_checker.is_sentry_installed:
        _litestar_lean_sentry_capture()
    bootstrapper = LitestarBootstrapper(
        bootstrap_config=LitestarConfig(
            service_name="floor-smoke",
            service_version="1.0.0",
            service_debug=False,
            logging_buffer_capacity=0,
            cors_allowed_origins=["http://test"],
            health_checks_path=HEALTH_PATH,
            sentry_dsn=SENTRY_DSN,
            sentry_additional_params=SENTRY_PARAMS,
            pyroscope_endpoint=PYROSCOPE_ENDPOINT,
            opentelemetry_endpoint=OTLP_ENDPOINT,
            opentelemetry_metrics_endpoint=OTLP_ENDPOINT,
            opentelemetry_log_traces=True,
        )
    )
    bootstrapper.bootstrap()
    try:
        _emit_span()
    finally:
        bootstrapper.teardown()


def _faststream() -> None:
    bootstrapper = FastStreamBootstrapper(
        bootstrap_config=FastStreamConfig(
            service_name="floor-smoke",
            service_version="1.0.0",
            logging_buffer_capacity=0,
            health_checks_path=HEALTH_PATH,
            sentry_dsn=SENTRY_DSN,
            sentry_additional_params=SENTRY_PARAMS,
            pyroscope_endpoint=PYROSCOPE_ENDPOINT,
            opentelemetry_endpoint=OTLP_ENDPOINT,
            opentelemetry_metrics_endpoint=OTLP_ENDPOINT,
            opentelemetry_log_traces=True,
        )
    )
    bootstrapper.bootstrap()
    try:
        _emit_span()
    finally:
        bootstrapper.teardown()


def _fastmcp_lean_sentry_capture() -> None:
    """Send one failing request through lean error capture, whose scope and session calls have floors too."""
    bootstrapper = FastMcpBootstrapper(
        bootstrap_config=FastMcpConfig(
            service_name="floor-smoke",
            service_version="1.0.0",
            logging_buffer_capacity=0,
            sentry_dsn=SENTRY_DSN,
            sentry_additional_params=SENTRY_PARAMS,
        )
    )
    application = bootstrapper.bootstrap()

    async def floor_error(_: "Request") -> "Response":
        message = "floor smoke"
        raise RuntimeError(message)

    application.custom_route("/floor-error", methods=["GET"])(floor_error)
    expected_status = 500
    assert asyncio.run(_request_status(application.http_app(), "/floor-error")) == expected_status
    bootstrapper.teardown()


def _fastmcp() -> None:
    if import_checker.is_sentry_installed:
        _fastmcp_lean_sentry_capture()
    bootstrapper = FastMcpBootstrapper(
        bootstrap_config=FastMcpConfig(
            service_name="floor-smoke",
            service_version="1.0.0",
            logging_buffer_capacity=0,
            health_checks_path=HEALTH_PATH,
            sentry_dsn=SENTRY_DSN,
            sentry_additional_params=SENTRY_PARAMS,
            pyroscope_endpoint=PYROSCOPE_ENDPOINT,
            opentelemetry_endpoint=OTLP_ENDPOINT,
            opentelemetry_metrics_endpoint=OTLP_ENDPOINT,
            opentelemetry_log_traces=True,
        )
    )
    application = bootstrapper.bootstrap()
    try:
        # FastMcpOpenTelemetryInstrument adds its middleware to the application http_app() builds.
        application.http_app()
        _emit_span()
    finally:
        bootstrapper.teardown()


TARGETS: typing.Final = {
    "free": _free,
    "fastapi": _fastapi,
    "litestar": _litestar,
    "faststream": _faststream,
    "fastmcp": _fastmcp,
}


def main() -> None:
    expected_argv_len = 2
    if len(sys.argv) != expected_argv_len or sys.argv[1] not in TARGETS:
        sys.exit(f"usage: floor_smoke.py {{{'|'.join(TARGETS)}}}")
    warnings.filterwarnings("error", category=InstrumentSkippedWarning)
    target = sys.argv[1]
    TARGETS[target]()
    print(f"floor smoke OK: {target} on {sys.version}")  # noqa: T201


if __name__ == "__main__":
    main()
