import dataclasses
import typing

from lite_bootstrap import import_checker
from lite_bootstrap.instruments.base import BaseConfig, BaseInstrument
from lite_bootstrap.instruments.logging_factory import STRUCTLOG_META_KEYS, StructuredLogPayload


if typing.TYPE_CHECKING:
    from sentry_sdk import _types as sentry_types
    from sentry_sdk.integrations import Integration


if import_checker.is_sentry_installed:
    import sentry_sdk


# Back-compat alias: this vocabulary moved to logging_factory and was renamed
# STRUCTLOG_META_KEYS. Preserved here for external importers of the old name.
IGNORED_STRUCTLOG_ATTRIBUTES: typing.Final = STRUCTLOG_META_KEYS


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
    sentry_before_send: "sentry_types.EventProcessor | None" = None


def enrich_sentry_event_from_structlog_log(
    event: "sentry_types.Event", _: "sentry_types.Hint"
) -> typing.Optional["sentry_types.Event"]:
    if not (
        (logentry := event.get("logentry"))
        and (formatted_message := logentry.get("formatted"))
        and isinstance(formatted_message, str)
        and isinstance(event.get("contexts"), dict)
    ):
        return event

    payload = StructuredLogPayload.parse(formatted_message)
    if payload is None:
        return event
    if payload.skip_sentry:
        return None
    if not payload.message:
        return event

    event["logentry"]["formatted"] = payload.message  # ty: ignore[invalid-assignment]
    if payload.extra:
        event["contexts"]["structlog"] = payload.extra
    return event


def wrap_before_send_callbacks(
    *callbacks: typing.Optional["sentry_types.EventProcessor"],
) -> "sentry_types.EventProcessor":
    def run_before_send(
        event: "sentry_types.Event", hint: "sentry_types.Hint"
    ) -> typing.Optional["sentry_types.Event"]:
        for callback in callbacks:
            if callback is None:
                continue

            temp_event = callback(event, hint)
            if temp_event is None:
                return None

            event = temp_event
        return event

    return run_before_send


@dataclasses.dataclass(kw_only=True, slots=True)
class SentryInstrument(BaseInstrument[SentryConfig]):
    not_configured_reason = "sentry_dsn is empty"
    missing_dependency_message = "sentry_sdk is not installed"

    @classmethod
    def is_configured(cls, bootstrap_config: "SentryConfig") -> bool:
        return bool(bootstrap_config.sentry_dsn)

    @staticmethod
    def dependencies_installed() -> bool:
        return import_checker.is_sentry_installed

    def bootstrap(self) -> None:
        config = self.bootstrap_config
        sentry_sdk.init(
            dsn=config.sentry_dsn,
            sample_rate=config.sentry_sample_rate,
            traces_sample_rate=config.sentry_traces_sample_rate,
            environment=config.service_environment,
            max_breadcrumbs=config.sentry_max_breadcrumbs,
            max_value_length=config.sentry_max_value_length,
            attach_stacktrace=config.sentry_attach_stacktrace,
            integrations=config.sentry_integrations,
            default_integrations=config.sentry_default_integrations,
            before_send=wrap_before_send_callbacks(enrich_sentry_event_from_structlog_log, config.sentry_before_send),
            **config.sentry_additional_params,
        )
        tags: dict[str, str] = config.sentry_tags or {}
        sentry_sdk.set_tags(tags)

    def teardown(self) -> None:
        """Flush pending events and reset the SDK to a no-op state.

        Calling ``sentry_sdk.init()`` with no DSN disables further event capture. This
        cleans up after a bootstrap so the same process can be torn down and re-tested
        without leaking the previous DSN/transport into subsequent code.
        """
        try:
            sentry_sdk.flush(timeout=2)
        finally:
            sentry_sdk.init()
