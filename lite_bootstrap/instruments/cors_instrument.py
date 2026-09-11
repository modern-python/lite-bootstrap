import dataclasses
import typing

from lite_bootstrap.exceptions import ConfigurationError
from lite_bootstrap.instruments.base import BaseConfig, BaseInstrument


_PERMISSIVE_ORIGIN_REGEX: typing.Final[frozenset[str]] = frozenset({".*", r".+"})


@dataclasses.dataclass(kw_only=True, frozen=True)
class CorsConfig(BaseConfig):
    cors_allowed_origins: list[str] = dataclasses.field(default_factory=list)
    cors_allowed_methods: list[str] = dataclasses.field(default_factory=list)
    cors_allowed_headers: list[str] = dataclasses.field(default_factory=list)
    cors_exposed_headers: list[str] = dataclasses.field(default_factory=list)
    cors_allowed_credentials: bool = False
    cors_allowed_origin_regex: str | None = None
    cors_max_age: int = 600

    def __post_init__(self) -> None:
        if self.cors_allowed_credentials:
            wildcard_in_origins = "*" in self.cors_allowed_origins
            permissive_regex = self.cors_allowed_origin_regex in _PERMISSIVE_ORIGIN_REGEX
            if wildcard_in_origins or permissive_regex:
                msg = (
                    "Unsafe CORS configuration: cors_allowed_credentials=True combined with a "
                    "wildcard origin is rejected by browsers and is a security misconfiguration. "
                    "Use an explicit list of allowed origins (or a narrow regex)."
                )
                raise ConfigurationError(msg)
        super().__post_init__()


@dataclasses.dataclass(kw_only=True, slots=True)
class CorsInstrument(BaseInstrument[CorsConfig]):
    not_configured_reason = "cors_allowed_origins or cors_allowed_origin_regex must be provided"

    @classmethod
    def is_configured(cls, bootstrap_config: "CorsConfig") -> bool:
        return bool(bootstrap_config.cors_allowed_origins) or bool(bootstrap_config.cors_allowed_origin_regex)

    @property
    def cors_kwargs(self) -> dict[str, typing.Any]:
        """The CORS settings under the keyword names Starlette's CORSMiddleware and Litestar's CORSConfig share."""
        config = self.bootstrap_config
        return {
            "allow_origins": config.cors_allowed_origins,
            "allow_methods": config.cors_allowed_methods,
            "allow_headers": config.cors_allowed_headers,
            "allow_credentials": config.cors_allowed_credentials,
            "allow_origin_regex": config.cors_allowed_origin_regex,
            "expose_headers": config.cors_exposed_headers,
            "max_age": config.cors_max_age,
        }
