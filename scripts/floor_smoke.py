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


def _fastapi() -> None:
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


def _litestar() -> None:
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
            opentelemetry_log_traces=True,
        )
    )
    bootstrapper.bootstrap()
    try:
        _emit_span()
    finally:
        bootstrapper.teardown()


def _fastmcp() -> None:
    bootstrapper = FastMcpBootstrapper(
        bootstrap_config=FastMcpConfig(
            service_name="floor-smoke",
            service_version="1.0.0",
            logging_buffer_capacity=0,
            health_checks_path=HEALTH_PATH,
            sentry_dsn=SENTRY_DSN,
            sentry_additional_params=SENTRY_PARAMS,
            pyroscope_endpoint=PYROSCOPE_ENDPOINT,
        )
    )
    bootstrapper.bootstrap()
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
