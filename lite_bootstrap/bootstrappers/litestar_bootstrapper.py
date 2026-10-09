import dataclasses
import pathlib
import re
import typing

from lite_bootstrap import import_checker
from lite_bootstrap.bootstrappers.base import BaseBootstrapper
from lite_bootstrap.helpers.path import is_valid_path
from lite_bootstrap.helpers.warn import warn_at_caller
from lite_bootstrap.instruments.cors_instrument import CorsConfig, CorsInstrument
from lite_bootstrap.instruments.healthchecks_instrument import (
    HealthChecksConfig,
    HealthChecksInstrument,
    HealthCheckTypedDict,
)
from lite_bootstrap.instruments.logging_instrument import LoggingConfig, LoggingInstrument
from lite_bootstrap.instruments.opentelemetry_instrument import OpenTelemetryConfig, OpenTelemetryInstrument
from lite_bootstrap.instruments.prometheus_instrument import (
    PrometheusConfig as PrometheusBootstrapperConfig,
)
from lite_bootstrap.instruments.prometheus_instrument import (
    PrometheusInstrument,
)
from lite_bootstrap.instruments.pyroscope_instrument import PyroscopeConfig, PyroscopeInstrument
from lite_bootstrap.instruments.sentry_instrument import SentryConfig, SentryInstrument
from lite_bootstrap.instruments.swagger_instrument import SwaggerConfig, SwaggerInstrument


if import_checker.is_litestar_installed:
    import litestar
    from litestar.config.app import AppConfig
    from litestar.config.cors import CORSConfig
    from litestar.logging.config import StructLoggingConfig
    from litestar.middleware.logging import LoggingMiddlewareConfig
    from litestar.openapi import OpenAPIConfig
    from litestar.openapi.plugins import SwaggerRenderPlugin
    from litestar.plugins.structlog import StructlogConfig, StructlogPlugin
    from litestar.static_files import create_static_files_router
    from litestar.types import Empty

if import_checker.is_litestar_installed and import_checker.is_prometheus_client_installed:
    # litestar.plugins.prometheus imports prometheus_client, which the `litestar`
    # extra does not install (only `litestar-metrics` does). Used only inside
    # LitestarPrometheusInstrument.bootstrap(), gated by dependencies_installed() ->
    # is_prometheus_client_installed, so this guard matches the usage.
    from litestar.plugins.prometheus import PrometheusConfig, PrometheusController

if import_checker.is_litestar_opentelemetry_installed:
    from litestar.middleware import ASGIMiddleware
    from litestar.plugins.opentelemetry import OpenTelemetryConfig as LitestarOpenTelemetryConfig
    from litestar.plugins.opentelemetry import OpenTelemetryPlugin
    from litestar.types.asgi_types import ASGIApp, Receive, Scope, Send
    from opentelemetry import trace

if import_checker.is_opentelemetry_installed:
    from opentelemetry.metrics import get_meter_provider
    from opentelemetry.trace import get_tracer_provider

if import_checker.is_structlog_installed:
    import structlog


def build_span_name(method: str, route: str) -> str:
    if not route:
        return method
    return f"{method} {route}"


# Litestar's own defaults include `body`, `headers`, `cookies` and `query`, which leak
# credentials and dump static Swagger assets into the log. `path` is scope["path"],
# so dropping `query` costs only the query string.
_LOGGING_MIDDLEWARE_REQUEST_LOG_FIELDS: typing.Final = ("path", "method", "content_type", "path_params")
_LOGGING_MIDDLEWARE_RESPONSE_LOG_FIELDS: typing.Final = ("status_code",)

# Litestar.from_config() passes every AppConfig field explicitly, so the default that
# Litestar.__init__ applies never reaches an app built from a config. Pinned to Litestar's
# own default by a guard test. See https://github.com/litestar-org/litestar/issues/4296.
_LITESTAR_DEFAULT_REQUEST_MAX_BODY_SIZE: typing.Final = 10_000_000


