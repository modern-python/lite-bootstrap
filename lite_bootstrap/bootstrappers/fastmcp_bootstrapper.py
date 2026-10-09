import contextlib
import dataclasses
import functools
import inspect
import re
import time
import typing
from collections.abc import AsyncGenerator

from lite_bootstrap import import_checker
from lite_bootstrap.bootstrappers.base import BaseBootstrapper
from lite_bootstrap.instruments.healthchecks_instrument import HealthChecksConfig, HealthChecksInstrument
from lite_bootstrap.instruments.logging_instrument import LoggingConfig, LoggingInstrument
from lite_bootstrap.instruments.opentelemetry_instrument import OpenTelemetryConfig, OpenTelemetryInstrument
from lite_bootstrap.instruments.prometheus_instrument import PrometheusConfig, PrometheusInstrument
from lite_bootstrap.instruments.pyroscope_instrument import PyroscopeConfig, PyroscopeInstrument
from lite_bootstrap.instruments.sentry_instrument import SentryConfig, SentryInstrument


if import_checker.is_fastmcp_installed:
    from fastmcp import FastMCP
    from fastmcp.server.http import StarletteWithLifespan
    from fastmcp.server.middleware import Middleware, MiddlewareContext
    from fastmcp.server.providers import Provider
    from starlette.requests import Request
    from starlette.responses import JSONResponse, Response

if import_checker.is_fastmcp_opentelemetry_installed:
    from opentelemetry.instrumentation.asgi import OpenTelemetryMiddleware
    from opentelemetry.metrics import get_meter_provider
    from opentelemetry.trace import get_tracer_provider
    from opentelemetry.util.http import parse_excluded_urls
    from starlette.routing import BaseRoute, Match, Mount, Route
    from starlette.types import Scope

if import_checker.is_structlog_installed:
    import structlog

    fastmcp_access_logger: typing.Final = structlog.get_logger("mcp.access")

if import_checker.is_prometheus_client_installed:
    import prometheus_client

if import_checker.is_prometheus_fastapi_instrumentator_installed:
    from prometheus_fastapi_instrumentator import Instrumentator
    from prometheus_fastapi_instrumentator import metrics as instrumentator_metrics

    _DEFAULT_METRICS_PARAMETERS: typing.Final = frozenset(inspect.signature(instrumentator_metrics.default).parameters)


# OpenTelemetryMiddleware matches its patterns against a full URL, not a bare path.
_EXCLUDED_URL_SCHEME_AND_HOST: typing.Final = r"^\w+://[^/]*"

_TOOL_CALL_STATUS_SUCCESS: typing.Final = "success"
_TOOL_CALL_STATUS_ERROR: typing.Final = "error"

# Set by StarletteInstrumentor too, so an application is never traced twice
_OPENTELEMETRY_INSTRUMENTED_MARKER: typing.Final = "_is_instrumented_by_opentelemetry"


def _make_fastmcp() -> "FastMCP[typing.Any]":
    return FastMCP()


def _postprocess_http_apps(
    application: "FastMCP[typing.Any]",
    postprocess: "typing.Callable[[StarletteWithLifespan], StarletteWithLifespan]",
) -> typing.Callable[[], None]:
    """Pass every ASGI application ``http_app()`` builds through ``postprocess``; return the undo.

    FastMCP builds its ASGI application lazily, when the user calls ``http_app()`` after bootstrap or
    ``run(transport="http")`` calls it, so there is nothing to instrument at bootstrap time.
    """
    previous_override: typing.Final = vars(application).get("http_app")
    build_http_app: typing.Final = application.http_app

    def http_app(*args: typing.Any, **kwargs: typing.Any) -> "StarletteWithLifespan":  # noqa: ANN401
        return postprocess(build_http_app(*args, **kwargs))

    application.http_app = http_app  # ty: ignore[invalid-assignment]

    def restore() -> None:
        if previous_override is None:
            del application.http_app
        else:
            application.http_app = previous_override

    return restore


def _build_tool_call_metrics() -> tuple["prometheus_client.Counter", "prometheus_client.Histogram"]:
    # The global registry rejects a second collector of the same name, so a later bootstrap reuses the first
    registered_collectors: typing.Final = prometheus_client.REGISTRY._names_to_collectors  # noqa: SLF001
    if "fastmcp_tool_calls_total" in registered_collectors:
        return (
            typing.cast("prometheus_client.Counter", registered_collectors["fastmcp_tool_calls_total"]),
            typing.cast("prometheus_client.Histogram", registered_collectors["fastmcp_tool_call_duration_seconds"]),
        )
    return (
        prometheus_client.Counter(
            "fastmcp_tool_calls_total", "Number of MCP tool calls by tool and outcome.", ["tool", "status"]
        ),
        prometheus_client.Histogram(
            "fastmcp_tool_call_duration_seconds", "Duration of MCP tool calls by tool.", ["tool"]
        ),
    )


