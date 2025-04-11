import dataclasses

import typing_extensions

from lite_bootstrap.instruments.base import BaseConfig, BaseInstrument


class HealthCheckTypedDict(typing_extensions.TypedDict, total=False):
    service_version: str | None
    service_name: str | None
    health_status: bool


@dataclasses.dataclass(kw_only=True, frozen=True)
class HealthChecksConfig(BaseConfig):
    health_checks_enabled: bool = True
    health_checks_path: str = "/health/"
    health_checks_include_in_schema: bool = False


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class HealthChecksInstrument(BaseInstrument):
    bootstrap_config: HealthChecksConfig
    not_ready_message = "health_checks_enabled is False"

    def is_ready(self) -> bool:
        return self.bootstrap_config.health_checks_enabled

    def render_health_check_data(self) -> HealthCheckTypedDict:
        return {
            "service_version": self.bootstrap_config.service_version,
            "service_name": self.bootstrap_config.service_name,
            "health_status": True,
        }
