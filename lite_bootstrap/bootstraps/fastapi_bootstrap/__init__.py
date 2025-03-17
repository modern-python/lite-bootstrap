import dataclasses
import typing

import fastapi

from lite_bootstrap.bootstraps.base import BaseBootstrap
from lite_bootstrap.bootstraps.fastapi_bootstrap.healthchecks_instrument import FastAPIHealthChecksInstrument
from lite_bootstrap.bootstraps.fastapi_bootstrap.opentelemetry_instrument import FastAPIOpenTelemetryInstrument
from lite_bootstrap.bootstraps.fastapi_bootstrap.sentry_instrument import FastAPISentryInstrument


__all__ = [
    "FastAPIBootstrap",
    "FastAPIHealthChecksInstrument",
    "FastAPIOpenTelemetryInstrument",
    "FastAPISentryInstrument",
]

from lite_bootstrap.service_config import ServiceConfig


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class FastAPIBootstrap(BaseBootstrap[fastapi.FastAPI]):
    application: fastapi.FastAPI
    instruments: typing.Sequence[
        FastAPIOpenTelemetryInstrument | FastAPISentryInstrument | FastAPIHealthChecksInstrument
    ]
    service_config: ServiceConfig