def build_fastmcp_route_details_from_scope(
    scope: "Scope",
    routes: "typing.Iterable[BaseRoute]",
) -> tuple[str, dict[str, str]]:
    method: typing.Final = str(scope.get("method", "HTTP")).strip()
    for route in routes:
        if isinstance(route, (Route, Mount)) and route.path and route.matches(scope)[0] == Match.FULL:
            return f"{method} {route.path}", {"http.route": route.path}
    # Unmatched paths get no `http.route`: a raw path would let scanners explode span cardinality
    return method, {}


if import_checker.is_fastmcp_installed:

    class _TeardownProvider(Provider):
        # FastMCP exposes no on_shutdown-style API; Provider.lifespan is the only public
        # post-construction hook whose async-cm runs during ASGI startup/shutdown.
        def __init__(self, teardown: typing.Callable[[], None]) -> None:
            super().__init__()
            self._teardown = teardown

        @contextlib.asynccontextmanager
        async def lifespan(self) -> AsyncGenerator[None]:
            try:
                yield
            finally:
                self._teardown()

    class FastMcpPrometheusMiddleware(Middleware):
        def __init__(
            self,
            tool_calls_total: "prometheus_client.Counter",
            tool_call_duration_seconds: "prometheus_client.Histogram",
        ) -> None:
            self.tool_calls_total = tool_calls_total
            self.tool_call_duration_seconds = tool_call_duration_seconds

        async def on_call_tool(
            self,
            context: "MiddlewareContext[typing.Any]",
            call_next: "typing.Callable[[MiddlewareContext[typing.Any]], typing.Awaitable[typing.Any]]",
        ) -> typing.Any:  # noqa: ANN401
            tool_name: typing.Final = context.message.name
            start_time: typing.Final = time.perf_counter()
            try:
                result = await call_next(context)
            except Exception:
                self.tool_calls_total.labels(tool=tool_name, status=_TOOL_CALL_STATUS_ERROR).inc()
                raise
            finally:
                self.tool_call_duration_seconds.labels(tool=tool_name).observe(time.perf_counter() - start_time)
            self.tool_calls_total.labels(tool=tool_name, status=_TOOL_CALL_STATUS_SUCCESS).inc()
            return result

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
class FastMcpConfig(
    HealthChecksConfig, LoggingConfig, OpenTelemetryConfig, PrometheusConfig, PyroscopeConfig, SentryConfig
):
    application: "FastMCP[typing.Any]" = dataclasses.field(default_factory=_make_fastmcp)
    fastmcp_logging_middleware_enabled: bool = False
    fastmcp_prometheus_tool_metrics_enabled: bool = True
    prometheus_instrumentator_params: dict[str, typing.Any] = dataclasses.field(default_factory=dict)
    prometheus_instrument_params: dict[str, typing.Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass(kw_only=True)
class FastMcpHealthChecksInstrument(HealthChecksInstrument):
    bootstrap_config: FastMcpConfig

    def bootstrap(self) -> None:
        config = self.bootstrap_config

        @config.application.custom_route(
            config.health_checks_path,
            methods=["GET"],
            name="health_check",
            include_in_schema=config.health_checks_include_in_schema,
        )
        async def health_check_handler(_: "Request") -> "JSONResponse":
            return JSONResponse(dict(self.render_health_check_data()))


@dataclasses.dataclass(kw_only=True)
class FastMcpOpenTelemetryInstrument(OpenTelemetryInstrument):
    bootstrap_config: FastMcpConfig
    missing_dependency_message = "opentelemetry-instrumentation-asgi is not installed"
    _restore_http_app: typing.Callable[[], None] | None = dataclasses.field(
        default=None, init=False, repr=False, compare=False
    )

    @staticmethod
    def dependencies_installed() -> bool:
        return OpenTelemetryInstrument.dependencies_installed() and import_checker.is_fastmcp_opentelemetry_installed

    def _build_excluded_url_patterns(self) -> list[str]:
        """Anchored patterns for the derived paths, plus the caller's own entries verbatim.

        The trailing slash is stripped and matched optionally, so ``/health/`` excludes the path with
        or without it. Anchoring is needed because ``ExcludeList`` searches unanchored: a bare
        ``/health`` would also silence ``/healthy``. Caller-supplied entries stay untouched because
        OpenTelemetry documents them as regexes.
        """
        anchored_patterns: typing.Final = {
            rf"{_EXCLUDED_URL_SCHEME_AND_HOST}{re.escape(normalized_path)}(?:/|$)"
            for excluded_path in self._build_infrastructure_excluded_paths()
            # A bare "/" would anchor to every URL, so it is dropped along with empty values.
            if (normalized_path := excluded_path.rstrip("/"))
        }
        return sorted(anchored_patterns | set(self.bootstrap_config.opentelemetry_excluded_urls))

    def _instrument_http_app(self, http_application: "StarletteWithLifespan") -> "StarletteWithLifespan":
        if getattr(http_application, _OPENTELEMETRY_INSTRUMENTED_MARKER, False):
            return http_application
        http_application.add_middleware(
            OpenTelemetryMiddleware,
            default_span_details=functools.partial(
                build_fastmcp_route_details_from_scope, routes=http_application.routes
            ),
            # OpenTelemetryMiddleware only parses a raw string from 0.56b0; the floor is 0.49b0.
            excluded_urls=parse_excluded_urls(",".join(self._build_excluded_url_patterns())),
            tracer_provider=get_tracer_provider(),
            meter_provider=get_meter_provider(),
        )
        setattr(http_application, _OPENTELEMETRY_INSTRUMENTED_MARKER, True)
        return http_application

    def bootstrap(self) -> None:
        super().bootstrap()
        self._restore_http_app = _postprocess_http_apps(self.bootstrap_config.application, self._instrument_http_app)

    def teardown(self) -> None:
        try:
            super().teardown()
        finally:
            if self._restore_http_app is not None:
                self._restore_http_app()
                self._restore_http_app = None


@dataclasses.dataclass(kw_only=True)
class FastMcpPrometheusInstrument(PrometheusInstrument):
    bootstrap_config: FastMcpConfig
    missing_dependency_message = "prometheus_client or prometheus_fastapi_instrumentator is not installed"
    _restore_http_app: typing.Callable[[], None] | None = dataclasses.field(
        default=None, init=False, repr=False, compare=False
    )
    _default_metrics: typing.Callable[..., typing.Any] | None = dataclasses.field(
        default=None, init=False, repr=False, compare=False
    )

    @staticmethod
    def dependencies_installed() -> bool:
        return (
            import_checker.is_prometheus_client_installed
            and import_checker.is_prometheus_fastapi_instrumentator_installed
        )

    def _instrument_http_app(self, http_application: "StarletteWithLifespan") -> "StarletteWithLifespan":
        config: typing.Final = self.bootstrap_config
        instrumentator_params: typing.Final[dict[str, typing.Any]] = {
            "excluded_handlers": [f"^{re.escape(config.prometheus_metrics_path)}$"],
            **config.prometheus_instrumentator_params,
        }
        # A second http_app() would register the default metrics again, which the instrumentator
        # treats as a duplicate and silently skips, so every application shares the first set.
        if self._default_metrics is None:
            default_metrics_params: typing.Final[dict[str, typing.Any]] = {
                name: value
                for name, value in {**instrumentator_params, **config.prometheus_instrument_params}.items()
                if name in _DEFAULT_METRICS_PARAMETERS
            }
            self._default_metrics = instrumentator_metrics.default(**default_metrics_params)
        Instrumentator(**instrumentator_params).add(self._default_metrics).instrument(
            http_application, **config.prometheus_instrument_params
        )
        return http_application

    def bootstrap(self) -> None:
        config = self.bootstrap_config
        self._restore_http_app = _postprocess_http_apps(config.application, self._instrument_http_app)
        if config.fastmcp_prometheus_tool_metrics_enabled:
            config.application.add_middleware(FastMcpPrometheusMiddleware(*_build_tool_call_metrics()))

        @config.application.custom_route(
            config.prometheus_metrics_path,
            methods=["GET"],
            name="metrics",
            include_in_schema=config.prometheus_metrics_include_in_schema,
        )
        async def metrics_handler(_: "Request") -> "Response":
            return Response(
                prometheus_client.generate_latest(prometheus_client.REGISTRY),
                headers={"content-type": prometheus_client.CONTENT_TYPE_LATEST},
            )

    def teardown(self) -> None:
        if self._restore_http_app is not None:
            self._restore_http_app()
            self._restore_http_app = None


@dataclasses.dataclass(kw_only=True)
class FastMcpLoggingInstrument(LoggingInstrument):
    bootstrap_config: FastMcpConfig

    def bootstrap(self) -> None:
        super().bootstrap()
        if not self.bootstrap_config.fastmcp_logging_middleware_enabled:
            return
        self.bootstrap_config.application.add_middleware(FastMcpLoggingMiddleware())


class FastMcpBootstrapper(BaseBootstrapper["FastMCP[typing.Any]"]):
    __slots__ = "bootstrap_config", "instruments"

    instruments_types: typing.ClassVar = [
        FastMcpOpenTelemetryInstrument,
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
        application = self.bootstrap_config.application
        self._attach_teardown_once(application, lambda: application.add_provider(_TeardownProvider(self.teardown)))

    def _prepare_application(self) -> "FastMCP[typing.Any]":
        return self.bootstrap_config.application
