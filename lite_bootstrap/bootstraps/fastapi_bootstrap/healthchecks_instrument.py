import dataclasses
import typing

import fastapi

from lite_bootstrap.instruments.healthchecks_instrument import HealthChecksInstrument, HealthCheckTypedDict
from lite_bootstrap.service_config import ServiceConfig


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class FastAPIHealthChecksInstrument(HealthChecksInstrument):
    enabled: bool = True
    path: str = "/health/"
    include_in_schema: bool = False

    def build_fastapi_health_check_router(self, service_config: ServiceConfig) -> fastapi.APIRouter:
        fastapi_router: typing.Final = fastapi.APIRouter(
            tags=["probes"],
            include_in_schema=self.include_in_schema,
        )

        @fastapi_router.get(self.path)
        async def health_check_handler() -> HealthCheckTypedDict:
            return self.render_health_check_data(service_config)

        return fastapi_router

    def bootstrap(self, service_config: ServiceConfig, application: fastapi.FastAPI | None = None) -> None:
        if application:
            application.include_router(self.build_fastapi_health_check_router(service_config))
