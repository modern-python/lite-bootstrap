import dataclasses
import typing

from lite_bootstrap.helpers import is_valid_path
from lite_bootstrap.instruments.base import BaseConfig, BaseInstrument


@dataclasses.dataclass(kw_only=True, frozen=True)
class SwaggerConfig(BaseConfig):
    service_static_path: str = "/static"
    swagger_path: str = "/docs"
    swagger_offline_docs: bool = False
    swagger_extra_params: dict[str, typing.Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class SwaggerInstrument(BaseInstrument):
    bootstrap_config: SwaggerConfig
    not_ready_message = "swagger_path is empty or not valid"

    def is_ready(self) -> bool:
        return bool(self.bootstrap_config.swagger_path) and is_valid_path(self.bootstrap_config.swagger_path)
