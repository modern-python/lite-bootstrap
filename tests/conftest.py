import typing
from unittest.mock import Mock

import pytest
from opentelemetry.instrumentation.instrumentor import BaseInstrumentor  # type: ignore[attr-defined]


class CustomInstrumentor(BaseInstrumentor):  # type: ignore[misc]
    def instrumentation_dependencies(self) -> typing.Collection[str]:
        return []

    def _uninstrument(self, **kwargs: typing.Mapping[str, typing.Any]) -> None:
        pass


@pytest.fixture(autouse=True)
def mock_sentry_init(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sentry_sdk.init", Mock)
