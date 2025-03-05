import dataclasses
import typing

import pydantic
import sentry_sdk
from sentry_sdk.integrations import Integration

from lite_bootstrap.instruments.base import BaseInstrument


@dataclasses.dataclass(kw_only=True, slots=True)
class SentryInstrument(BaseInstrument):
    dsn: str | None = None
    sample_rate: float = pydantic.Field(default=1.0, le=1.0, ge=0.0)
    traces_sample_rate: float | None = None
    environment: str | None = None
    max_breadcrumbs: int = 15
    max_value_length: int = 16384
    attach_stacktrace: bool = True
    integrations: list[Integration] = dataclasses.field(default_factory=list)
    additional_params: dict[str, typing.Any] = dataclasses.field(default_factory=dict)
    tags: dict[str, str] | None = None

    def is_ready(self) -> bool:
        return bool(self.dsn)

    def bootstrap(self) -> None:
        sentry_sdk.init(
            dsn=self.dsn,
            sample_rate=self.sample_rate,
            traces_sample_rate=self.traces_sample_rate,
            environment=self.environment,
            max_breadcrumbs=self.max_breadcrumbs,
            max_value_length=self.max_value_length,
            attach_stacktrace=self.attach_stacktrace,
            integrations=self.integrations,
            **self.additional_params,
        )
        tags: dict[str, str] = self.tags or {}
        sentry_sdk.set_tags(tags)

    def teardown(self) -> None: ...
