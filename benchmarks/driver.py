"""Shared pieces: a null Sentry transport and an in-process ASGI request loop.

Driving the app directly (`await app(scope, receive, send)`) removes sockets and HTTP parsing
from the measurement, so what is left is library cost. It makes the baseline unrealistically
fast, which overstates the *relative* impact; `run_http.py` is the real-server counterpart.
"""

import asyncio
import gc
import time
import typing


if typing.TYPE_CHECKING:
    from sentry_sdk.envelope import Envelope

from sentry_sdk.transport import Transport


DSN: typing.Final = "https://public@o0.ingest.sentry.io/0"

ASGIApp = typing.Callable[..., typing.Awaitable[None]]


class NullTransport(Transport):
    """Serialize the envelope and drop it: transport CPU is counted, network is not."""

    def __init__(self, options: dict[str, typing.Any] | None = None) -> None:
        super().__init__(options)
        self.envelopes = 0
        self.bytes = 0

    def capture_envelope(self, envelope: "Envelope") -> None:
        self.envelopes += 1
        self.bytes += len(envelope.serialize())


TRANSPORT: typing.Final = NullTransport()


BASE_SCOPE: typing.Final[dict[str, typing.Any]] = {
    "type": "http",
    "asgi": {"version": "3.0", "spec_version": "2.3"},
    "http_version": "1.1",
    "method": "GET",
    "scheme": "http",
    "path": "/ping",
    "raw_path": b"/ping",
    "root_path": "",
    "query_string": b"",
    "headers": [
        (b"host", b"testserver"),
        (b"user-agent", b"bench/1.0"),
        (b"accept", b"*/*"),
        (b"connection", b"keep-alive"),
    ],
    "client": ("127.0.0.1", 50000),
    "server": ("127.0.0.1", 8000),
}


async def one_request(app: ASGIApp, scope: dict[str, typing.Any] | None = None) -> int:
    """Drive one request through the ASGI app and return its status code.

    The scope is copied per call because Starlette and the instrumentations write into it
    (`route`, `endpoint`, `app`, ...), exactly as a real server hands over a fresh one.
    """
    request_scope = dict(scope if scope is not None else BASE_SCOPE)
    status = 0
    body_sent = False

    async def receive() -> dict[str, typing.Any]:
        nonlocal body_sent
        if body_sent:
            return {"type": "http.disconnect"}
        body_sent = True
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, typing.Any]) -> None:
        nonlocal status
        if message["type"] == "http.response.start":
            status = message["status"]

    await app(request_scope, receive, send)
    return status


async def run(app: ASGIApp, requests: int, rounds: int, warmup: int) -> list[float]:
    """Return one requests-per-second figure per round."""
    expected_status = 200
    for _ in range(warmup):
        status = await one_request(app)
        if status != expected_status:
            msg = f"warmup returned {status}, expected {expected_status}"
            raise RuntimeError(msg)

    results = []
    for _ in range(rounds):
        gc.collect()
        start = time.perf_counter()
        for _ in range(requests):
            await one_request(app)
        results.append(requests / (time.perf_counter() - start))
    return results


def measure(app: ASGIApp, requests: int, rounds: int, warmup: int) -> list[float]:
    return asyncio.run(run(app, requests, rounds, warmup))
