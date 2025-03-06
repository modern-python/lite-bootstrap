import dataclasses
import typing

import fastapi

from lite_bootstrap.bootstraps.base import BaseBootstrap
from lite_bootstrap.bootstraps.fastapi_bootstrap.opentelemetry_instrument import FastAPIOpenTelemetryInstrument
from lite_bootstrap.bootstraps.fastapi_bootstrap.sentry_instrument import FastAPISentryInstrument


__all__ = [
    "FastAPIBootstrap",
    "FastAPIOpenTelemetryInstrument",
    "FastAPISentryInstrument",
]


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class FastAPIBootstrap(BaseBootstrap):
    app: fastapi.FastAPI
    instruments: typing.Sequence[FastAPIOpenTelemetryInstrument | FastAPISentryInstrument]

    def __post_init__(self) -> None:
        for one_instrument in self.instruments:
            one_instrument.app = self.app
