import dataclasses
import typing

from lite_bootstrap.instruments.base import BaseConfig, BaseInstrument


@dataclasses.dataclass(kw_only=True, frozen=True)
class SwaggerConfig(BaseConfig):
    swagger_static_path: str = "/static"
    swagger_offline_docs: bool = False
    swagger_extra_params: dict[str, typing.Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class SwaggerInstrument(BaseInstrument):
    bootstrap_config: SwaggerConfig
