class LiteBootstrapError(RuntimeError):
    """Base class for all lite-bootstrap errors."""


class BootstrapperNotReadyError(LiteBootstrapError):
    """Raised when a bootstrapper's is_ready() check fails during construction."""


class ConfigurationError(LiteBootstrapError):
    """Raised when a config is invalid or a required optional dependency is missing."""


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


class InstrumentNotReadyWarning(InstrumentSkippedWarning):
    """Emitted when an instrument is skipped because its config indicates it should not run."""
