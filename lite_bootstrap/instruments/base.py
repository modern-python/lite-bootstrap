import abc

from lite_bootstrap.service_config import ServiceConfig
from lite_bootstrap.types import ApplicationT


class BaseInstrument(abc.ABC):
    def bootstrap(self, service_config: ServiceConfig, application: ApplicationT | None = None) -> None: ...  # noqa: B027

    def teardown(self, application: ApplicationT | None = None) -> None: ...  # noqa: B027

    @abc.abstractmethod
    def is_ready(self) -> bool: ...
