import abc
import typing

from lite_bootstrap.instruments.base import BaseInstrument


class BaseBootstrap(abc.ABC):
    instruments: typing.Sequence[BaseInstrument]

    def bootstrap(self) -> None:
        for one_instrument in self.instruments:
            if one_instrument.is_ready():
                one_instrument.bootstrap()

    def teardown(self) -> None:
        for one_instrument in self.instruments:
            if one_instrument.is_ready():
                one_instrument.teardown()
