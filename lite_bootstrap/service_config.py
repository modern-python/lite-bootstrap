import dataclasses


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class ServiceConfig:
    service_name: str = "micro-service"
    service_version: str = "1.0.0"
    service_environment: str | None = None
