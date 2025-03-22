import abc
import typing

from lite_bootstrap.instruments.base import BaseInstrument
from lite_bootstrap.service_config import ServiceConfig
from lite_bootstrap.types import ApplicationT, BootstrapObjectT


class BaseBootstrapper(abc.ABC, typing.Generic[BootstrapObjectT, ApplicationT]):
    bootstrap_object: BootstrapObjectT
    instruments: typing.Sequence[BaseInstrument]
    service_config: ServiceConfig

    @abc.abstractmethod
    def _prepare_application(self) -> ApplicationT: ...

    def bootstrap(self) -> ApplicationT:
        for one_instrument in self.instruments:
            if one_instrument.is_ready(self.service_config):
                one_instrument.bootstrap(self.service_config, self.bootstrap_object)
        return self._prepare_application()

    def teardown(self) -> None:
        for one_instrument in self.instruments:
            if one_instrument.is_ready(self.service_config):
                one_instrument.teardown(self.bootstrap_object)
