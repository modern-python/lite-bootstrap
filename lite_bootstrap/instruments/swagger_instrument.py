import dataclasses

from lite_bootstrap.instruments.base import BaseConfig, BaseInstrument


@dataclasses.dataclass(kw_only=True, frozen=True)
class SwaggerConfig(BaseConfig):
    swagger_static_path: str = "/static"
    swagger_path: str = "/docs"
    swagger_offline_docs: bool = False


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class SwaggerInstrument(BaseInstrument):
    bootstrap_config: SwaggerConfig
