import dataclasses
import typing

from lite_bootstrap.bootstrappers.base import BaseBootstrapper
from lite_bootstrap.instruments.logging_instrument import LoggingConfig, LoggingInstrument
from lite_bootstrap.instruments.opentelemetry_instrument import OpentelemetryConfig, OpenTelemetryInstrument
from lite_bootstrap.instruments.sentry_instrument import SentryConfig, SentryInstrument


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class FreeBootstrapperConfig(LoggingConfig, OpentelemetryConfig, SentryConfig): ...


class FreeBootstrapper(BaseBootstrapper[None]):
    instruments_types: typing.ClassVar = [
        OpenTelemetryInstrument,
        SentryInstrument,
        LoggingInstrument,
    ]
    bootstrap_config: FreeBootstrapperConfig
    __slots__ = "bootstrap_config", "instruments"

    def __init__(self, bootstrap_config: FreeBootstrapperConfig) -> None:
        super().__init__(bootstrap_config)

    def _prepare_application(self) -> None:
        return None