def build_litestar_route_details_from_scope(
    scope: "Scope",
) -> tuple[str, dict[str, str]]:
    method: typing.Final = str(scope.get("method", "HTTP")).strip()
    path_template: typing.Final = scope.get("path_template")
    # Unmatched paths get no `http.route`: a raw path would let scanners explode span cardinality
    if path_template is None:
        return method, {}
    path_template_stripped: typing.Final = path_template.strip()
    return build_span_name(method, path_template_stripped), {"http.route": path_template_stripped}


if import_checker.is_litestar_opentelemetry_installed:

    class LitestarOpenTelemetryRouteMiddleware(ASGIMiddleware):
        # OpenTelemetryPlugin opens the server span before routing, so the route template is only known here
        async def handle(
            self,
            scope: "Scope",
            receive: "Receive",
            send: "Send",
            next_app: "ASGIApp",
        ) -> None:
            server_span: typing.Final = trace.get_current_span()
            if server_span.is_recording():
                span_name, attributes = build_litestar_route_details_from_scope(scope)
                server_span.update_name(span_name)
                server_span.set_attributes(attributes)
            await next_app(scope, receive, send)


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class LitestarConfig(
    CorsConfig,
    HealthChecksConfig,
    LoggingConfig,
    OpenTelemetryConfig,
    PrometheusBootstrapperConfig,
    PyroscopeConfig,
    SentryConfig,
    SwaggerConfig,
):
    application_config: "AppConfig" = dataclasses.field(default_factory=lambda: AppConfig())  # noqa: PLW0108
    litestar_logging_middleware_config: "LoggingMiddlewareConfig | None" = None
    litestar_logging_middleware_enabled: bool = False
    prometheus_additional_params: dict[str, typing.Any] = dataclasses.field(default_factory=dict)
    # Bounds path-label cardinality (Litestar defaults False -> raw URLs leak memory). See litestar#4891.
    prometheus_group_path: bool = True
    swagger_extra_params: dict[str, typing.Any] = dataclasses.field(default_factory=dict)

    def __post_init__(self) -> None:
        # @dataclass(slots=True) replaces the class object, breaking bare super().
        super(LitestarConfig, self).__post_init__()
        if self.litestar_logging_middleware_config is not None and not self.litestar_logging_middleware_enabled:
            warn_at_caller(
                "litestar_logging_middleware_config is ignored while litestar_logging_middleware_enabled is False; "
                "set litestar_logging_middleware_enabled=True to turn access logging on."
            )


@dataclasses.dataclass(kw_only=True, slots=True)
class LitestarCorsInstrument(CorsInstrument):
    bootstrap_config: LitestarConfig

    def bootstrap(self) -> None:
        self.bootstrap_config.application_config.cors_config = CORSConfig(**self.cors_kwargs)


@dataclasses.dataclass(kw_only=True, slots=True)
class LitestarHealthChecksInstrument(HealthChecksInstrument):
    bootstrap_config: LitestarConfig

    def build_litestar_health_check_router(self) -> "litestar.Router":
        @litestar.get(media_type=litestar.MediaType.JSON)
        async def health_check_handler() -> HealthCheckTypedDict:
            return self.render_health_check_data()

        return litestar.Router(
            path=self.bootstrap_config.health_checks_path,
            route_handlers=[health_check_handler],
            tags=["probes"],
            include_in_schema=self.bootstrap_config.health_checks_include_in_schema,
        )

    def bootstrap(self) -> None:
        self.bootstrap_config.application_config.route_handlers.append(self.build_litestar_health_check_router())


