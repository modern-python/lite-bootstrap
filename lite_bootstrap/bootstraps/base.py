import abc
import typing

from lite_bootstrap.instruments.base import BaseInstrument
from lite_bootstrap.service_config import ServiceConfig
from lite_bootstrap.types import ApplicationT


class BaseBootstrap(abc.ABC, typing.Generic[ApplicationT]):
    application: ApplicationT
    instruments: typing.Sequence[BaseInstrument]
    service_config: ServiceConfig

    def bootstrap(self) -> None:
        for one_instrument in self.instruments:
            if one_instrument.is_ready():
                one_instrument.bootstrap(self.service_config, self.application)

    def teardown(self) -> None:
        for one_instrument in self.instruments:
            if one_instrument.is_ready():
                one_instrument.teardown(self.application)
