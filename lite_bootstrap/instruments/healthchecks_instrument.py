import dataclasses

import typing_extensions

from lite_bootstrap.instruments.base import BaseInstrument
from lite_bootstrap.service_config import ServiceConfig


class HealthCheckTypedDict(typing_extensions.TypedDict, total=False):
    service_version: str | None
    service_name: str | None
    health_status: bool


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class HealthChecksInstrument(BaseInstrument):
    enabled: bool = True
    path: str = "/health/"
    include_in_schema: bool = False

    def is_ready(self) -> bool:
        return self.enabled

    @staticmethod
    def render_health_check_data(service_config: ServiceConfig) -> HealthCheckTypedDict:
        return {
            "service_version": service_config.service_version,
            "service_name": service_config.service_name,
            "health_status": True,
        }
