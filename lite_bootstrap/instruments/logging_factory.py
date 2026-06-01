import dataclasses
import logging
import logging.handlers
import sys
import typing

import orjson

from lite_bootstrap import import_checker


ScopeType = typing.MutableMapping[str, typing.Any]


class AddressProtocol(typing.Protocol):
    host: str
    port: int


class RequestProtocol(typing.Protocol):
    client: AddressProtocol
    scope: ScopeType
    method: str


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class _MemoryLoggerFactoryConfig:
    logging_buffer_capacity: int
    logging_flush_level: int
    logging_log_level: int
    log_stream: typing.Any = sys.stdout


def _serialize_log_with_orjson_to_string(value: typing.Any, **kwargs: typing.Any) -> str:  # noqa: ANN401
    return orjson.dumps(value, **kwargs).decode()


if import_checker.is_structlog_installed:
    import structlog

    class MemoryLoggerFactory(structlog.stdlib.LoggerFactory):
        def __init__(
            self,
            *args: typing.Any,  # noqa: ANN401
            config: "_MemoryLoggerFactoryConfig",
            **kwargs: typing.Any,  # noqa: ANN401
        ) -> None:
            super().__init__(*args, **kwargs)
            self.config = config
            self._created_handlers: list[tuple[logging.Logger, logging.handlers.MemoryHandler]] = []

        def __call__(self, *args: typing.Any) -> logging.Logger:  # noqa: ANN401
            logger: typing.Final = super().__call__(*args)
            stream_handler: typing.Final = logging.StreamHandler(stream=self.config.log_stream)
            handler: typing.Final = logging.handlers.MemoryHandler(
                capacity=self.config.logging_buffer_capacity,
                flushLevel=self.config.logging_flush_level,
                target=stream_handler,
            )
            logger.addHandler(handler)
            logger.setLevel(self.config.logging_log_level)
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
