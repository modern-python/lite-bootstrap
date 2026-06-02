import dataclasses

from lite_bootstrap.instruments.base import BaseConfig, BaseInstrument


@dataclasses.dataclass(kw_only=True, frozen=True)
class CorsConfig(BaseConfig):
    cors_allowed_origins: list[str] = dataclasses.field(default_factory=list)
    cors_allowed_methods: list[str] = dataclasses.field(default_factory=list)
    cors_allowed_headers: list[str] = dataclasses.field(default_factory=list)
    cors_exposed_headers: list[str] = dataclasses.field(default_factory=list)
    cors_allowed_credentials: bool = False
    cors_allowed_origin_regex: str | None = None
    cors_max_age: int = 600


@dataclasses.dataclass(kw_only=True, slots=True)
class CorsInstrument(BaseInstrument[CorsConfig]):
    not_ready_message = "cors_allowed_origins or cors_allowed_origin_regex must be provided"

    @classmethod
    def is_configured(cls, bootstrap_config: "CorsConfig") -> bool:
        return bool(bootstrap_config.cors_allowed_origins) or bool(bootstrap_config.cors_allowed_origin_regex)
