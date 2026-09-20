import contextlib
import dataclasses
import time
import typing

from lite_bootstrap import import_checker
from lite_bootstrap.bootstrappers.base import BaseBootstrapper
from lite_bootstrap.exceptions import ConfigurationError
from lite_bootstrap.helpers.fastapi_helpers import enable_offline_docs
from lite_bootstrap.helpers.warn import warn_at_caller
from lite_bootstrap.instruments.cors_instrument import CorsConfig, CorsInstrument
from lite_bootstrap.instruments.healthchecks_instrument import (
    HealthChecksConfig,
    HealthChecksInstrument,
    HealthCheckTypedDict,
)
from lite_bootstrap.instruments.logging_instrument import LoggingConfig, LoggingInstrument
from lite_bootstrap.instruments.opentelemetry_instrument import OpenTelemetryConfig, OpenTelemetryInstrument
from lite_bootstrap.instruments.prometheus_instrument import PrometheusConfig, PrometheusInstrument
from lite_bootstrap.instruments.pyroscope_instrument import PyroscopeConfig, PyroscopeInstrument
from lite_bootstrap.instruments.sentry_instrument import SentryConfig, SentryInstrument
from lite_bootstrap.instruments.swagger_instrument import SwaggerConfig, SwaggerInstrument
from lite_bootstrap.types import UNSET, UnsetType


if typing.TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

if import_checker.is_fastapi_installed:
    import fastapi
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.routing import _merge_lifespan_context

if import_checker.is_structlog_installed:
    import structlog

    fastapi_access_logger: typing.Final = structlog.get_logger("http.access")

if import_checker.is_opentelemetry_installed:
    from opentelemetry.trace import get_tracer_provider

if import_checker.is_fastapi_opentelemetry_installed:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

if import_checker.is_prometheus_fastapi_instrumentator_installed:
    from prometheus_fastapi_instrumentator import Instrumentator


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class FastAPIConfig(
    CorsConfig,
    HealthChecksConfig,
    LoggingConfig,
    OpenTelemetryConfig,
    PrometheusConfig,
    PyroscopeConfig,
    SentryConfig,
    SwaggerConfig,
):
    application: "fastapi.FastAPI | UnsetType" = UNSET
    application_kwargs: dict[str, typing.Any] = dataclasses.field(default_factory=dict)
    # Not on OpenTelemetryConfig: `exclude_spans` is this instrumentor's parameter, and Litestar's has none.
    opentelemetry_exclude_spans: list[typing.Literal["receive", "send"]] = dataclasses.field(default_factory=list)
    prometheus_instrumentator_params: dict[str, typing.Any] = dataclasses.field(default_factory=dict)
    prometheus_instrument_params: dict[str, typing.Any] = dataclasses.field(default_factory=dict)
    prometheus_expose_params: dict[str, typing.Any] = dataclasses.field(default_factory=dict)
    fastapi_logging_middleware_enabled: bool = False

    def __post_init__(self) -> None:
        # @dataclass(slots=True) replaces the class object, breaking bare super().
        super(FastAPIConfig, self).__post_init__()
        if not import_checker.is_fastapi_installed:
            msg = "fastapi is not installed"
            raise ConfigurationError(msg)

        if isinstance(self.application, UnsetType):
            application = fastapi.FastAPI(docs_url=self.swagger_path, **self.application_kwargs)
            # FastAPIConfig stays frozen for user-facing immutability; __post_init__ needs
            # to set application after construction, so we bypass the freeze here.
            object.__setattr__(self, "application", application)
            application.title = self.service_name
            application.debug = self.service_debug
            application.version = self.service_version
        elif self.application_kwargs:
            warn_at_caller("application_kwargs must be used without application")

    @property
    def app(self) -> "fastapi.FastAPI":
        """The application narrowed past the UNSET sentinel that ``__post_init__`` has replaced."""
        if isinstance(self.application, UnsetType):
            msg = "FastAPIConfig.application is UNSET; __post_init__ did not run"
            raise TypeError(msg)
        return self.application


class _AccessLogMiddleware:
    """One structured line per request, pure ASGI.

    Not `BaseHTTPMiddleware`: that one buffers the response, which breaks streaming
    responses and background tasks.
    """

    def __init__(self, app: "ASGIApp", *, excluded_paths: tuple[str, ...]) -> None:
        self.app = app
        self.excluded_paths = excluded_paths

    def _is_excluded(self, path: str) -> bool:
        normalized_path = path.rstrip("/")
        return any(
            normalized_path == excluded_path or normalized_path.startswith(f"{excluded_path}/")
            for excluded_path in self.excluded_paths
        )

    @staticmethod
    def _http_fields(scope: "Scope", status_code: int) -> dict[str, typing.Any]:
        content_type = ""
        for header_name, header_value in scope.get("headers", ()):
            if header_name == b"content-type":
                content_type = header_value.decode("latin-1")
                break
        return {
            "method": scope.get("method", ""),
            "path": scope.get("path", ""),
            "content_type": content_type,
            "path_params": scope.get("path_params", {}),
            "status_code": status_code,
        }

    async def __call__(self, scope: "Scope", receive: "Receive", send: "Send") -> None:
        if scope["type"] != "http" or self._is_excluded(scope["path"]):
            await self.app(scope, receive, send)
            return

        status_code = 0

        async def send_wrapper(message: "Message") -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        started_at = time.perf_counter_ns()
        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            fastapi_access_logger.exception(
                "http_request",
                http=self._http_fields(scope, status_code),
                duration=time.perf_counter_ns() - started_at,
            )
            raise
        fastapi_access_logger.info(
            "http_request",
            http=self._http_fields(scope, status_code),
            duration=time.perf_counter_ns() - started_at,
        )


