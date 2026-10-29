import contextlib
import sys
import typing
import warnings
from collections.abc import Generator
from importlib import reload
from unittest.mock import MagicMock, patch

import opentelemetry.metrics._internal
import opentelemetry.trace
import prometheus_client
import pytest
import sentry_sdk
from opentelemetry.instrumentation.instrumentor import BaseInstrumentor
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.util._once import Once
from sentry_sdk import integrations as sentry_integrations
from sentry_sdk import scope as sentry_scope
from sentry_sdk.envelope import Envelope
from sentry_sdk.integrations import Integration
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.litestar import LitestarIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
from structlog.typing import EventDict, WrappedLogger

from lite_bootstrap import import_checker
from lite_bootstrap.exceptions import InstrumentSkippedWarning
from lite_bootstrap.instruments import healthchecks_instrument, opentelemetry_instrument


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


class ProbeError(RuntimeError):
    pass


async def passing_probe() -> bool:
    return True


async def failing_probe() -> bool:
    return False


async def raising_probe() -> bool:
    message = "dependency unreachable"
    raise ProbeError(message)


HEALTH_PROBE_CASES: typing.Final = [
    pytest.param({"db": passing_probe, "cache": passing_probe}, 200, True, [], id="all-pass"),
    pytest.param({"db": passing_probe, "cache": failing_probe}, 500, False, ["cache"], id="one-returns-false"),
    pytest.param({"db": passing_probe, "cache": raising_probe}, 500, False, ["cache"], id="one-raises"),
]


@contextlib.contextmanager
def capture_probe_warnings() -> Generator[MagicMock]:
    with patch.object(healthchecks_instrument, "logger") as mock_logger:
        yield mock_logger.warning


def failed_probe_names(warning_mock: MagicMock) -> list[str]:
    return [call.args[1] for call in warning_mock.call_args_list]


class SentryTestTransport(sentry_sdk.Transport):
    def __init__(self, *args: typing.Any, **kwargs: typing.Any) -> None:  # noqa: ANN401
        super().__init__(*args, **kwargs)
        self.mock_envelopes: list[Envelope] = []

    def capture_envelope(self, envelope: Envelope) -> None:
        self.mock_envelopes.append(envelope)


@pytest.fixture(autouse=True)
def _reset_otel_providers() -> typing.Iterator[None]:
    """Give each test the process-global tracer and meter providers unset, as a fresh process has them.

    Both setters are set-once, so without this the first test to bootstrap owns the global and every
    later one silently loses the race against it. Restoring the module-level names the SDK guards
    them with is the only way back: there is no public reset. The meter provider keeps its pair in
    `opentelemetry.metrics._internal`, one module below the public re-export.
    """
    yield
    opentelemetry.trace._TRACER_PROVIDER = None  # noqa: SLF001
    opentelemetry.trace._TRACER_PROVIDER_SET_ONCE = Once()  # noqa: SLF001
    opentelemetry.metrics._internal._METER_PROVIDER = None  # noqa: SLF001
    opentelemetry.metrics._internal._METER_PROVIDER_SET_ONCE = Once()  # noqa: SLF001


_LEAN_CAPTURE_REPLACED_INTEGRATIONS: typing.Final[tuple[type[Integration], ...]] = (
    LitestarIntegration,
    StarletteIntegration,
    FastApiIntegration,
)
_integrations_set_up: set[str] = set()


@pytest.fixture(autouse=True)
def _lean_capture_replaced_integrations_not_yet_installed(monkeypatch: pytest.MonkeyPatch) -> typing.Iterator[None]:
    """Start each test as a fresh process would, with sentry-sdk's framework integrations not installed.

    sentry-sdk records installed integrations process-wide, and ``disabled_integrations`` cannot remove one
    that an earlier ``sentry_sdk.init`` installed. Any test that bootstraps Sentry with a framework
    importable installs its integration, because they are all auto-enabling.

    An integration's patches cannot be undone, and ``setup_once`` on these integrations wraps the framework
    again on every call, which stacked over a hundred layers on ``Starlette.__call__`` across the suite. So
    once it has run it is replaced by a no-op: the registries say "not installed" while the patches from
    the first run stay in place.
    """
    identifiers: typing.Final = {integration.identifier for integration in _LEAN_CAPTURE_REPLACED_INTEGRATIONS}
    registries: typing.Final = (
        sentry_integrations._processed_integrations,  # noqa: SLF001
        sentry_integrations._installed_integrations,  # noqa: SLF001
    )
    _integrations_set_up.update(identifiers & sentry_integrations._installed_integrations)  # noqa: SLF001
    for integration in _LEAN_CAPTURE_REPLACED_INTEGRATIONS:
        if integration.identifier in _integrations_set_up:
            monkeypatch.setattr(integration, "setup_once", staticmethod(lambda: None))
    saved: typing.Final = [registry & identifiers for registry in registries]
    for registry in registries:
        registry.difference_update(identifiers)
    yield
    _integrations_set_up.update(identifiers & sentry_integrations._installed_integrations)  # noqa: SLF001
    for registry, was_there in zip(registries, saved, strict=True):
        registry.difference_update(identifiers)
        registry.update(was_there)


