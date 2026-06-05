import contextlib
import sys
import typing
import warnings
from importlib import reload

import pytest
import sentry_sdk
from opentelemetry.instrumentation.instrumentor import BaseInstrumentor
from sentry_sdk.envelope import Envelope
from structlog.typing import EventDict, WrappedLogger

from lite_bootstrap import import_checker
from lite_bootstrap.exceptions import InstrumentSkippedWarning


def pytest_configure() -> None:
    """Escalate InstrumentSkippedWarning (and subclasses) to errors.

    Done here rather than via filterwarnings in pyproject.toml to avoid pytest
    resolving the warning class before pytest-cov starts coverage, which would
    cause coverage to miss the lite_bootstrap module-level statements.
    """
    warnings.filterwarnings("error", category=InstrumentSkippedWarning)


class CustomInstrumentor(BaseInstrumentor):
    def instrumentation_dependencies(self) -> typing.Collection[str]:
        return []

    def _uninstrument(self, **kwargs: typing.Mapping[str, typing.Any]) -> None:
        pass


class SentryTestTransport(sentry_sdk.Transport):
    def __init__(self, *args: typing.Any, **kwargs: typing.Any) -> None:  # noqa: ANN401
        super().__init__(*args, **kwargs)
        self.mock_envelopes: list[Envelope] = []

    def capture_envelope(self, envelope: Envelope) -> None:
        self.mock_envelopes.append(envelope)


@pytest.fixture
def sentry_mock() -> SentryTestTransport:
    return SentryTestTransport()


class LoggingMock:
    def __init__(self) -> None:
        self.entries: list[EventDict] = []

    def __call__(self, _: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
        self.entries.append(event_dict)
        return event_dict


@pytest.fixture
def logging_mock() -> LoggingMock:
    return LoggingMock()


@contextlib.contextmanager
def emulate_package_missing(package_name: str) -> typing.Iterator[None]:
    old_module = sys.modules[package_name]
    sys.modules[package_name] = None  # ty: ignore[invalid-assignment]
    reload(import_checker)
    try:
        yield
    finally:
        sys.modules[package_name] = old_module
        reload(import_checker)


@contextlib.contextmanager
def emulate_package_missing_with_module_reload(
    package_name: str, module_names: typing.Iterable[str]
) -> typing.Iterator[None]:
    # Reload listed modules under emulate_package_missing so their
    # `if import_checker.is_X_installed: import X` blocks re-evaluate against
    # the patched flag. `importlib.reload` preserves existing module globals,
    # so we wipe non-dunder names first to truly simulate a fresh import where
    # the conditional import never ran.
    module_names = list(module_names)
    snapshots: dict[str, dict[str, typing.Any]] = {}
    for name in module_names:
        if name in sys.modules:
            snapshots[name] = dict(sys.modules[name].__dict__)

    def _wipe_and_reload() -> None:
        for name in module_names:
            if name in sys.modules:
                mod_dict = sys.modules[name].__dict__
                for key in [k for k in mod_dict if not k.startswith("__")]:
                    del mod_dict[key]
                reload(sys.modules[name])

    with emulate_package_missing(package_name):
        _wipe_and_reload()
        try:
            yield
        finally:
            for name, snap in snapshots.items():
                if name in sys.modules:
                    mod_dict = sys.modules[name].__dict__
                    for key in [k for k in mod_dict if not k.startswith("__")]:
                        del mod_dict[key]
                    mod_dict.update({k: v for k, v in snap.items() if not k.startswith("__")})
