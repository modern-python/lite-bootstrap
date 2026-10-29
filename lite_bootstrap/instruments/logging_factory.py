import dataclasses
import json
import typing

from lite_bootstrap import import_checker


if import_checker.is_orjson_installed:
    import orjson


def _dumps_orjson(value: typing.Any, **kwargs: typing.Any) -> str:  # noqa: ANN401
    return orjson.dumps(value, **kwargs).decode()


def _dumps_stdlib(value: typing.Any, **kwargs: typing.Any) -> str:  # noqa: ANN401
    # Match orjson's compact, UTF-8 output shape so log lines stay byte-identical.
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False, **kwargs)


# orjson has no free-threaded wheels and refuses to build on ft; fall back to the
# stdlib json accelerator (always ft-native) when it is absent. See ADR-0004.
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