@dataclasses.dataclass(kw_only=True)
class LitestarLoggingInstrument(LoggingInstrument):
    bootstrap_config: LitestarConfig

    def _build_logging_middleware_excluded_paths(self) -> list[str]:
        """Regex-escaped path prefixes for infrastructure routes not worth an access log line."""
        # Litestar matches exclude patterns with an unanchored search, so anchor each one to the
        # path itself or a sub-path; a bare prefix would also suppress an unrelated /custom-healthy.
        return [rf"^{re.escape(excluded_path)}(?:/|$)" for excluded_path in self._build_excluded_paths()]

    def _build_logging_middleware_config(self) -> "LoggingMiddlewareConfig":
        # A caller-supplied config replaces the hardened defaults wholesale, no merging.
        if self.bootstrap_config.litestar_logging_middleware_config is not None:
            return self.bootstrap_config.litestar_logging_middleware_config
        excluded_paths: typing.Final = self._build_logging_middleware_excluded_paths()
        return LoggingMiddlewareConfig(
            request_log_fields=_LOGGING_MIDDLEWARE_REQUEST_LOG_FIELDS,
            response_log_fields=_LOGGING_MIDDLEWARE_RESPONSE_LOG_FIELDS,
            exclude=excluded_paths or None,
        )

    def _configure_structlog_loggers(self) -> None:
        """Register Litestar's StructlogPlugin instead of calling ``structlog.configure`` directly."""
        self.bootstrap_config.application_config.plugins.append(
            StructlogPlugin(
                config=StructlogConfig(
                    structlog_logging_config=StructLoggingConfig(
                        processors=self.structlog_processors,
                        logger_factory=self.memory_logger_factory,
                        wrapper_class=structlog.stdlib.BoundLogger,
                        cache_logger_on_first_use=True,
                        pretty_print_tty=False,
                        standard_lib_logging_config=None,
                    ),
                    # Litestar defaults this to True, which logs full request/response bodies.
                    enable_middleware_logging=self.bootstrap_config.litestar_logging_middleware_enabled,
                    middleware_logging_config=self._build_logging_middleware_config(),
                ),
            )
        )


@dataclasses.dataclass(kw_only=True)
class LitestarOpenTelemetryInstrument(OpenTelemetryInstrument):
    bootstrap_config: LitestarConfig
    missing_dependency_message = "opentelemetry-instrumentation-asgi or litestar>=2.22 is not installed"

    @staticmethod
    def dependencies_installed() -> bool:
        return OpenTelemetryInstrument.dependencies_installed() and import_checker.is_litestar_opentelemetry_installed

    def _build_excluded_path_patterns(self) -> list[str]:
        """Anchored patterns for the derived paths, plus the caller's own entries verbatim.

        The trailing slash is stripped and matched optionally, so ``/custom-health/`` excludes the
        path with or without it. Anchoring is needed because Litestar searches its ``exclude``
        patterns unanchored: a bare ``/custom-health`` would also silence ``/custom-healthy``.
        Caller-supplied entries stay untouched because they are regexes.
        """
        anchored_patterns: typing.Final = {
            rf"^{re.escape(normalized_path)}(?:/|$)"
            for excluded_path in self._build_infrastructure_excluded_paths()
            # A bare "/" would anchor to every URL, so it is dropped along with empty values.
            if (normalized_path := excluded_path.rstrip("/"))
        }
        return sorted(anchored_patterns | set(self.bootstrap_config.opentelemetry_excluded_urls))

    def bootstrap(self) -> None:
        super().bootstrap()
        application_config: typing.Final = self.bootstrap_config.application_config
        application_config.plugins.append(
            OpenTelemetryPlugin(
                LitestarOpenTelemetryConfig(
                    tracer_provider=get_tracer_provider(),
                    meter_provider=get_meter_provider(),
                    scope_span_details_extractor=build_litestar_route_details_from_scope,
                    # An empty list compiles to a pattern that matches, and so skips, every path
                    exclude=self._build_excluded_path_patterns() or None,
                )
            )
        )
        application_config.middleware.append(LitestarOpenTelemetryRouteMiddleware())


