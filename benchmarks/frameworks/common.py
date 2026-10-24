"""Shared pieces for the framework suites: ASGI driving, lifespan, scenario shape, OTLP and Sentry sinks.

The null Sentry transport is the one `benchmarks/driver.py` defines, loaded from there by path.
"""

import asyncio
import dataclasses
import importlib.util
import os
import pathlib
import types
import typing

from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased


HERE: typing.Final = pathlib.Path(__file__).resolve().parent
BENCHMARKS: typing.Final = HERE.parent
STUB_OTLP: typing.Final = BENCHMARKS / "stub_otlp.py"


def _load_driver() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("driver", BENCHMARKS / "driver.py")
    if spec is None or spec.loader is None:
        msg = f"cannot load {BENCHMARKS / 'driver.py'}"
        raise ImportError(msg)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_driver: typing.Final = _load_driver()
DSN: typing.Final[str] = _driver.DSN
TRANSPORT: typing.Final = _driver.TRANSPORT

OTLP_PORT: typing.Final = int(os.environ.get("STUB_OTLP_PORT", "8139"))
OTLP_TRACES: typing.Final = f"http://127.0.0.1:{OTLP_PORT}/v1/traces"
OTLP_METRICS: typing.Final = f"http://127.0.0.1:{OTLP_PORT}/v1/metrics"

ASGIApp = typing.Callable[..., typing.Coroutine[typing.Any, typing.Any, None]]
Op = typing.Callable[[], typing.Awaitable[object]]
Cleanup = typing.Callable[[], typing.Awaitable[None]]
Headers = tuple[tuple[bytes, bytes], ...]

BASE_HEADERS: typing.Final[Headers] = (
    (b"host", b"testserver"),
    (b"user-agent", b"bench/1.0"),
    (b"accept", b"*/*"),
    (b"connection", b"keep-alive"),
)


@dataclasses.dataclass(frozen=True, kw_only=True)
class Scenario:
    config: dict[str, typing.Any]
    path: str = "/ping"
    headers: Headers = ()
    kind: str = "async"
    patch: typing.Callable[[], None] | None = None


def http_scope(path: str = "/ping", method: str = "GET", extra_headers: Headers = ()) -> dict[str, typing.Any]:
    overridden = {name for name, _ in extra_headers}
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": [*(header for header in BASE_HEADERS if header[0] not in overridden), *extra_headers],
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8000),
    }


def asgi_op(app: ASGIApp, scope: dict[str, typing.Any], body: bytes = b"", expect: int = 200) -> Op:
    """One request per call. The scope is copied: frameworks write into it, as a server hands over a fresh one."""

    async def op() -> int:
        request_scope = dict(scope)
        request_scope["state"] = {}
        status = 0
        body_sent = False

        async def receive() -> dict[str, typing.Any]:
            nonlocal body_sent
            if body_sent:
                return {"type": "http.disconnect"}
            body_sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message: dict[str, typing.Any]) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]

        await app(request_scope, receive, send)
        if status != expect:
            msg = f"status {status}, expected {expect}"
            raise RuntimeError(msg)
        return status

    return op


async def start_lifespan(app: ASGIApp) -> Cleanup:
    """Run the ASGI lifespan startup and return a coroutine function that shuts it down."""
    inbox: asyncio.Queue[dict[str, typing.Any]] = asyncio.Queue()
    started = asyncio.Event()
    stopped = asyncio.Event()

    async def receive() -> dict[str, typing.Any]:
        return await inbox.get()

    async def send(message: dict[str, typing.Any]) -> None:
        if message["type"].startswith("lifespan.startup"):
            if message["type"].endswith("failed"):
                raise RuntimeError(message.get("message"))
            started.set()
        if message["type"].startswith("lifespan.shutdown"):
            stopped.set()

    task = asyncio.create_task(app({"type": "lifespan", "asgi": {"version": "3.0"}, "state": {}}, receive, send))
    await inbox.put({"type": "lifespan.startup"})
    await asyncio.wait_for(started.wait(), 10)

    async def stop() -> None:
        await inbox.put({"type": "lifespan.shutdown"})
        try:
            await asyncio.wait_for(stopped.wait(), 5)
        except TimeoutError:
            task.cancel()

    return stop


def base_config(**overrides: object) -> dict[str, typing.Any]:
    """Every lite-bootstrap instrument off; a scenario turns on what it measures."""
    merged: dict[str, typing.Any] = {
        "service_name": "bench",
        "service_environment": "bench",
        "service_debug": False,
        "prometheus_metrics_path": "",
        "health_checks_enabled": False,
        "logging_enabled": False,
    }
    merged.update(overrides)
    return merged


def ratio(fraction: float) -> dict[str, typing.Any]:
    return {"opentelemetry_sampler": ParentBased(TraceIdRatioBased(fraction))}


def sentry(**extra_params: object) -> dict[str, typing.Any]:
    return {"sentry_dsn": DSN, "sentry_additional_params": {"transport": TRANSPORT, **extra_params}}


OTEL: typing.Final = {"opentelemetry_endpoint": OTLP_TRACES, "opentelemetry_exporter_protocol": "http"}
OTEL_METRICS: typing.Final = {"opentelemetry_metrics_endpoint": OTLP_METRICS}
EXCL: typing.Final = {"opentelemetry_exclude_spans": ["receive", "send"]}
PROM: typing.Final = {"prometheus_metrics_path": "/metrics"}
LOG: typing.Final = {"logging_enabled": True}
CORS: typing.Final = {"cors_allowed_origins": ["https://example.com"], "cors_allowed_methods": ["GET"]}
ORIGIN: typing.Final[Headers] = ((b"origin", b"https://example.com"),)
