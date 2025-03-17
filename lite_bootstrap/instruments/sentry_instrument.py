import contextlib
import dataclasses
import typing

from lite_bootstrap.instruments.base import BaseInstrument
from lite_bootstrap.service_config import ServiceConfig
from lite_bootstrap.types import ApplicationT


with contextlib.suppress(ImportError):
    import sentry_sdk
    from sentry_sdk.integrations import Integration


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class SentryInstrument(BaseInstrument):
    dsn: str | None = None
    sample_rate: float = dataclasses.field(default=1.0)
    traces_sample_rate: float | None = None
    max_breadcrumbs: int = 15
    max_value_length: int = 16384
    attach_stacktrace: bool = True
    integrations: list[Integration] = dataclasses.field(default_factory=list)
    additional_params: dict[str, typing.Any] = dataclasses.field(default_factory=dict)
    tags: dict[str, str] | None = None

    def is_ready(self) -> bool:
        return bool(self.dsn)

    def bootstrap(self, service_config: ServiceConfig, _: ApplicationT | None = None) -> None:
        sentry_sdk.init(
            dsn=self.dsn,
            sample_rate=self.sample_rate,
            traces_sample_rate=self.traces_sample_rate,
            environment=service_config.service_environment,
            max_breadcrumbs=self.max_breadcrumbs,
            max_value_length=self.max_value_length,
            attach_stacktrace=self.attach_stacktrace,
            integrations=self.integrations,
            **self.additional_params,
        )
        tags: dict[str, str] = self.tags or {}
        sentry_sdk.set_tags(tags)

    def teardown(self, application: ApplicationT | None = None) -> None: ...
