import contextlib
import sys
import typing
from importlib import reload
from unittest.mock import Mock

import pytest
from opentelemetry.instrumentation.instrumentor import BaseInstrumentor  # type: ignore[attr-defined]

from lite_bootstrap import import_checker


class CustomInstrumentor(BaseInstrumentor):  # type: ignore[misc]
    def instrumentation_dependencies(self) -> typing.Collection[str]:
        return []

    def _uninstrument(self, **kwargs: typing.Mapping[str, typing.Any]) -> None:
        pass


@pytest.fixture(autouse=True)
def mock_sentry_init(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sentry_sdk.init", Mock)


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
