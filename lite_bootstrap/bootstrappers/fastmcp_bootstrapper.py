import contextlib
import dataclasses
import time
import typing

from lite_bootstrap import import_checker
from lite_bootstrap.bootstrappers.base import BaseBootstrapper
from lite_bootstrap.instruments.healthchecks_instrument import HealthChecksConfig, HealthChecksInstrument
from lite_bootstrap.instruments.logging_instrument import LoggingConfig, LoggingInstrument
from lite_bootstrap.instruments.prometheus_instrument import PrometheusConfig, PrometheusInstrument
from lite_bootstrap.instruments.pyroscope_instrument import PyroscopeConfig, PyroscopeInstrument
from lite_bootstrap.instruments.sentry_instrument import SentryConfig, SentryInstrument


if import_checker.is_fastmcp_installed:
    from fastmcp import FastMCP
    from fastmcp.server.middleware import Middleware, MiddlewareContext
    from fastmcp.server.providers import Provider
    from starlette.requests import Request
    from starlette.responses import JSONResponse, Response

if import_checker.is_structlog_installed:
    import structlog

    fastmcp_access_logger: typing.Final = structlog.get_logger("mcp.access")

if import_checker.is_prometheus_client_installed:
    import prometheus_client


def _make_fastmcp() -> "FastMCP[typing.Any]":
    return FastMCP()


if import_checker.is_fastmcp_installed:

    class _TeardownProvider(Provider):
        # FastMCP exposes no on_shutdown-style API; Provider.lifespan is the only public
        # post-construction hook whose async-cm runs during ASGI startup/shutdown.
        def __init__(self, teardown: typing.Callable[[], None]) -> None:
            super().__init__()
            self._teardown = teardown

        @contextlib.asynccontextmanager
        async def lifespan(self) -> typing.AsyncIterator[None]:
            try:
                yield
            finally:
                self._teardown()

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


@dataclasses.dataclass(kw_only=True)
class FastMcpHealthChecksInstrument(HealthChecksInstrument):
    bootstrap_config: FastMcpConfig

    def bootstrap(self) -> None:
        @self.bootstrap_config.application.custom_route(
            self.bootstrap_config.health_checks_path,
            methods=["GET"],
            name="health_check",
            include_in_schema=self.bootstrap_config.health_checks_include_in_schema,
        )
        async def health_check_handler(_: "Request") -> "JSONResponse":
            return JSONResponse(dict(self.render_health_check_data()))


@dataclasses.dataclass(kw_only=True)
class FastMcpPrometheusInstrument(PrometheusInstrument):
    bootstrap_config: FastMcpConfig
    missing_dependency_message = "prometheus_client is not installed"

    @staticmethod
    def check_dependencies() -> bool:
        return import_checker.is_prometheus_client_installed

    def bootstrap(self) -> None:
        @self.bootstrap_config.application.custom_route(
            self.bootstrap_config.prometheus_metrics_path,
            methods=["GET"],
            name="metrics",
            include_in_schema=self.bootstrap_config.prometheus_metrics_include_in_schema,
        )
        async def metrics_handler(_: "Request") -> "Response":
            return Response(
                prometheus_client.generate_latest(prometheus_client.REGISTRY),
                headers={"content-type": prometheus_client.CONTENT_TYPE_LATEST},
            )


@dataclasses.dataclass(kw_only=True)
class FastMcpLoggingInstrument(LoggingInstrument):
    bootstrap_config: FastMcpConfig

    def bootstrap(self) -> None:
        super().bootstrap()
        if self.bootstrap_config.logging_turn_off_middleware:
            return
        self.bootstrap_config.application.add_middleware(FastMcpLoggingMiddleware())


class FastMcpBootstrapper(BaseBootstrapper["FastMCP[typing.Any]"]):
    __slots__ = "bootstrap_config", "instruments"

    instruments_types: typing.ClassVar = [
        PyroscopeInstrument,
        SentryInstrument,
        FastMcpHealthChecksInstrument,
        FastMcpLoggingInstrument,
        FastMcpPrometheusInstrument,
    ]
    bootstrap_config: FastMcpConfig
    not_ready_message = "fastmcp is not installed"

    def is_ready(self) -> bool:
        return import_checker.is_fastmcp_installed

    def __init__(self, bootstrap_config: FastMcpConfig) -> None:
        super().__init__(bootstrap_config)
        self.bootstrap_config.application.add_provider(_TeardownProvider(self.teardown))

    def _prepare_application(self) -> "FastMCP[typing.Any]":
        return self.bootstrap_config.application
