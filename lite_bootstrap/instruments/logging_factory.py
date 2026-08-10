import dataclasses
import json
import logging
import logging.handlers
import sys
import typing

from lite_bootstrap import import_checker


if import_checker.is_orjson_installed:
    import orjson


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
    # default_factory, not a bare default: a bare one binds sys.stdout at import time, so a
    # process that rebinds stdout before bootstrap would keep logging to the stale stream.
    log_stream: typing.Any = dataclasses.field(default_factory=lambda: sys.stdout)


def _dumps_orjson(value: typing.Any, **kwargs: typing.Any) -> str:  # noqa: ANN401
    return orjson.dumps(value, **kwargs).decode()


def _dumps_stdlib(value: typing.Any, **kwargs: typing.Any) -> str:  # noqa: ANN401
    # Match orjson's compact, UTF-8 output shape so log lines stay byte-identical.
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False, **kwargs)


# orjson has no free-threaded wheels and refuses to build on ft; fall back to the
# stdlib json accelerator (always ft-native) when it is absent.
# See architecture/free-threading.md.
_serialize_log_to_string = _dumps_orjson if import_checker.is_orjson_installed else _dumps_stdlib
_json_loads = orjson.loads if import_checker.is_orjson_installed else json.loads


# Meta-keys the producer's structlog processor chain emits at the top level of every
# rendered line (see lite_bootstrap/instruments/logging_instrument.py). They are not
# user-supplied extra and are stripped from StructuredLogPayload.extra. If you add a
# custom top-level meta-processor to that chain, add its key here.
STRUCTLOG_META_KEYS: typing.Final = frozenset(
    {"event", "level", "logger", "tracing", "timestamp", "exception", "skip_sentry"}
)


@dataclasses.dataclass(frozen=True, slots=True)
class StructuredLogPayload:
    """The semantic content of one rendered structlog line.

    A consumer-side interpretation type: ``parse`` turns the raw JSON string a
    structlog processor chain emits into its parts. It holds no knowledge of any
    downstream event shape (e.g. Sentry's); mapping onto a consumer's event is the
    consumer's job.
    """

    message: str | None
    extra: dict[str, typing.Any]
    skip_sentry: bool

    @classmethod
    def parse(cls, formatted: str) -> "StructuredLogPayload | None":
        """Interpret one rendered structlog line.

        Returns ``None`` when ``formatted`` is not a structlog JSON object (not a
        JSON object string, a decode error, or a non-dict result).
        """
        if not formatted.startswith("{"):
            return None
        try:
            loaded = _json_loads(formatted)
        except json.JSONDecodeError:  # orjson.JSONDecodeError subclasses this
            return None
        if not isinstance(loaded, dict):  # pragma: no cover - JSON starting with "{" is always an object
            return None

        skip_sentry = bool(loaded.get("skip_sentry"))
        message = loaded.get("event")
        extra = {key: value for key, value in loaded.items() if key not in STRUCTLOG_META_KEYS}
        return cls(message=message, extra=extra, skip_sentry=skip_sentry)


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
