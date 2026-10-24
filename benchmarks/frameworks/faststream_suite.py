"""FastStream per-message cost through FastStreamBootstrapper on a RedisBroker.

The broker is started against a real Redis (REDIS_URL), so no test doubles are installed: TestRedisBroker
replaces the broker logger and every handler with MagicMocks, which both hide FastStream's per-message
log calls and add their own cost. Two drivers:
- consume (default): the subscriber's own `process_message` on a prebuilt raw pub/sub message, which is
  what the consume loop calls for each message it reads. Parsing, decoding, the middleware chain, the
  handler and FastStream's per-message log calls run; Redis is not touched inside the loop.
- `<name>@pub`: `broker.publish` to Redis, the publisher side (its middleware, serialization, one round trip).
"""

import logging
import os
import typing

import structlog
from common import LOG, OTEL, OTEL_METRICS, Cleanup, Op, Scenario, base_config, ratio, sentry
from faststream.asgi import AsgiFastStream
from faststream.redis import RedisBroker
from faststream.redis.opentelemetry import RedisTelemetryMiddleware
from faststream.redis.prometheus import RedisPrometheusMiddleware
from faststream.redis.testing import ChannelVisitor, build_message

from lite_bootstrap import FastStreamBootstrapper, FastStreamConfig


log = structlog.get_logger("bench")

REDIS_URL: typing.Final = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379")
OTEL_MW: typing.Final = {**OTEL, "opentelemetry_middleware_cls": RedisTelemetryMiddleware}
PROM_MW: typing.Final = {"prometheus_metrics_path": "/metrics", "prometheus_middleware_cls": RedisPrometheusMiddleware}
INFO: typing.Final = {"faststream_log_level": logging.INFO}

_BASE: typing.Final = {
    "bare": Scenario(config=base_config()),
    "log": Scenario(config=base_config(**LOG)),
    "log_info": Scenario(config=base_config(**LOG, **INFO)),
    "log_handler3": Scenario(config=base_config(**LOG), kind="structlog"),
    "prom": Scenario(config=base_config(**LOG, **PROM_MW)),
    "otel": Scenario(config=base_config(**LOG, **OTEL_MW)),
    "otel_10": Scenario(config=base_config(**LOG, **OTEL_MW, **ratio(0.1))),
    "otel_0": Scenario(config=base_config(**LOG, **OTEL_MW, **ratio(0.0))),
    "otel_metrics": Scenario(config=base_config(**LOG, **OTEL_MW, **OTEL_METRICS)),
    "otel_0_metrics": Scenario(config=base_config(**LOG, **OTEL_MW, **OTEL_METRICS, **ratio(0.0))),
    "otel_prom": Scenario(config=base_config(**LOG, **OTEL_MW, **PROM_MW)),
    "prom_otel_0": Scenario(config=base_config(**LOG, **OTEL_MW, **PROM_MW, **ratio(0.0))),
    "otel_metrics_prom": Scenario(config=base_config(**LOG, **OTEL_MW, **OTEL_METRICS, **PROM_MW)),
    "sentry": Scenario(config=base_config(**LOG, **sentry())),
    "sentry_nolog": Scenario(config=base_config(**sentry())),
    "sentry_log_info": Scenario(config=base_config(**LOG, **sentry(), **INFO)),
    "sentry_log_handler3": Scenario(config=base_config(**LOG, **sentry()), kind="structlog"),
    "sentry_noauto": Scenario(config=base_config(**LOG, **sentry(auto_enabling_integrations=False))),
    "full": Scenario(config=base_config(**OTEL_MW, **PROM_MW, **LOG, **sentry())),
}
SCENARIOS: typing.Final = {**_BASE, **{f"{name}@pub": scenario for name, scenario in _BASE.items()}}


async def handle(body: dict[str, int]) -> None:  # noqa: ARG001
    return None


async def handle_log(body: dict[str, int]) -> None:  # noqa: ARG001
    log.info("handling message", a=1)
    log.info("did a thing", b=2)
    log.info("done", c=3)


HANDLERS: typing.Final = {"async": handle, "structlog": handle_log}


async def make(name: str) -> tuple[Op, Cleanup]:
    scenario = SCENARIOS[name]
    broker = RedisBroker(REDIS_URL)
    subscriber = broker.subscriber("in")
    subscriber(HANDLERS[scenario.kind])
    application = AsgiFastStream(broker)
    FastStreamBootstrapper(FastStreamConfig(application=application, **scenario.config)).bootstrap()
    await broker.start()

    async def cleanup() -> None:
        await broker.stop()

    if name.endswith("@pub"):

        async def publish() -> None:
            await broker.publish({"a": 1}, channel="out")

        return publish, cleanup

    body = await build_message(
        message={"a": 1},
        correlation_id="bench-correlation-id",
        message_format=subscriber.config.message_format,
        serializer=broker.config.fd_config._serializer,
    )
    raw = ChannelVisitor().get_message("in", body, subscriber)

    async def consume() -> None:
        await subscriber.process_message(raw)

    return consume, cleanup
