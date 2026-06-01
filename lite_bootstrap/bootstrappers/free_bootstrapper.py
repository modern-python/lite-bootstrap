import dataclasses
import typing

from lite_bootstrap.bootstrappers.base import BaseBootstrapper
from lite_bootstrap.instruments.logging_instrument import LoggingConfig, LoggingInstrument
from lite_bootstrap.instruments.opentelemetry_instrument import OpenTelemetryConfig, OpenTelemetryInstrument
from lite_bootstrap.instruments.pyroscope_instrument import PyroscopeConfig, PyroscopeInstrument
from lite_bootstrap.instruments.sentry_instrument import SentryConfig, SentryInstrument


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class FreeConfig(LoggingConfig, OpenTelemetryConfig, PyroscopeConfig, SentryConfig): ...


class FreeBootstrapper(BaseBootstrapper[None]):
    __slots__ = "bootstrap_config", "instruments"

    instruments_types: typing.ClassVar = [
        LoggingInstrument,
        SentryInstrument,
        OpenTelemetryInstrument,
        PyroscopeInstrument,
    ]
    bootstrap_config: FreeConfig
    not_ready_message = ""

    def is_ready(self) -> bool:
        return True

    def __init__(self, bootstrap_config: FreeConfig) -> None:
        super().__init__(bootstrap_config)

    def _prepare_application(self) -> None:
        return None


# Backward-compatible alias preserved for users importing the old name.
FreeBootstrapperConfig = FreeConfig
