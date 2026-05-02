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
