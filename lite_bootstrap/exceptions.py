import contextlib
import logging
import typing


class LiteBootstrapError(RuntimeError):
    """Base class for all lite-bootstrap errors."""


class BootstrapperNotReadyError(LiteBootstrapError):
    """Raised when a bootstrapper's is_ready() check fails during construction."""


class ConfigurationError(LiteBootstrapError):
    """Raised when a config is invalid or a required optional dependency is missing.

    Also raised when a bootstrapper is constructed on an application another bootstrapper
    already owns.
    """


class TeardownError(LiteBootstrapError):
    """Raised when one or more instruments fail during teardown."""

    def __init__(self, errors: list[tuple[str, BaseException]]) -> None:
        self.errors = errors
        details = "; ".join(f"{name}: {err}" for name, err in errors)
        super().__init__(f"{len(errors)} instrument(s) failed during teardown: {details}")


class InstrumentSkippedWarning(UserWarning):
    """Base class for warnings emitted when an instrument is skipped during bootstrap."""


class InstrumentDependencyMissingWarning(InstrumentSkippedWarning):
    """Emitted when an instrument is skipped because its optional dependency is not installed."""


class TeardownErrorCollector:
    """Accumulates teardown failures so the steps after a failing one still run."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.errors: list[tuple[str, BaseException]] = []
        self._logger = logger

    @contextlib.contextmanager
    def capture(self, name: str) -> typing.Iterator[None]:
        """Record an ``Exception`` raised by one teardown step under ``name`` and continue."""
        try:
            yield
        except Exception as e:  # noqa: BLE001
            if self._logger is not None:
                self._logger.warning("Error tearing down %s: %s", name, e)
            self.errors.append((name, e))


@contextlib.contextmanager
def collect_teardown_errors(logger: logging.Logger | None = None) -> typing.Iterator[TeardownErrorCollector]:
    """Collect the failures of individual teardown steps and raise them together.

    Raises :class:`TeardownError` on leaving the block if any ``capture()`` recorded
    something, chained from the first failure. A ``BaseException`` escaping the block
    propagates as-is and nothing is raised on top of it.
    """
    collector = TeardownErrorCollector(logger)
    yield collector
    if collector.errors:
        raise TeardownError(collector.errors) from collector.errors[0][1]
