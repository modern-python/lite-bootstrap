import dataclasses
import logging
import logging.handlers
import sys
import typing

import orjson

from lite_bootstrap import import_checker
from lite_bootstrap.instruments.base import BaseConfig, BaseInstrument


if typing.TYPE_CHECKING:
    from structlog.typing import EventDict, WrappedLogger


if import_checker.is_structlog_installed:
    import structlog


if import_checker.is_opentelemetry_installed:
    from opentelemetry import trace

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

else:  # pragma: no cover

    def tracer_injection(_: "WrappedLogger", __: str, event_dict: "EventDict") -> "EventDict":
        return event_dict


ScopeType = typing.MutableMapping[str, typing.Any]


class AddressProtocol(typing.Protocol):
    host: str
    port: int


class RequestProtocol(typing.Protocol):
    client: AddressProtocol
    scope: ScopeType
    method: str


if import_checker.is_structlog_installed:

    class MemoryLoggerFactory(structlog.stdlib.LoggerFactory):
        def __init__(
            self,
            *args: typing.Any,  # noqa: ANN401
            logging_buffer_capacity: int,
            logging_flush_level: int,
            logging_log_level: int,
            log_stream: typing.Any = sys.stdout,  # noqa: ANN401
            **kwargs: typing.Any,  # noqa: ANN401
        ) -> None:
            super().__init__(*args, **kwargs)
            self.logging_buffer_capacity = logging_buffer_capacity
            self.logging_flush_level = logging_flush_level
            self.logging_log_level = logging_log_level
            self.log_stream = log_stream
            self._created_handlers: list[tuple[logging.Logger, logging.handlers.MemoryHandler]] = []

        def __call__(self, *args: typing.Any) -> logging.Logger:  # noqa: ANN401
            logger: typing.Final = super().__call__(*args)
            stream_handler: typing.Final = logging.StreamHandler(stream=self.log_stream)
            handler: typing.Final = logging.handlers.MemoryHandler(
                capacity=self.logging_buffer_capacity,
                flushLevel=self.logging_flush_level,
                target=stream_handler,
            )
            logger.addHandler(handler)
            logger.setLevel(self.logging_log_level)
            logger.propagate = False
            self._created_handlers.append((logger, handler))
            return logger

        def close_handlers(self) -> None:
            for created_logger, handler in self._created_handlers:
                created_logger.removeHandler(handler)
                created_logger.propagate = True
                target = handler.target
                handler.close()
                if target is not None:
                    target.close()
            self._created_handlers.clear()

    def _serialize_log_with_orjson_to_string(value: typing.Any, **kwargs: typing.Any) -> str:  # noqa: ANN401
        return orjson.dumps(value, **kwargs).decode()


@dataclasses.dataclass(kw_only=True, frozen=True)
class LoggingConfig(BaseConfig):
    logging_log_level: int = logging.INFO
    logging_flush_level: int = logging.ERROR
    logging_buffer_capacity: int = 10
    logging_extra_processors: list[typing.Any] = dataclasses.field(default_factory=list)
    logging_unset_handlers: list[str] = dataclasses.field(
        default_factory=list,
    )
    logging_time_stamper: "structlog.processors.TimeStamper | None" = None
    logging_enabled: bool = True


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class LoggingInstrument(BaseInstrument):
    bootstrap_config: LoggingConfig
    not_ready_message = "logging_enabled is False"
    missing_dependency_message = "structlog is not installed"
    _logger_factory: "MemoryLoggerFactory | None" = dataclasses.field(
        default_factory=lambda: None, init=False, repr=False, compare=False
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

    def is_ready(self) -> bool:
        return self.bootstrap_config.logging_enabled

    @staticmethod
    def check_dependencies() -> bool:
        return import_checker.is_structlog_installed

    def _unset_handlers(self) -> None:
        for unset_handlers_logger in self.bootstrap_config.logging_unset_handlers:
            logging.getLogger(unset_handlers_logger).handlers = []

    @property
    def structlog_processors(self) -> list[typing.Any]:
        return [
            structlog.stdlib.filter_by_level,
            *self.structlog_pre_chain_processors,
            *self.bootstrap_config.logging_extra_processors,
            structlog.processors.JSONRenderer(serializer=_serialize_log_with_orjson_to_string),
        ]

    @property
    def memory_logger_factory(self) -> "MemoryLoggerFactory":
        cached: MemoryLoggerFactory | None = self._logger_factory
        if cached is None:
            cached = MemoryLoggerFactory(
                logging_buffer_capacity=self.bootstrap_config.logging_buffer_capacity,
                logging_flush_level=self.bootstrap_config.logging_flush_level,
                logging_log_level=self.bootstrap_config.logging_log_level,
            )
            object.__setattr__(self, "_logger_factory", cached)
        return cached

    def _configure_structlog_loggers(self) -> None:
        structlog.configure(
            processors=self.structlog_processors,
            context_class=dict,
            logger_factory=self.memory_logger_factory,
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=True,
        )

    def _configure_foreign_loggers(self) -> None:
        root_logger: typing.Final = logging.getLogger()
        stream_handler: typing.Final = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(
            structlog.stdlib.ProcessorFormatter(
                foreign_pre_chain=self.structlog_pre_chain_processors,
                processors=[
                    structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                    *self.bootstrap_config.logging_extra_processors,
                    structlog.processors.JSONRenderer(serializer=_serialize_log_with_orjson_to_string),
                ],
                logger=root_logger,
            )
        )
        root_logger.addHandler(stream_handler)
        root_logger.setLevel(self.bootstrap_config.logging_log_level)

    def bootstrap(self) -> None:
        self._unset_handlers()
        self._configure_structlog_loggers()
        self._configure_foreign_loggers()

    def teardown(self) -> None:
        structlog.reset_defaults()
        root_logger = logging.getLogger()
        for h in root_logger.handlers[:]:
            root_logger.removeHandler(h)
            h.close()
        root_logger.setLevel(logging.WARNING)
        if self._logger_factory is not None:
            try:
                self._logger_factory.close_handlers()
            finally:
                object.__setattr__(self, "_logger_factory", None)