@dataclasses.dataclass(kw_only=True)
class FastAPILoggingInstrument(LoggingInstrument):
    bootstrap_config: FastAPIConfig

    def _build_excluded_paths(self) -> tuple[str, ...]:
        """Infrastructure routes not worth an access log line, normalized and deduplicated."""
        config = self.bootstrap_config
        candidate_paths: typing.Final = (
            config.swagger_path,
            config.swagger_static_path if config.swagger_offline_docs else "",
            config.health_checks_path,
            config.prometheus_metrics_path,
        )
        excluded_paths: list[str] = []
        for candidate_path in candidate_paths:
            # A bare "/" would exclude every route, so it is dropped along with empty values.
            normalized_path = candidate_path.rstrip("/")
            if normalized_path and normalized_path not in excluded_paths:
                excluded_paths.append(normalized_path)
        return tuple(excluded_paths)

    def bootstrap(self) -> None:
        super().bootstrap()
        if not self.bootstrap_config.fastapi_logging_middleware_enabled:
            return
        self.bootstrap_config.app.add_middleware(_AccessLogMiddleware, excluded_paths=self._build_excluded_paths())


@dataclasses.dataclass(kw_only=True, slots=True)
class FastAPICorsInstrument(CorsInstrument):
    bootstrap_config: FastAPIConfig

    def bootstrap(self) -> None:
        self.bootstrap_config.app.add_middleware(CORSMiddleware, **self.cors_kwargs)


@dataclasses.dataclass(kw_only=True, slots=True)
class FastAPIHealthChecksInstrument(HealthChecksInstrument):
    bootstrap_config: FastAPIConfig

    def build_fastapi_health_check_router(self) -> "fastapi.APIRouter":
        fastapi_router = fastapi.APIRouter(
            tags=["probes"],
            include_in_schema=self.bootstrap_config.health_checks_include_in_schema,
        )

        @fastapi_router.get(self.bootstrap_config.health_checks_path)
        async def health_check_handler() -> HealthCheckTypedDict:
            return self.render_health_check_data()

        return fastapi_router

    def bootstrap(self) -> None:
        self.bootstrap_config.app.include_router(self.build_fastapi_health_check_router())


@dataclasses.dataclass(kw_only=True)
class FastAPIOpenTelemetryInstrument(OpenTelemetryInstrument):
    bootstrap_config: FastAPIConfig

    def bootstrap(self) -> None:
        super().bootstrap()
        FastAPIInstrumentor.instrument_app(
            app=self.bootstrap_config.app,
            tracer_provider=get_tracer_provider(),
            excluded_urls=",".join(self._build_excluded_urls()),
            exclude_spans=self.bootstrap_config.opentelemetry_exclude_spans,
        )

    def teardown(self) -> None:
        FastAPIInstrumentor.uninstrument_app(self.bootstrap_config.app)
        super().teardown()


@dataclasses.dataclass(kw_only=True)
class FastAPIPrometheusInstrument(PrometheusInstrument):
    bootstrap_config: FastAPIConfig
    missing_dependency_message = "prometheus_fastapi_instrumentator is not installed"

    @staticmethod
    def dependencies_installed() -> bool:
        return import_checker.is_prometheus_fastapi_instrumentator_installed

    def bootstrap(self) -> None:
        config = self.bootstrap_config
        application = config.app
        Instrumentator(**config.prometheus_instrumentator_params).instrument(
            application,
            **config.prometheus_instrument_params,
        ).expose(
            application,
            endpoint=config.prometheus_metrics_path,
            include_in_schema=config.prometheus_metrics_include_in_schema,
            **config.prometheus_expose_params,
        )


@dataclasses.dataclass(kw_only=True)
class FastAPISwaggerInstrument(SwaggerInstrument):
    bootstrap_config: FastAPIConfig

    def bootstrap(self) -> None:
        config = self.bootstrap_config
        application = config.app
        if config.swagger_path != application.docs_url:
            warn_at_caller(f"swagger_path differs from docs_url, {application.docs_url} will be used for docs path")
        if config.swagger_offline_docs:
            enable_offline_docs(application, static_path=config.swagger_static_path)


class FastAPIBootstrapper(BaseBootstrapper["fastapi.FastAPI"]):
    __slots__ = "bootstrap_config", "instruments"

    instruments_types: typing.ClassVar = [
        FastAPICorsInstrument,
        FastAPIOpenTelemetryInstrument,
        PyroscopeInstrument,
        SentryInstrument,
        FastAPIHealthChecksInstrument,
        FastAPILoggingInstrument,
        FastAPIPrometheusInstrument,
        FastAPISwaggerInstrument,
    ]
    bootstrap_config: FastAPIConfig
    not_ready_message = "fastapi is not installed"

    @contextlib.asynccontextmanager
    async def lifespan_manager(self, _: "fastapi.FastAPI") -> typing.AsyncIterator[dict[str, typing.Any]]:
        try:
            yield {}
        finally:
            self.teardown()

    def __init__(self, bootstrap_config: FastAPIConfig) -> None:
        super().__init__(bootstrap_config)
        application = self.bootstrap_config.app
        self._attach_teardown_once(application, lambda: self._wrap_lifespan(application))

    def _wrap_lifespan(self, application: "fastapi.FastAPI") -> None:
        old_lifespan_manager = application.router.lifespan_context
        application.router.lifespan_context = _merge_lifespan_context(
            old_lifespan_manager,
            self.lifespan_manager,
        )

    def is_ready(self) -> bool:
        return import_checker.is_fastapi_installed

    def _prepare_application(self) -> "fastapi.FastAPI":
        return self.bootstrap_config.app
