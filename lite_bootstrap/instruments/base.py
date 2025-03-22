import abc

from lite_bootstrap.service_config import ServiceConfig
from lite_bootstrap.types import BootstrapObjectT


class BaseInstrument(abc.ABC):
    def bootstrap(self, service_config: ServiceConfig, bootstrap_object: BootstrapObjectT | None = None) -> None: ...  # noqa: B027

    def teardown(self, bootstrap_object: BootstrapObjectT | None = None) -> None: ...  # noqa: B027

    @abc.abstractmethod
    def is_ready(self, service_config: ServiceConfig) -> bool: ...
