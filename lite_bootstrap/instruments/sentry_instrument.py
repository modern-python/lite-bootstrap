import dataclasses
import logging
import typing
from collections.abc import Mapping

from lite_bootstrap import import_checker
from lite_bootstrap.helpers.warn import deprecated_module_getattr, warn_at_caller
from lite_bootstrap.instruments.base import BaseConfig, BaseInstrument
from lite_bootstrap.instruments.logging_factory import STRUCTLOG_META_KEYS, StructuredLogPayload


if typing.TYPE_CHECKING:
    from sentry_sdk import _types as sentry_types
    from sentry_sdk.integrations import Integration


if import_checker.is_sentry_installed:
    import sentry_sdk
    from sentry_sdk.integrations.logging import LoggingIntegration
    from sentry_sdk.utils import event_from_exception

    IS_SENTRY_SDK_2: typing.Final = sentry_sdk.VERSION.startswith("2.")


_PII_KEY_DENYLIST: typing.Final = {"mode": "denylist", "terms": ["forwarded", "-ip", "remote-", "via", "-user"]}
DEFAULT_DATA_COLLECTION: typing.Final[dict[str, typing.Any]] = {
    "user_info": False,
    "http_bodies": [],
    "graphql": {"document": False, "variables": False},
    "gen_ai": {"inputs": False, "outputs": False},
    "mcp": {"inputs": False, "outputs": False},
    "database_query_data": False,
    "queues": False,
    "http_headers": {"request": _PII_KEY_DENYLIST},
    "cookies": _PII_KEY_DENYLIST,
    "url_query_params": _PII_KEY_DENYLIST,
    "stack_frame_variables": {"mode": "denylist"},
}


_TRACING_OPTIONS: typing.Final = ("traces_sample_rate", "traces_sampler", "enable_tracing")


@dataclasses.dataclass(kw_only=True, frozen=True)
class SentryConfig(BaseConfig):
    sentry_dsn: str | None = None
    sentry_traces_sample_rate: float | None = None
    sentry_sample_rate: float = 1.0
    sentry_max_breadcrumbs: int = 15
    sentry_max_value_length: int = 16384
    sentry_attach_stacktrace: bool = True
    sentry_auto_session_tracking: bool = False
    sentry_integrations: list["Integration"] = dataclasses.field(default_factory=list)
    sentry_logging_breadcrumb_level: int | None = logging.WARNING
    sentry_additional_params: dict[str, typing.Any] = dataclasses.field(default_factory=dict)
    sentry_tags: dict[str, str] | None = None
    sentry_default_integrations: bool = True
    sentry_before_send: "sentry_types.EventProcessor | None" = None

    def is_sentry_tracing_requested(self) -> bool:
        return any(
            option is not None
            for option in (
                self.sentry_traces_sample_rate,
                *(self.sentry_additional_params.get(name) for name in _TRACING_OPTIONS),
            )
        )


@dataclasses.dataclass(kw_only=True, frozen=True)
class SentryLeanCaptureConfig(SentryConfig):
    """A framework whose request errors lite-bootstrap can report without sentry-sdk's framework integration."""

    sentry_lean_error_capture: bool | None = None
    _sentry_lean_replaced_integrations: typing.ClassVar[Mapping[str, str]] = {}

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.sentry_lean_error_capture:
            return
        if self.is_sentry_tracing_requested():
            warn_at_caller(
                "sentry_lean_error_capture starts no transaction per request, so Sentry tracing "
                "only samples transactions your code starts itself."
            )
        if supplied := self._supplied_sentry_lean_replaced_integrations():
            warn_at_caller(
                f"sentry_lean_error_capture disables Sentry's {' and '.join(supplied)}, so the one in "
                "sentry_integrations is dropped."
            )

    def _supplied_sentry_lean_replaced_integrations(self) -> list[str]:
        return [
            self._sentry_lean_replaced_integrations[integration.identifier]
            for integration in self.sentry_integrations
            if integration.identifier in self._sentry_lean_replaced_integrations
        ]

    def is_sentry_lean_error_capture_on(self) -> bool:
        if self.sentry_lean_error_capture is not None:
            return self.sentry_lean_error_capture
        return not self.is_sentry_tracing_requested() and not self._supplied_sentry_lean_replaced_integrations()


SENTRY_FAILED_REQUEST_STATUS_CODES: typing.Final = range(500, 600)
_SENTRY_TRACE_HEADERS: typing.Final = frozenset({b"sentry-trace", b"baggage"})


def read_sentry_trace_headers(headers: typing.Iterable[tuple[bytes, bytes]]) -> dict[str, str]:
    return {name.decode("latin-1"): value.decode("latin-1") for name, value in headers if name in _SENTRY_TRACE_HEADERS}


