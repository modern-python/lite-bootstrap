import dataclasses
import logging
import sys
import typing

from lite_bootstrap import import_checker
from lite_bootstrap.exceptions import collect_teardown_errors
from lite_bootstrap.instruments.base import BaseConfig, BaseInstrument
from lite_bootstrap.instruments.logging_factory import _serialize_log_to_string


if typing.TYPE_CHECKING:
    from structlog.typing import EventDict, WrappedLogger


class _RenderedLine(str):
    """A line structlog's chain already rendered, which the root handler's formatter emits as is."""

    __slots__ = ()


def _mark_rendered(_: "WrappedLogger", __: str, rendered_line: str) -> _RenderedLine:
    return _RenderedLine(rendered_line)


if import_checker.is_structlog_installed:
    import structlog

    class _RenderedLinePassthroughFormatter(structlog.stdlib.ProcessorFormatter):
        """Render stdlib records through the foreign chain, and emit structlog's rendered lines verbatim."""

        def format(self, record: logging.LogRecord) -> str:
            if type(record.msg) is _RenderedLine:
                return record.msg
            return super().format(record)


if import_checker.is_opentelemetry_installed:
    from opentelemetry import trace

    # `tracer_injection` adds the top-level `tracing` meta-key. Any new top-level
    # meta-processor added to the chain must register its key in
    # `STRUCTLOG_META_KEYS` (logging_factory.py) or it will leak into
    # StructuredLogPayload.extra and downstream Sentry context.
    def tracer_injection(_: "WrappedLogger", __: str, event_dict: "EventDict") -> "EventDict":
        current_span = trace.get_current_span()
        if not current_span.is_recording():
            event_dict["tracing"] = {}
            return event_dict

        current_span_context = current_span.get_span_context()
        event_dict["tracing"] = {
            "span_id": trace.format_span_id(current_span_context.span_id),
            "trace_id": trace.format_trace_id(current_span_context.trace_id),
        }
        return event_dict

else:  # pragma: no cover - only without opentelemetry, i.e. neither the [otl] nor the [otl-http] extra

    def tracer_injection(_: "WrappedLogger", __: str, event_dict: "EventDict") -> "EventDict":
        return event_dict


__all__ = [
    "LoggingConfig",
    "LoggingInstrument",
    "tracer_injection",
]


@dataclasses.dataclass(kw_only=True, frozen=True)
class LoggingConfig(BaseConfig):
    logging_log_level: int = logging.INFO
    logging_extra_processors: list[typing.Any] = dataclasses.field(default_factory=list)
    logging_unset_handlers: list[str] = dataclasses.field(
        default_factory=list,
    )
    logging_record_filters: dict[str, tuple[logging.Filter, ...]] = dataclasses.field(default_factory=dict)
    logging_time_stamper: "structlog.processors.TimeStamper | None" = None
    logging_enabled: bool = True


LoggingConfigT = typing.TypeVar("LoggingConfigT", bound=LoggingConfig)


