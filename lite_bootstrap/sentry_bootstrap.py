import dataclasses
import typing

import sentry_sdk


@dataclasses.dataclass(kw_only=True, slots=True)
class SentryBootstrap:
    sentry_dsn: str
    environment: str | None = None
    release: str | None = None
    max_breadcrumbs: int = 15
    attach_stacktrace: bool = True
    default_integrations: bool = True
    sentry_params: dict[str, typing.Any] = dataclasses.field(default_factory=dict)
    tags: dict[str, str] | None = None

    def start_tracing(self) -> None:
        if not self.sentry_dsn:
            return

        sentry_sdk.init(
            dsn=self.sentry_dsn,
            environment=self.environment,
            max_breadcrumbs=self.max_breadcrumbs,
            attach_stacktrace=self.attach_stacktrace,
            default_integrations=self.default_integrations,
            release=self.release,
            **self.sentry_params,
        )
        tags: dict[str, str] = self.tags or {}
        sentry_sdk.set_tags(tags)
