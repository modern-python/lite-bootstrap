import abc
import logging
import typing
import warnings

from lite_bootstrap.exceptions import (
    BootstrapperNotReadyError,
    InstrumentDependencyMissingWarning,
    TeardownError,
)
from lite_bootstrap.instruments.base import BaseConfig, BaseInstrument
from lite_bootstrap.types import ApplicationT


logger = logging.getLogger(__name__)


InstrumentT = typing.TypeVar("InstrumentT", bound=BaseInstrument)


class BaseBootstrapper(abc.ABC, typing.Generic[ApplicationT]):
    instruments_types: typing.ClassVar[list[type[BaseInstrument]]]
    instruments: list[BaseInstrument]
    skipped_instruments: list[tuple[type[BaseInstrument], str]]
    bootstrap_config: BaseConfig

    def build_summary(self) -> str:
        """Return a multi-line human-readable summary of configured + skipped instruments.

        Useful for INFO-level diagnostic logging (called once by ``__init__``) and for
        post-construction debugging (e.g. from a REPL or a health endpoint).
        """
        lines = [f"{type(self).__name__}:", "  configured:"]
        if self.instruments:
            lines.extend(f"    - {type(i).__name__}" for i in self.instruments)
        else:
            lines.append("    (none)")
        lines.append("  skipped:")
        if self.skipped_instruments:
            lines.extend(f"    - {cls.__name__}: {reason}" for cls, reason in self.skipped_instruments)
        else:
            lines.append("    (none)")
        return "\n".join(lines)

    def __init__(self, bootstrap_config: BaseConfig) -> None:
        self.is_bootstrapped = False
        if not self.is_ready():
            msg = f"{type(self).__name__} is not ready: {self.not_ready_message}"
            raise BootstrapperNotReadyError(msg)

        self.bootstrap_config = bootstrap_config
        self.instruments = []
        self.skipped_instruments = []
        for instrument_type in self.instruments_types:
            # Config-level skip first: silent (no warning). Runs before instantiation so a
            # missing-optional-dep doesn't fail in a dataclass default_factory before we
            # can decide the user opted out.
            if not instrument_type.is_configured(self.bootstrap_config):
                self.skipped_instruments.append((instrument_type, instrument_type.not_ready_message))
                continue
            # Dep-missing for a CONFIGURED instrument is a genuine deployment surprise.
            if not instrument_type.check_dependencies():
                warnings.warn(
                    instrument_type.missing_dependency_message,
                    category=InstrumentDependencyMissingWarning,
                    stacklevel=3,
                )
                continue
            self.instruments.append(instrument_type(bootstrap_config=self.bootstrap_config))

        if logger.isEnabledFor(logging.INFO):
            logger.info(self.build_summary())

    @property
    @abc.abstractmethod
    def not_ready_message(self) -> str: ...

    @abc.abstractmethod
    def _prepare_application(self) -> ApplicationT: ...

    @abc.abstractmethod
    def is_ready(self) -> bool: ...

    def bootstrap(self) -> ApplicationT:
        if self.is_bootstrapped:
            return self._prepare_application()
        self.is_bootstrapped = True
        for one_instrument in self.instruments:
            one_instrument.bootstrap()
        return self._prepare_application()

    def teardown(self) -> None:
        if not self.is_bootstrapped:
            return
        self.is_bootstrapped = False
        errors: list[tuple[str, BaseException]] = []
        for one_instrument in reversed(self.instruments):
            try:
                one_instrument.teardown()
            except Exception as e:  # noqa: BLE001, PERF203
                name = type(one_instrument).__name__
                logger.warning("Error tearing down %s: %s", name, e)
                errors.append((name, e))
        if errors:
            raise TeardownError(errors) from errors[0][1]
