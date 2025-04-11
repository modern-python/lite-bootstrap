import abc
import typing
import warnings

from lite_bootstrap.instruments.base import BaseConfig, BaseInstrument
from lite_bootstrap.types import ApplicationT


InstrumentT = typing.TypeVar("InstrumentT", bound=BaseInstrument)


class BaseBootstrapper(abc.ABC, typing.Generic[ApplicationT]):
    instruments_types: typing.ClassVar[list[type[BaseInstrument]]]
    instruments: list[BaseInstrument]
    bootstrap_config: BaseConfig

    def __init__(self, bootstrap_config: BaseConfig) -> None:
        if not self.is_ready():
            raise RuntimeError(self.not_ready_message)

        self.bootstrap_config = bootstrap_config
        self.instruments = []
        for instrument_type in self.instruments_types:
            instrument = instrument_type(bootstrap_config=bootstrap_config)
            if instrument.is_ready():
                self.instruments.append(instrument)
            else:
                warnings.warn(instrument.not_ready_message, stacklevel=2)

    @property
    @abc.abstractmethod
    def not_ready_message(self) -> str: ...

    @abc.abstractmethod
    def _prepare_application(self) -> ApplicationT: ...

    @abc.abstractmethod
    def is_ready(self) -> bool: ...

    def bootstrap(self) -> ApplicationT:
        for one_instrument in self.instruments:
            one_instrument.bootstrap()
        return self._prepare_application()

    def teardown(self) -> None:
        for one_instrument in self.instruments:
            one_instrument.teardown()