@dataclasses.dataclass(kw_only=True, slots=True)
class LoggingInstrument(BaseInstrument[LoggingConfigT]):
    not_configured_reason = "logging_enabled is False"
    missing_dependency_message = "structlog is not installed"
    _attached_filters: list[tuple[logging.Logger, logging.Filter]] = dataclasses.field(
        default_factory=list, init=False, repr=False, compare=False
    )

    @property
    def structlog_pre_chain_processors(self) -> list[typing.Any]:
        return [
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            tracer_injection,
            structlog.stdlib.PositionalArgumentsFormatter(),
            self.bootstrap_config.logging_time_stamper or structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
        ]

    @classmethod
    def is_configured(cls, bootstrap_config: "LoggingConfig") -> bool:
        return bootstrap_config.logging_enabled

    @staticmethod
    def dependencies_installed() -> bool:
        return import_checker.is_structlog_installed

    def _unset_handlers(self) -> None:
        """Clear handlers on the named loggers. Mutation is permanent; teardown() does not restore."""
        for unset_handlers_logger in self.bootstrap_config.logging_unset_handlers:
            logging.getLogger(unset_handlers_logger).handlers = []

    def _build_excluded_paths(self) -> tuple[str, ...]:
        """Infrastructure routes not worth an access log line, normalized and deduplicated.

        Sibling paths are read with ``getattr`` because they live on the Swagger, HealthChecks and
        Prometheus configs, which a given framework's config need not mix in (see ADR-0002).
        """
        config = self.bootstrap_config
        offline_docs: typing.Final = getattr(config, "swagger_offline_docs", False)
        candidate_paths: typing.Final = (
            getattr(config, "swagger_path", ""),
            getattr(config, "swagger_static_path", "") if offline_docs else "",
            getattr(config, "health_checks_path", ""),
            getattr(config, "prometheus_metrics_path", ""),
        )
        excluded_paths: list[str] = []
        for candidate_path in candidate_paths:
            # A bare "/" would exclude every route, so it is dropped along with empty values.
            normalized_path = candidate_path.rstrip("/")
            if normalized_path and normalized_path not in excluded_paths:
                excluded_paths.append(normalized_path)
        return tuple(excluded_paths)

    @property
    def structlog_processors(self) -> list[typing.Any]:
        return [
            structlog.stdlib.filter_by_level,
            *self.structlog_pre_chain_processors,
            *self.bootstrap_config.logging_extra_processors,
            structlog.processors.JSONRenderer(serializer=_serialize_log_to_string),
            _mark_rendered,
        ]

    def _configure_structlog_loggers(self) -> None:
        structlog.configure(
            processors=self.structlog_processors,
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=True,
        )

    def _configure_foreign_loggers(self) -> None:
        root_logger: typing.Final = logging.getLogger()
        stream_handler: typing.Final = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(
            _RenderedLinePassthroughFormatter(
                foreign_pre_chain=self.structlog_pre_chain_processors,
                processors=[
                    structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                    *self.bootstrap_config.logging_extra_processors,
                    structlog.processors.JSONRenderer(serializer=_serialize_log_to_string),
                ],
                logger=root_logger,
            )
        )
        root_logger.addHandler(stream_handler)
        root_logger.setLevel(self.bootstrap_config.logging_log_level)

    def _attach_record_filters(self) -> None:
        """Attach each configured filter to its logger, remembering the pair for teardown."""
        for logger_name, record_filters in self.bootstrap_config.logging_record_filters.items():
            target_logger = logging.getLogger(logger_name)
            for record_filter in record_filters:
                target_logger.addFilter(record_filter)
                self._attached_filters.append((target_logger, record_filter))

    def _detach_record_filters(self) -> None:
        """Remove only the filters this instrument attached, leaving any others in place."""
        for target_logger, record_filter in self._attached_filters:
            target_logger.removeFilter(record_filter)
        self._attached_filters.clear()

    def bootstrap(self) -> None:
        self._unset_handlers()
        self._configure_structlog_loggers()
        self._configure_foreign_loggers()
        self._attach_record_filters()

    def teardown(self) -> None:
        """Reset structlog and root logger.

        Root logger level is unconditionally set to WARNING; pre-existing user configuration is overwritten.
        Filters from ``logging_record_filters`` are removed one pair at a time, so a filter the
        application or another library put on the same logger survives.

        Best-effort cleanup: errors from individual ``handler.close()`` calls are collected and
        re-raised together via :class:`~lite_bootstrap.exceptions.TeardownError` after the rest of
        teardown completes, so no single misbehaving handler keeps the others open.
        """
        structlog.reset_defaults()
        root_logger = logging.getLogger()
        with collect_teardown_errors() as teardown_errors:
            try:
                for h in root_logger.handlers[:]:
                    root_logger.removeHandler(h)
                    with teardown_errors.capture(type(h).__name__):
                        h.close()
                root_logger.setLevel(logging.WARNING)
            finally:
                self._detach_record_filters()
