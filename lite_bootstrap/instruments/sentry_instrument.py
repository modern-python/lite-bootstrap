import dataclasses
import typing

import orjson

from lite_bootstrap import import_checker
from lite_bootstrap.instruments.base import BaseConfig, BaseInstrument


if typing.TYPE_CHECKING:
    from sentry_sdk import _types as sentry_types
    from sentry_sdk.integrations import Integration


if import_checker.is_sentry_installed:
    import sentry_sdk


IGNORED_STRUCTLOG_ATTRIBUTES: typing.Final = frozenset(
    {"event", "level", "logger", "tracing", "timestamp", "exception"}
)


@dataclasses.dataclass(kw_only=True, frozen=True)
class SentryConfig(BaseConfig):
    sentry_dsn: str | None = None
    sentry_traces_sample_rate: float | None = None
    sentry_sample_rate: float = 1.0
    sentry_max_breadcrumbs: int = 15
    sentry_max_value_length: int = 16384
    sentry_attach_stacktrace: bool = True
    sentry_integrations: list["Integration"] = dataclasses.field(default_factory=list)
    sentry_additional_params: dict[str, typing.Any] = dataclasses.field(default_factory=dict)
    sentry_tags: dict[str, str] | None = None
    sentry_default_integrations: bool = True
    sentry_before_send: typing.Callable[[typing.Any, typing.Any], typing.Any | None] | None = None


def enrich_sentry_event_from_structlog_log(
    event: "sentry_types.Event", _: "sentry_types.Hint"
) -> typing.Optional["sentry_types.Event"]:
    if (
        (logentry := event.get("logentry"))
        and (formatted_message := logentry.get("formatted"))
        and (isinstance(formatted_message, str))
        and formatted_message.startswith("{")
        and (isinstance(event.get("contexts"), dict))
    ):
        try:
            loaded_formatted_log = orjson.loads(formatted_message)
        except orjson.JSONDecodeError:
            return event

        if not isinstance(loaded_formatted_log, dict):  # pragma: no cover
            return event

        if loaded_formatted_log.get("skip_sentry"):
            return None

        if event_name := loaded_formatted_log.get("event"):
            event["logentry"]["formatted"] = event_name  # type: ignore[index]
        else:
            return event

        additional_extra = loaded_formatted_log
        for one_attr in IGNORED_STRUCTLOG_ATTRIBUTES:
            additional_extra.pop(one_attr, None)
        if additional_extra:
            event["contexts"]["structlog"] = additional_extra

    return event


def wrap_before_send_callbacks(
    *callbacks: typing.Optional["sentry_types.EventProcessor"],
) -> "sentry_types.EventProcessor":
    def run_before_send(
        event: "sentry_types.Event", hint: "sentry_types.Hint"
    ) -> typing.Optional["sentry_types.Event"]:
        for callback in callbacks:
            if not callback:
                continue

            temp_event = callback(event, hint)
            if temp_event is None:
                return None

            event = temp_event
        return event

    return run_before_send


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class SentryInstrument(BaseInstrument):
    bootstrap_config: SentryConfig
    not_ready_message = "sentry_dsn is empty"
    missing_dependency_message = "sentry_sdk is not installed"

    def is_ready(self) -> bool:
        return bool(self.bootstrap_config.sentry_dsn) and import_checker.is_sentry_installed

    @staticmethod
    def check_dependencies() -> bool:
        return import_checker.is_sentry_installed

    def bootstrap(self) -> None:
        sentry_sdk.init(
            dsn=self.bootstrap_config.sentry_dsn,
            sample_rate=self.bootstrap_config.sentry_sample_rate,
            traces_sample_rate=self.bootstrap_config.sentry_traces_sample_rate,
            environment=self.bootstrap_config.service_environment,
            max_breadcrumbs=self.bootstrap_config.sentry_max_breadcrumbs,
            max_value_length=self.bootstrap_config.sentry_max_value_length,
            attach_stacktrace=self.bootstrap_config.sentry_attach_stacktrace,
            integrations=self.bootstrap_config.sentry_integrations,
            before_send=wrap_before_send_callbacks(
                enrich_sentry_event_from_structlog_log, self.bootstrap_config.sentry_before_send
            ),
            **self.bootstrap_config.sentry_additional_params,
        )
        tags: dict[str, str] = self.bootstrap_config.sentry_tags or {}
        sentry_sdk.set_tags(tags)
