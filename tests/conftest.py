import contextlib
import sys
import typing
from importlib import reload

import pytest
import sentry_sdk
from opentelemetry.instrumentation.instrumentor import BaseInstrumentor  # type: ignore[attr-defined]
from structlog.testing import capture_logs
from structlog.typing import EventDict

from lite_bootstrap import import_checker


class CustomInstrumentor(BaseInstrumentor):  # type: ignore[misc]
    def instrumentation_dependencies(self) -> typing.Collection[str]:
        return []

    def _uninstrument(self, **kwargs: typing.Mapping[str, typing.Any]) -> None:
        pass


P = typing.ParamSpec("P")


class SentryTestTransport(sentry_sdk.Transport):
    def __init__(self, *args: typing.Any, **kwargs: typing.Any) -> None:  # noqa: ANN401
        super().__init__(*args, **kwargs)
        self.mock_envelopes: list[sentry_sdk.envelope.Envelope] = []

    def capture_envelope(self, envelope: sentry_sdk.envelope.Envelope) -> None:
        self.mock_envelopes.append(envelope)


@pytest.fixture
def sentry_mock() -> SentryTestTransport:
    return SentryTestTransport()


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


@pytest.fixture(name="log_output")
def fixture_log_output() -> typing.Iterator[list[EventDict]]:
    with capture_logs() as cap_logs:
        yield cap_logs