@pytest.fixture(autouse=True)
def _fresh_sentry_scopes() -> typing.Iterator[None]:
    """Give each test the current and isolation scopes a fresh process has.

    Tests run in one context, so a transaction name an integration left on a scope reaches every later event.
    """
    current_token: typing.Final = sentry_scope._current_scope.set(None)  # noqa: SLF001
    isolation_token: typing.Final = sentry_scope._isolation_scope.set(None)  # noqa: SLF001
    yield
    sentry_scope._isolation_scope.reset(isolation_token)  # noqa: SLF001
    sentry_scope._current_scope.reset(current_token)  # noqa: SLF001


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


def warning_source_files(caught: typing.Iterable[warnings.WarningMessage], category: type[Warning]) -> list[str]:
    """Return the file each recorded warning of ``category`` was attributed to, in the order raised.

    Attribution is what the stacklevel rules decide, so a test that pins it compares whole lists:
    a warning raised from the wrong frame and one raised twice are different bugs.
    """
    return [one_warning.filename for one_warning in caught if issubclass(one_warning.category, category)]


@contextlib.contextmanager
def emulate_package_missing(package_name: str) -> Generator[None]:
    old_module = sys.modules[package_name]
    sys.modules[package_name] = None  # ty: ignore[invalid-assignment]
    reload(import_checker)
    try:
        yield
    finally:
        sys.modules[package_name] = old_module
        reload(import_checker)


def _is_module_state(key: str) -> bool:
    # A module __getattr__ holds the module's own objects, so it is restored along with them.
    return not key.startswith("__") or key == "__getattr__"


@contextlib.contextmanager
def emulate_package_missing_with_module_reload(
    package_name: str, module_names: typing.Iterable[str]
) -> Generator[None]:
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
                for key in [k for k in mod_dict if _is_module_state(k)]:
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
                    for key in [k for k in mod_dict if _is_module_state(k)]:
                        del mod_dict[key]
                    mod_dict.update({k: v for k, v in snap.items() if _is_module_state(k)})


@contextlib.contextmanager
def in_memory_opentelemetry_metric_reader() -> Generator[InMemoryMetricReader]:
    """Hand the MeterProvider that opentelemetry_metrics_endpoint installs an in-memory reader instead of OTLP."""
    reader: typing.Final = InMemoryMetricReader()
    with patch.object(opentelemetry_instrument, "PeriodicExportingMetricReader", return_value=reader):
        yield reader


def opentelemetry_recorded_http_server_metrics(reader: InMemoryMetricReader) -> bool:
    metrics_data: typing.Final = reader.get_metrics_data()
    if metrics_data is None:
        return False
    return any(
        metric.name.startswith("http.server.")
        for resource_metrics in metrics_data.resource_metrics
        for scope_metrics in resource_metrics.scope_metrics
        for metric in scope_metrics.metrics
    )


def prometheus_recorded_path(path: str) -> bool:
    return f'"{path}"' in prometheus_client.generate_latest().decode()


def unregister_prometheus_request_metrics() -> None:
    """Unregister the instrumentator's request metrics: a second registration is skipped, not reused."""
    registered_collectors: typing.Final = dict(prometheus_client.REGISTRY._collector_to_names)  # noqa: SLF001
    for collector, names in registered_collectors.items():
        if any(name.startswith(("http_request", "http_response")) for name in names):
            prometheus_client.REGISTRY.unregister(collector)
