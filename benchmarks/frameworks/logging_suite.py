"""Cost per log call through lite-bootstrap's LoggingInstrument, output to a real /dev/null file.

One op is one log call. `noop` is the loop's own cost, subtract it. `native_bytes*` is structlog's own
filtering bound logger writing orjson bytes, without lite-bootstrap, as a reference point.
"""

import contextlib
import dataclasses
import logging
import os
import typing

import orjson
import structlog
from common import DSN, TRANSPORT, Cleanup, Op
from opentelemetry import context, trace
from opentelemetry.sdk.trace import TracerProvider

from lite_bootstrap.instruments import logging_factory, logging_instrument
from lite_bootstrap.instruments.logging_instrument import LoggingConfig, LoggingInstrument
from lite_bootstrap.instruments.sentry_instrument import SentryConfig, SentryInstrument


@dataclasses.dataclass(frozen=True, kw_only=True)
class LogScenario:
    call: str
    sentry: dict[str, typing.Any] | None = None
    span: bool = False
    native: bool = False
    stdlib_json: bool = False


SCENARIOS: typing.Final = {
    "noop": LogScenario(call="noop"),
    "info": LogScenario(call="info"),
    "info_kw5": LogScenario(call="info_kw5"),
    "debug_filtered": LogScenario(call="debug"),
    "info_stdjson": LogScenario(call="info", stdlib_json=True),
    "info_span": LogScenario(call="info", span=True),
    "info_sentry": LogScenario(call="info", sentry={}),
    "info_sentry_nocrumb": LogScenario(call="info", sentry={"sentry_logging_breadcrumb_level": None}),
    "debug_filtered_sentry": LogScenario(call="debug", sentry={}),
    "stdlib_info": LogScenario(call="stdlib_info"),
    "stdlib_debug_filtered": LogScenario(call="stdlib_debug"),
    "stdlib_info_sentry": LogScenario(call="stdlib_info", sentry={}),
    "native_bytes": LogScenario(call="info", native=True),
    "native_bytes_filtered": LogScenario(call="debug", native=True),
}

log = structlog.get_logger("bench")
std = logging.getLogger("lib")


async def noop() -> None:
    return None


async def info() -> None:
    log.info("did a thing", a=1)


async def info_kw5() -> None:
    log.info("did a thing", a=1, b="two", c=3.0, d=[1, 2], e={"k": "v"})


async def debug() -> None:
    log.debug("did a thing", a=1)


async def stdlib_info() -> None:
    std.info("did a thing %s", 1)


async def stdlib_debug() -> None:
    std.debug("did a thing %s", 1)


CALLS: typing.Final = {
    "noop": noop,
    "info": info,
    "info_kw5": info_kw5,
    "debug": debug,
    "stdlib_info": stdlib_info,
    "stdlib_debug": stdlib_debug,
}


def configure_native(stream: typing.BinaryIO) -> None:
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(serializer=orjson.dumps),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.BytesLoggerFactory(file=stream),
        cache_logger_on_first_use=True,
    )


def setup(scenario: LogScenario) -> list[typing.Callable[[], object]]:
    """Configure logging (and Sentry, and a span) for the scenario; return what to undo, last first."""
    if scenario.stdlib_json:
        logging_instrument._serialize_log_to_string = logging_factory._dumps_stdlib
    devnull = open(os.devnull, "w")  # noqa: PTH123, SIM115
    cleanups: list[typing.Callable[[], object]] = [devnull.close]

    if scenario.native:
        devnull_bytes = open(os.devnull, "wb")  # noqa: PTH123, SIM115
        cleanups.append(devnull_bytes.close)
        configure_native(devnull_bytes)
    elif scenario.call != "noop":
        with contextlib.redirect_stdout(devnull):
            config = LoggingConfig(logging_enabled=True)
            LoggingInstrument(bootstrap_config=config).bootstrap()

    if scenario.sentry is not None:
        sentry_config = SentryConfig(
            sentry_dsn=DSN, sentry_additional_params={"transport": TRANSPORT}, **scenario.sentry
        )
        SentryInstrument(bootstrap_config=sentry_config).bootstrap()

    if scenario.span:
        span = TracerProvider().get_tracer("bench").start_span("request")
        token = context.attach(trace.set_span_in_context(span))
        cleanups.append(lambda: context.detach(token))
    return cleanups


async def make(name: str) -> tuple[Op, Cleanup]:
    scenario = SCENARIOS[name]
    cleanups = setup(scenario)

    async def cleanup() -> None:
        for step in reversed(cleanups):
            step()

    return CALLS[scenario.call], cleanup
