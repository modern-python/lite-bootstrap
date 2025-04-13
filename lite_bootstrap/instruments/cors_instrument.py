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


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class CorsInstrument(BaseInstrument):
    bootstrap_config: CorsConfig
    not_ready_message = "cors_allowed_origins or cors_allowed_origin_regex must be provided"

    def is_ready(self) -> bool:
        return bool(self.bootstrap_config.cors_allowed_origins) or bool(
            self.bootstrap_config.cors_allowed_origin_regex,
        )
