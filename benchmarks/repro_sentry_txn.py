"""Standalone repro for getsentry/sentry-python#7400, kept copy-pasteable.

Deliberately imports nothing from this directory: it is pasted into the upstream issue and has
to run against a bare `pip install sentry-sdk fastapi` checkout. Importing sentry-sdk patches
nothing - only `init()` does - so `--off` is a genuine no-SDK baseline.

    python repro_sentry_txn.py --off      # SDK never initialised
    python repro_sentry_txn.py            # SDK as shipped
    python repro_sentry_txn.py --patched  # skip the Transaction, keep trace propagation
"""

import asyncio
import sys
import time
import typing

import sentry_sdk
from fastapi import FastAPI
from sentry_sdk.envelope import Envelope
from sentry_sdk.scope import Scope
from sentry_sdk.transport import Transport


SCOPE: typing.Final = {
    "type": "http",
    "asgi": {"version": "3.0", "spec_version": "2.3"},
    "http_version": "1.1",
    "method": "GET",
    "scheme": "http",
    "path": "/ping",
    "raw_path": b"/ping",
    "root_path": "",
    "query_string": b"",
    "headers": [(b"host", b"testserver"), (b"accept", b"*/*")],
    "client": ("127.0.0.1", 50000),
    "server": ("127.0.0.1", 8000),
}
WARMUP: typing.Final = 500
REQUESTS: typing.Final = 5000


class NullTransport(Transport):
    def capture_envelope(self, envelope: Envelope) -> None:
        """Drop it: this measures instrumentation, not delivery."""


def continue_trace_without_transaction(
    self: Scope, environ_or_headers: dict[str, typing.Any], *_args: object, **_kwargs: object
) -> None:
    """Set up trace propagation only, as the SDK could when tracing is disabled."""
    self.generate_propagation_context(environ_or_headers)


def setup(*, patched: bool) -> None:
    # tracing is DISABLED: traces_sample_rate and traces_sampler are both unset
    sentry_sdk.init(dsn="https://public@o0.ingest.sentry.io/0", transport=NullTransport)
    if patched:
        Scope.continue_trace = continue_trace_without_transaction  # ty: ignore[invalid-assignment]


async def drive(app: typing.Callable[..., typing.Awaitable[None]], requests: int) -> float:
    async def receive() -> dict[str, typing.Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, typing.Any]) -> None:
        """Discard the response."""

    for _ in range(WARMUP):
        await app(dict(SCOPE), receive, send)

    start = time.perf_counter()
    for _ in range(requests):
        await app(dict(SCOPE), receive, send)
    return requests / (time.perf_counter() - start)


def main() -> None:
    if "--patched" in sys.argv:
        mode = "patched"
    elif "--off" in sys.argv:
        mode = "off"
    else:
        mode = "sdk"

    if mode != "off":
        setup(patched=mode == "patched")

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/ping")
    async def ping() -> dict[str, bool]:
        return {"ok": True}

    rps = asyncio.run(drive(app, REQUESTS))
    print(f"{mode:<8} {rps:8.0f} rps   {1e6 / rps:6.1f} us/req")


if __name__ == "__main__":
    main()
