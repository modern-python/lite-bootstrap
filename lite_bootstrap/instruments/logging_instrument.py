import contextlib
import dataclasses
import logging
import logging.handlers
import typing

from lite_bootstrap.instruments.base import BaseConfig, BaseInstrument


if typing.TYPE_CHECKING:
    from structlog.typing import EventDict, WrappedLogger


with contextlib.suppress(ImportError):
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

    event_dict["tracing"] = {}
    current_span = trace.get_current_span()
    if current_span == trace.INVALID_SPAN:
        return event_dict

    span_context = current_span.get_span_context()
    if span_context == trace.INVALID_SPAN_CONTEXT:  # pragma: no cover
        return event_dict

    event_dict["tracing"]["trace_id"] = format(span_context.span_id, "016x")
    event_dict["tracing"]["span_id"] = format(span_context.trace_id, "032x")

    return event_dict


DEFAULT_STRUCTLOG_PROCESSORS: typing.Final[list[typing.Any]] = [
    structlog.stdlib.filter_by_level,
    structlog.stdlib.add_log_level,
    structlog.stdlib.add_logger_name,
    tracer_injection,
    structlog.stdlib.PositionalArgumentsFormatter(),
    structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S"),
    structlog.processors.StackInfoRenderer(),
    structlog.processors.format_exc_info,
    structlog.processors.UnicodeDecoder(),
]
DEFAULT_STRUCTLOG_FORMATTER_PROCESSOR: typing.Final = structlog.processors.JSONRenderer()


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

    def is_ready(self) -> bool:
        return not self.bootstrap_config.service_debug

    def bootstrap(self) -> None:
        for unset_handlers_logger in self.bootstrap_config.logging_unset_handlers:
            logging.getLogger(unset_handlers_logger).handlers = []

        structlog.configure(
            processors=[
                *DEFAULT_STRUCTLOG_PROCESSORS,
                *self.bootstrap_config.logging_extra_processors,
                DEFAULT_STRUCTLOG_FORMATTER_PROCESSOR,
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
