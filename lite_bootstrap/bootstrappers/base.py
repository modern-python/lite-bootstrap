import abc
import logging
import typing
import warnings

from lite_bootstrap.exceptions import BootstrapperNotReadyError, TeardownError
from lite_bootstrap.instruments.base import BaseConfig, BaseInstrument
from lite_bootstrap.types import ApplicationT


try:
    import structlog

    logger = structlog.getLogger(__name__)
except ImportError:
    logger = logging.getLogger(__name__)


InstrumentT = typing.TypeVar("InstrumentT", bound=BaseInstrument)


class BaseBootstrapper(abc.ABC, typing.Generic[ApplicationT]):
    instruments_types: typing.ClassVar[list[type[BaseInstrument]]]
    instruments: list[BaseInstrument]
    bootstrap_config: BaseConfig

    def __init__(self, bootstrap_config: BaseConfig) -> None:
        self.is_bootstrapped = False
        if not self.is_ready():
            msg = f"{type(self).__name__} is not ready: {self.not_ready_message}"
            raise BootstrapperNotReadyError(msg)

        self.bootstrap_config = bootstrap_config
        self.instruments = []
        for instrument_type in self.instruments_types:
            instrument = instrument_type(bootstrap_config=bootstrap_config)
            if not instrument.check_dependencies():
                warnings.warn(instrument.missing_dependency_message, stacklevel=2)
                continue

            if not instrument.is_ready():
                logger.info(f"{instrument_type.__name__} is not ready: {instrument.not_ready_message}")
                continue

            self.instruments.append(instrument)

    @property
    @abc.abstractmethod
    def not_ready_message(self) -> str: ...

    @abc.abstractmethod
    def _prepare_application(self) -> ApplicationT: ...

    @abc.abstractmethod
    def is_ready(self) -> bool: ...

    def bootstrap(self) -> ApplicationT:
        self.is_bootstrapped = True
        for one_instrument in self.instruments:
            one_instrument.bootstrap()
        return self._prepare_application()

    def teardown(self) -> None:
        self.is_bootstrapped = False
        errors: list[tuple[str, BaseException]] = []
        for one_instrument in reversed(self.instruments):
            try:
                one_instrument.teardown()
            except Exception as e:  # noqa: BLE001, PERF203
                name = type(one_instrument).__name__
                logger.warning(f"Error tearing down {name}: {e}")
                errors.append((name, e))
        if errors:
            raise TeardownError(errors) from errors[0][1]