def capture_request_exception(
    exception: BaseException,
    *,
    mechanism_type: str,
    handled: bool,
    enrich: typing.Callable[["sentry_types.Event"], "sentry_types.Event"] = lambda event: event,
) -> None:
    client_options: typing.Final = {"client_options": sentry_sdk.get_client().options} if IS_SENTRY_SDK_2 else {}
    event, hint = event_from_exception(
        exception, mechanism={"type": mechanism_type, "handled": handled}, **client_options
    )
    sentry_sdk.capture_event(enrich(event), hint=hint)


def disable_sentry_integrations(
    init_params: dict[str, typing.Any], integrations: typing.Sequence[type["Integration"]]
) -> None:
    init_params["disabled_integrations"] = [*init_params.get("disabled_integrations", []), *integrations]


def warn_about_sentry_integrations_installed_earlier(integrations: typing.Sequence[type["Integration"]]) -> None:
    client: typing.Final = sentry_sdk.get_client()
    if installed := [integration.__name__ for integration in integrations if client.get_integration(integration)]:
        warn_at_caller(
            f"Sentry's {' and '.join(installed)} was installed by an earlier sentry_sdk.init in this process and "
            "sentry_lean_error_capture cannot disable it, so request errors may be reported twice."
        )


def enrich_sentry_event_from_structlog_log(
    event: "sentry_types.Event", _: "sentry_types.Hint"
) -> typing.Optional["sentry_types.Event"]:
    logentry = event.get("logentry") or {}
    if not (
        (formatted_message := logentry.get("formatted"))
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


SentryConfigT = typing.TypeVar("SentryConfigT", bound=SentryConfig)


@dataclasses.dataclass(kw_only=True, slots=True)
class SentryInstrument(BaseInstrument[SentryConfigT]):
    not_configured_reason = "sentry_dsn is empty"
    missing_dependency_message = "sentry_sdk is not installed"

    @classmethod
    def is_configured(cls, bootstrap_config: "SentryConfig") -> bool:
        return bool(bootstrap_config.sentry_dsn)

    @staticmethod
    def dependencies_installed() -> bool:
        return import_checker.is_sentry_installed

    def _warn_breadcrumb_level_ignored(self, reason: str) -> None:
        if self.bootstrap_config.sentry_logging_breadcrumb_level != logging.WARNING:
            warn_at_caller(f"sentry_logging_breadcrumb_level is ignored, {reason}")

    def _build_integrations(self) -> list["Integration"]:
        config = self.bootstrap_config
        if any(integration.identifier == LoggingIntegration.identifier for integration in config.sentry_integrations):
            self._warn_breadcrumb_level_ignored("sentry_integrations already supplies a LoggingIntegration")
            return config.sentry_integrations
        if not config.sentry_default_integrations:
            self._warn_breadcrumb_level_ignored("sentry_default_integrations is False")
            return config.sentry_integrations
        breadcrumb_level = config.sentry_logging_breadcrumb_level
        logging_integration_kwargs: dict[str, typing.Any] = (
            {"level": breadcrumb_level, "sentry_logs_level": None}
            if IS_SENTRY_SDK_2
            else {"breadcrumb_level": breadcrumb_level, "event_level": logging.ERROR, "level": None}
        )
        return [*config.sentry_integrations, LoggingIntegration(**logging_integration_kwargs)]

    def _build_init_params(self) -> dict[str, typing.Any]:
        config = self.bootstrap_config
        init_params: dict[str, typing.Any] = {
            "dsn": config.sentry_dsn,
            "sample_rate": config.sentry_sample_rate,
            "traces_sample_rate": config.sentry_traces_sample_rate,
            "environment": config.service_environment,
            "max_breadcrumbs": config.sentry_max_breadcrumbs,
            "max_value_length": config.sentry_max_value_length,
            "attach_stacktrace": config.sentry_attach_stacktrace,
            "auto_session_tracking": config.sentry_auto_session_tracking,
            "integrations": self._build_integrations(),
            "default_integrations": config.sentry_default_integrations,
            "data_collection": DEFAULT_DATA_COLLECTION,
            "before_send": wrap_before_send_callbacks(
                enrich_sentry_event_from_structlog_log, config.sentry_before_send
            ),
        }
        init_params.update(config.sentry_additional_params)
        return init_params

    def bootstrap(self) -> None:
        sentry_sdk.init(**self._build_init_params())
        tags: dict[str, str] = self.bootstrap_config.sentry_tags or {}
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


if typing.TYPE_CHECKING:
    IGNORED_STRUCTLOG_ATTRIBUTES: typing.Final = STRUCTLOG_META_KEYS

__getattr__ = deprecated_module_getattr(
    __name__,
    {"IGNORED_STRUCTLOG_ATTRIBUTES": (STRUCTLOG_META_KEYS, "STRUCTLOG_META_KEYS")},
)
