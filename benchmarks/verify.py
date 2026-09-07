"""What a cheaper Sentry configuration actually gives up.

Speed alone does not settle whether a scenario is worth adopting. This drives a request that
raises, with an incoming `sentry-trace` header, and prints what survived on the captured event:
the transaction name, whether the incoming distributed trace was continued, and the breadcrumbs.

    python verify.py errors_only errors_only_no_txn errors_only_skip_txn
"""

import argparse
import asyncio
import contextlib
import io
import json
import logging
import sys
import typing

import driver
import sentry_scenarios
import sentry_sdk
from fastapi import FastAPI
from sentry_sdk.envelope import Envelope
from sentry_sdk.transport import Transport


INCOMING_TRACE_ID: typing.Final = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
INCOMING_SPAN_ID: typing.Final = "bbbbbbbbbbbbbbbb"

logger = logging.getLogger("bench")


class CapturingTransport(Transport):
    def __init__(self, options: dict[str, typing.Any] | None = None) -> None:
        super().__init__(options)
        self.events: list[dict[str, typing.Any]] = []

    def capture_envelope(self, envelope: Envelope) -> None:
        for item in envelope.items:
            if item.type == "event" and item.payload.json is not None:
                self.events.append(item.payload.json)


def make_app() -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/ping")
    async def ping() -> dict[str, bool]:
        logger.info("about to fail")
        msg = "boom"
        raise RuntimeError(msg)

    return app


def traced_scope() -> dict[str, typing.Any]:
    scope = dict(driver.BASE_SCOPE)
    scope["headers"] = [
        *driver.BASE_SCOPE["headers"],
        (b"sentry-trace", f"{INCOMING_TRACE_ID}-{INCOMING_SPAN_ID}-1".encode()),
        (b"baggage", f"sentry-trace_id={INCOMING_TRACE_ID},sentry-environment=prod".encode()),
    ]
    return scope


async def drive(app: driver.ASGIApp) -> None:
    with contextlib.suppress(RuntimeError):
        await driver.one_request(app, traced_scope())


def describe(scenario: str, event: dict[str, typing.Any]) -> dict[str, typing.Any]:
    trace = (event.get("contexts") or {}).get("trace") or {}
    breadcrumbs = (event.get("breadcrumbs") or {}).get("values") or []
    return {
        "scenario": scenario,
        "transaction": event.get("transaction"),
        "trace_id": trace.get("trace_id"),
        "parent_span_id": trace.get("parent_span_id"),
        "continues_incoming_trace": trace.get("trace_id") == INCOMING_TRACE_ID,
        "breadcrumbs": [crumb.get("message") for crumb in breadcrumbs],
        "request_url": (event.get("request") or {}).get("url"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, stream=io.StringIO())

    transport = CapturingTransport()
    kwargs = sentry_scenarios.SCENARIOS[args.scenario]
    if kwargs is None:
        parser.error("scenario 'off' captures nothing")
    init_kwargs = kwargs()
    init_kwargs["transport"] = transport
    sentry_sdk.init(**init_kwargs)
    for patch in sentry_scenarios.PATCHES.get(args.scenario, ()):
        patch()

    asyncio.run(drive(make_app()))

    for event in transport.events:
        json.dump(describe(args.scenario, event), sys.stdout)
        sys.stdout.write("\n")


if __name__ == "__main__":
    main()
