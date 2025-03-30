import abc
import dataclasses


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class BaseConfig:
    service_name: str = "micro-service"
    service_version: str = "1.0.0"
    service_environment: str | None = None
    service_debug: bool = True


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class BaseInstrument(abc.ABC):
    bootstrap_config: BaseConfig

    def bootstrap(self) -> None: ...  # noqa: B027

    def teardown(self) -> None: ...  # noqa: B027

    @abc.abstractmethod
    def is_ready(self) -> bool: ...
