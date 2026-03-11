import contextlib
import sys
import typing
from importlib import reload

import pytest
import sentry_sdk
from opentelemetry.instrumentation.instrumentor import BaseInstrumentor
from sentry_sdk.envelope import Envelope
from structlog.typing import EventDict, WrappedLogger

from lite_bootstrap import import_checker


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
    sys.modules[package_name] = None  # type: ignore[assignment]
    reload(import_checker)
    try:
        yield
    finally:
        sys.modules[package_name] = old_module
        reload(import_checker)
