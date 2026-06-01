import dataclasses
import time
import typing

from lite_bootstrap import import_checker
from lite_bootstrap.bootstrappers.base import BaseBootstrapper
from lite_bootstrap.instruments.healthchecks_instrument import HealthChecksConfig
from lite_bootstrap.instruments.logging_instrument import LoggingConfig
from lite_bootstrap.instruments.prometheus_instrument import PrometheusConfig
from lite_bootstrap.instruments.pyroscope_instrument import PyroscopeConfig
from lite_bootstrap.instruments.sentry_instrument import SentryConfig


if import_checker.is_fastmcp_installed:
    from fastmcp import FastMCP
    from fastmcp.server.middleware import Middleware, MiddlewareContext

if import_checker.is_structlog_installed:
    import structlog

    fastmcp_access_logger: typing.Final = structlog.get_logger("mcp.access")


def _make_fastmcp() -> "FastMCP[typing.Any]":
    return FastMCP()


class FastMcpLoggingMiddleware(Middleware):
    async def on_message(
        self,
        context: "MiddlewareContext[typing.Any]",
        call_next: "typing.Callable[[MiddlewareContext[typing.Any]], typing.Awaitable[typing.Any]]",
    ) -> typing.Any:  # noqa: ANN401
        start_time = time.perf_counter_ns()
        mcp_fields = {
            "method": context.method,
            "source": context.source,
            "type": context.type,
        }
        try:
            result = await call_next(context)
        except Exception:
            fastmcp_access_logger.exception(
                context.method or "unknown",
                mcp=mcp_fields,
                duration=time.perf_counter_ns() - start_time,
            )
            raise

        fastmcp_access_logger.info(
            context.method or "unknown",
            mcp=mcp_fields,
            duration=time.perf_counter_ns() - start_time,
        )
        return result


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class FastMcpConfig(HealthChecksConfig, LoggingConfig, PrometheusConfig, PyroscopeConfig, SentryConfig):
    application: "FastMCP[typing.Any]" = dataclasses.field(default_factory=_make_fastmcp)
    logging_turn_off_middleware: bool = False


class FastMcpBootstrapper(BaseBootstrapper["FastMCP[typing.Any]"]):
    __slots__ = "bootstrap_config", "instruments"

    instruments_types: typing.ClassVar = []
    bootstrap_config: FastMcpConfig
    not_ready_message = "fastmcp is not installed"

    def is_ready(self) -> bool:
        return import_checker.is_fastmcp_installed

    def _prepare_application(self) -> "FastMCP[typing.Any]":
        return self.bootstrap_config.application
