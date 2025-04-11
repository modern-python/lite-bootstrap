import dataclasses
import typing

from lite_bootstrap import import_checker
from lite_bootstrap.instruments.base import BaseConfig, BaseInstrument


if typing.TYPE_CHECKING:
    from sentry_sdk.integrations import Integration


if import_checker.is_sentry_installed:
    import sentry_sdk


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


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class SentryInstrument(BaseInstrument):
    bootstrap_config: SentryConfig
    not_ready_message = "sentry_dsn is empty or sentry_sdk is not installed"

    def is_ready(self) -> bool:
        return bool(self.bootstrap_config.sentry_dsn) and import_checker.is_sentry_installed

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
            **self.bootstrap_config.sentry_additional_params,
        )
        tags: dict[str, str] = self.bootstrap_config.sentry_tags or {}
        sentry_sdk.set_tags(tags)