@dataclasses.dataclass(kw_only=True)
class LitestarPrometheusInstrument(PrometheusInstrument):
    bootstrap_config: LitestarConfig
    missing_dependency_message = "prometheus_client is not installed"

    @staticmethod
    def dependencies_installed() -> bool:
        return import_checker.is_prometheus_client_installed

    def bootstrap(self) -> None:
        config = self.bootstrap_config

        class LitestarPrometheusController(PrometheusController):
            path = config.prometheus_metrics_path
            include_in_schema = config.prometheus_metrics_include_in_schema
            openmetrics_format = True

        # Merged so prometheus_additional_params can override group_path without a kwarg collision.
        prometheus_params: dict[str, typing.Any] = {
            "group_path": config.prometheus_group_path,
            **config.prometheus_additional_params,
        }
        litestar_prometheus_config = PrometheusConfig(app_name=config.service_name, **prometheus_params)

        config.application_config.route_handlers.append(LitestarPrometheusController)
        config.application_config.middleware.append(litestar_prometheus_config.middleware)


@dataclasses.dataclass(kw_only=True)
class LitestarSwaggerInstrument(SwaggerInstrument):
    bootstrap_config: LitestarConfig
    not_configured_reason = "swagger_path is empty or not valid"

    @classmethod
    def is_configured(cls, bootstrap_config: "LitestarConfig") -> bool:  # ty: ignore[invalid-method-override]
        return bool(bootstrap_config.swagger_path) and is_valid_path(bootstrap_config.swagger_path)

    def bootstrap(self) -> None:
        config = self.bootstrap_config
        render_plugins: typing.Final = (
            (
                SwaggerRenderPlugin(
                    js_url=f"{config.swagger_static_path}/swagger-ui-bundle.js",
                    css_url=f"{config.swagger_static_path}/swagger-ui.css",
                    standalone_preset_js_url=f"{config.swagger_static_path}/swagger-ui-standalone-preset.js",
                ),
            )
            if config.swagger_offline_docs
            else (SwaggerRenderPlugin(),)
        )
        config.application_config.openapi_config = OpenAPIConfig(
            path=config.swagger_path,
            title=config.service_name,
            version=config.service_version,
            description=config.service_description,
            render_plugins=render_plugins,
            **config.swagger_extra_params,
        )
        if config.swagger_offline_docs:
            static_dir_path = pathlib.Path(__file__).parent.parent / "static/litestar_docs"
            config.application_config.route_handlers.append(
                create_static_files_router(path=config.swagger_static_path, directories=[static_dir_path])
            )


class LitestarBootstrapper(BaseBootstrapper["litestar.Litestar"]):
    __slots__ = "bootstrap_config", "instruments"

    instruments_types: typing.ClassVar = [
        LitestarCorsInstrument,
        LitestarOpenTelemetryInstrument,
        PyroscopeInstrument,
        SentryInstrument,
        LitestarHealthChecksInstrument,
        LitestarLoggingInstrument,
        LitestarPrometheusInstrument,
        LitestarSwaggerInstrument,
    ]
    bootstrap_config: LitestarConfig
    not_ready_message = "litestar is not installed"

    def __init__(self, bootstrap_config: LitestarConfig) -> None:
        super().__init__(bootstrap_config)
        application_config = self.bootstrap_config.application_config
        self._attach_teardown_once(application_config, lambda: self._apply_config(application_config))

    def _apply_config(self, application_config: "AppConfig") -> None:
        application_config.debug = self.bootstrap_config.service_debug
        # An Empty value reaches layer resolution and 500s every body-reading handler.
        if application_config.request_max_body_size is Empty:
            application_config.request_max_body_size = _LITESTAR_DEFAULT_REQUEST_MAX_BODY_SIZE
        application_config.on_shutdown.append(self.teardown)

    def is_ready(self) -> bool:
        return import_checker.is_litestar_installed

    def _prepare_application(self) -> "litestar.Litestar":
        return litestar.Litestar.from_config(self.bootstrap_config.application_config)
