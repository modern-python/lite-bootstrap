import asyncio
import dataclasses
import logging
import typing
from collections.abc import Awaitable, Callable, Mapping

import typing_extensions

from lite_bootstrap.instruments.base import BaseConfig, BaseInstrument


logger = logging.getLogger(__name__)

HealthProbe = Callable[[], Awaitable[bool]]


class HealthCheckTypedDict(typing_extensions.TypedDict, total=False):
    service_version: str | None
    service_name: str | None
    health_status: bool


@dataclasses.dataclass(kw_only=True, frozen=True)
class HealthChecksConfig(BaseConfig):
    health_checks_enabled: bool = True
    health_checks_path: str = "/health/"
    health_checks_include_in_schema: bool = False
    health_checks_probes: Mapping[str, HealthProbe] = dataclasses.field(default_factory=dict)

    @property
    def health_check_data(self) -> HealthCheckTypedDict:
        return {
            "service_version": self.service_version,
            "service_name": self.service_name,
            "health_status": True,
        }


HealthChecksConfigT = typing.TypeVar("HealthChecksConfigT", bound=HealthChecksConfig)


@dataclasses.dataclass(kw_only=True, slots=True)
class HealthChecksInstrument(BaseInstrument[HealthChecksConfigT]):
    not_configured_reason = "health_checks_enabled is False"

    @classmethod
    def is_configured(cls, bootstrap_config: "HealthChecksConfig") -> bool:
        return bootstrap_config.health_checks_enabled

    def render_health_check_data(self, *, health_status: bool = True) -> HealthCheckTypedDict:
        health_check_data = self.bootstrap_config.health_check_data
        health_check_data["health_status"] = health_status
        return health_check_data

    async def define_health_status(self) -> bool:
        results = await asyncio.gather(
            self._define_framework_health_status(),
            *(self._run_probe(name, probe) for name, probe in self.bootstrap_config.health_checks_probes.items()),
        )
        return all(results)

    async def _define_framework_health_status(self) -> bool:
        return True

    @staticmethod
    async def _run_probe(name: str, probe: HealthProbe) -> bool:
        try:
            passed = await probe()
        except Exception:
            logger.warning("Health probe %s raised", name, exc_info=True)
            return False
        if not passed:
            logger.warning("Health probe %s failed", name)
        return bool(passed)
