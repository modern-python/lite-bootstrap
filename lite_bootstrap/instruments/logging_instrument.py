import dataclasses
import logging
import logging.handlers
import sys
import typing

from lite_bootstrap import import_checker
from lite_bootstrap.instruments.base import BaseConfig, BaseInstrument


if typing.TYPE_CHECKING:
    from structlog.typing import EventDict, WrappedLogger


if import_checker.is_structlog_installed:
    import structlog


ScopeType = typing.MutableMapping[str, typing.Any]


class AddressProtocol(typing.Protocol):
    host: str
    port: int


class RequestProtocol(typing.Protocol):
    client: AddressProtocol
    scope: ScopeType
    method: str


def tracer_injection(_: "WrappedLogger", __: str, event_dict: "EventDict") -> "EventDict":
    try:
        from opentelemetry import trace
    except ImportError:  # pragma: no cover
        return event_dict

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


class MemoryLoggerFactory(structlog.stdlib.LoggerFactory):
    def __init__(
        self,
        *args: typing.Any,  # noqa: ANN401
        logging_buffer_capacity: int,
        logging_flush_level: int,
        logging_log_level: int,
        log_stream: typing.Any = None,  # noqa: ANN401
        **kwargs: typing.Any,  # noqa: ANN401
    ) -> None:
        super().__init__(*args, **kwargs)
        self.logging_buffer_capacity = logging_buffer_capacity
        self.logging_flush_level = logging_flush_level
        self.logging_log_level = logging_log_level
        self.log_stream = log_stream

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
        return logger


@dataclasses.dataclass(kw_only=True, frozen=True)
class LoggingConfig(BaseConfig):
    logging_log_level: int = logging.INFO
    logging_flush_level: int = logging.ERROR
    logging_buffer_capacity: int = 10
    logging_extra_processors: list[typing.Any] = dataclasses.field(default_factory=list)
    logging_unset_handlers: list[str] = dataclasses.field(
        default_factory=list,
    )


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class LoggingInstrument(BaseInstrument):
    bootstrap_config: LoggingConfig
    not_ready_message = "service_debug is True or structlog is not installed"

    def is_ready(self) -> bool:
        return not self.bootstrap_config.service_debug and import_checker.is_structlog_installed

    def bootstrap(self) -> None:
        # Configure basic logging to allow structlog to catch its events
        logging.basicConfig(
            format="%(message)s",
            stream=sys.stdout,
            level=logging.INFO,
        )

        for unset_handlers_logger in self.bootstrap_config.logging_unset_handlers:
            logging.getLogger(unset_handlers_logger).handlers = []

        structlog.configure(
            processors=[
                structlog.stdlib.filter_by_level,
                structlog.stdlib.add_log_level,
                structlog.stdlib.add_logger_name,
                tracer_injection,
                structlog.stdlib.PositionalArgumentsFormatter(),
                structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S"),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.processors.UnicodeDecoder(),
                *self.bootstrap_config.logging_extra_processors,
                structlog.processors.JSONRenderer(),
            ],
            context_class=dict,
            logger_factory=MemoryLoggerFactory(
                logging_buffer_capacity=self.bootstrap_config.logging_buffer_capacity,
                logging_flush_level=self.bootstrap_config.logging_flush_level,
                logging_log_level=self.bootstrap_config.logging_log_level,
            ),
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=True,
        )

    def teardown(self) -> None:
        structlog.reset_defaults()
