import logging
import types
import warnings
from unittest.mock import MagicMock

import pytest
import structlog

from lite_bootstrap import (
    FreeBootstrapper,
    FreeConfig,
    InstrumentDependencyMissingWarning,
    TeardownError,
)
from lite_bootstrap.bootstrappers.base import BaseBootstrapper
from lite_bootstrap.instruments.logging_instrument import LoggingInstrument
from lite_bootstrap.instruments.pyroscope_instrument import PyroscopeInstrument
from lite_bootstrap.instruments.sentry_instrument import SentryInstrument
from tests.conftest import CustomInstrumentor, SentryTestTransport, emulate_package_missing


logger = structlog.getLogger(__name__)


@pytest.fixture
def free_bootstrapper_config() -> FreeConfig:
    return FreeConfig(
        service_debug=False,
        opentelemetry_instrumentors=[CustomInstrumentor()],
        opentelemetry_log_traces=True,
        sentry_dsn="https://testdsn@localhost/1",
        logging_buffer_capacity=0,
    )


def test_free_bootstrap(free_bootstrapper_config: FreeConfig) -> None:
    bootstrapper = FreeBootstrapper(bootstrap_config=free_bootstrapper_config)
    bootstrapper.bootstrap()
    try:
        logger.info("testing logging", key="value")
    finally:
        bootstrapper.teardown()


def test_free_bootstrap_logging_disabled() -> None:
    bootstrapper = FreeBootstrapper(
        bootstrap_config=FreeConfig(
            logging_enabled=False,
            opentelemetry_instrumentors=[CustomInstrumentor()],
            opentelemetry_log_traces=True,
            sentry_dsn="https://testdsn@localhost/1",
            sentry_additional_params={"transport": SentryTestTransport()},
            logging_buffer_capacity=0,
        ),
    )
    skipped_classes = {cls for cls, _ in bootstrapper.skipped_instruments}
    assert LoggingInstrument in skipped_classes
    assert PyroscopeInstrument in skipped_classes


def test_teardown_error_isolation(free_bootstrapper_config: FreeConfig, caplog: pytest.LogCaptureFixture) -> None:
    bootstrapper = FreeBootstrapper(bootstrap_config=free_bootstrapper_config)
    bootstrapper.bootstrap()

    # Replace instruments with mocks: first raises, second succeeds.
    bad = MagicMock()
    bad.teardown.side_effect = RuntimeError("boom")
    good = MagicMock()
    bootstrapper.instruments = [bad, good]

    with (
        caplog.at_level(logging.WARNING, logger="lite_bootstrap.bootstrappers.base"),
        pytest.raises(TeardownError, match="boom") as excinfo,
    ):
        bootstrapper.teardown()

    # Both instruments attempted teardown despite the error (LIFO: good first, bad second).
    good.teardown.assert_called_once()
    bad.teardown.assert_called_once()
    assert any("boom" in r.message for r in caplog.records)
    assert excinfo.value.errors == [("MagicMock", excinfo.value.__cause__)]


def test_teardown_error_aggregates_all_failures(free_bootstrapper_config: FreeConfig) -> None:
    bootstrapper = FreeBootstrapper(bootstrap_config=free_bootstrapper_config)
    bootstrapper.bootstrap()

    first = MagicMock()
    first.teardown.side_effect = RuntimeError("boom-1")
    second = MagicMock()
    second.teardown.side_effect = ValueError("boom-2")
    bootstrapper.instruments = [first, second]

    with pytest.raises(TeardownError) as excinfo:
        bootstrapper.teardown()

    msg = str(excinfo.value)
    assert "2 instrument(s) failed during teardown" in msg
    assert "boom-1" in msg
    assert "boom-2" in msg
    # `second` runs first under reversed(), so its ValueError is the chained cause.
    assert isinstance(excinfo.value.__cause__, ValueError)
    assert [name for name, _ in excinfo.value.errors] == ["MagicMock", "MagicMock"]


@pytest.mark.parametrize(
    "package_name",
    [
        "opentelemetry",
        "sentry_sdk",
        "structlog",
    ],
)
def test_free_bootstrapper_with_missing_instrument_dependency(
    free_bootstrapper_config: FreeConfig, package_name: str
) -> None:
    with emulate_package_missing(package_name), pytest.warns(UserWarning, match=package_name):
        FreeBootstrapper(bootstrap_config=free_bootstrapper_config)


def test_attach_teardown_once_attaches_then_warns_and_skips(free_bootstrapper_config: FreeConfig) -> None:
    bootstrapper = FreeBootstrapper(bootstrap_config=free_bootstrapper_config)
    target = types.SimpleNamespace()
    attach = MagicMock()

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        bootstrapper._attach_teardown_once(target, attach)  # noqa: SLF001

    attach.assert_called_once()
    assert getattr(target, BaseBootstrapper._TEARDOWN_MARKER) is True  # noqa: SLF001

    with pytest.warns(UserWarning, match="already has a lite-bootstrap teardown hook"):
        bootstrapper._attach_teardown_once(target, attach)  # noqa: SLF001

    attach.assert_called_once()  # still once — second attach skipped


def test_attach_teardown_once_does_not_mark_when_attach_raises(free_bootstrapper_config: FreeConfig) -> None:
    bootstrapper = FreeBootstrapper(bootstrap_config=free_bootstrapper_config)
    target = types.SimpleNamespace()

    failing = MagicMock(side_effect=RuntimeError("attach boom"))
    with pytest.raises(RuntimeError, match="attach boom"):
        bootstrapper._attach_teardown_once(target, failing)  # noqa: SLF001

    # A failed attach must leave the target untagged so a retry can re-attach.
    assert not getattr(target, BaseBootstrapper._TEARDOWN_MARKER, False)  # noqa: SLF001

    retry = MagicMock()
    bootstrapper._attach_teardown_once(target, retry)  # noqa: SLF001
    retry.assert_called_once()
    assert getattr(target, BaseBootstrapper._TEARDOWN_MARKER) is True  # noqa: SLF001


def test_teardown_is_idempotent(free_bootstrapper_config: FreeConfig) -> None:
    bootstrapper = FreeBootstrapper(bootstrap_config=free_bootstrapper_config)
    bootstrapper.bootstrap()

    first = MagicMock()
    second = MagicMock()
    bootstrapper.instruments = [first, second]

    bootstrapper.teardown()
    bootstrapper.teardown()

    first.teardown.assert_called_once()
    second.teardown.assert_called_once()
    assert not bootstrapper.is_bootstrapped


def test_bootstrap_is_idempotent(free_bootstrapper_config: FreeConfig) -> None:
    bootstrapper = FreeBootstrapper(bootstrap_config=free_bootstrapper_config)

    first = MagicMock()
    second = MagicMock()
    bootstrapper.instruments = [first, second]

    bootstrapper.bootstrap()
    bootstrapper.bootstrap()

    first.bootstrap.assert_called_once()
    second.bootstrap.assert_called_once()
    assert bootstrapper.is_bootstrapped


def test_free_bootstrap_emits_summary_log(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="lite_bootstrap.bootstrappers.base"):
        FreeBootstrapper(
            bootstrap_config=FreeConfig(
                sentry_dsn="https://testdsn@localhost/1",
                sentry_additional_params={"transport": SentryTestTransport()},
            ),
        )
    summary_records = [r for r in caplog.records if "FreeBootstrapper" in r.message]
    assert summary_records, "expected a summary log entry mentioning FreeBootstrapper"
    summary = summary_records[-1].message
    assert "  configured:" in summary
    assert "  skipped:" in summary


def test_build_summary_format() -> None:
    bootstrapper = FreeBootstrapper(
        bootstrap_config=FreeConfig(
            sentry_dsn="https://testdsn@localhost/1",
            sentry_additional_params={"transport": SentryTestTransport()},
            logging_enabled=False,
            logging_buffer_capacity=0,
        ),
    )
    summary = bootstrapper.build_summary()
    assert summary.startswith("FreeBootstrapper:")
    assert "  configured:" in summary
    assert "  skipped:" in summary
    assert "    - SentryInstrument" in summary
    assert "    - LoggingInstrument: logging_enabled is False" in summary


def test_config_skip_emits_no_warning() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # any UserWarning becomes a test failure
        bootstrapper = FreeBootstrapper(
            bootstrap_config=FreeConfig(
                logging_enabled=False,
                logging_buffer_capacity=0,
            ),
        )
    assert LoggingInstrument in {cls for cls, _ in bootstrapper.skipped_instruments}


def test_only_the_silent_skip_path_lands_in_skipped_instruments() -> None:
    """INVARIANT: a config skip is recorded in `skipped_instruments`; a dependency skip is not.

    The two skips mean opposite things. "You did not ask for Sentry" is the normal case and gets no
    warning, so `skipped_instruments` (and the `build_summary()` line built from it) is the only
    place it is visible — that list is the answer to "why is this instrument not running." "You
    asked for Sentry and sentry-sdk is not installed" is a deployment surprise that already shouts
    through a warning and a `logger.warning`, and adding it to the same list would put a fault and a
    non-fault next to each other under one heading, making the quiet one impossible to scan for.

    Folding the dependency path into `skipped_instruments` is what breaks it, and it is an inviting
    change to make: the list looks incomplete until you know it is a list of one specific thing.
    `skipped_instruments` is public — documented for programmatic inspection — so a consumer
    filtering on it would start seeing entries that mean the opposite of what it filtered for.
    """
    config_skip = FreeBootstrapper(
        bootstrap_config=FreeConfig(logging_enabled=False, logging_buffer_capacity=0),
    )
    assert LoggingInstrument in {cls for cls, _ in config_skip.skipped_instruments}

    with (
        emulate_package_missing("sentry_sdk"),
        pytest.warns(InstrumentDependencyMissingWarning, match="sentry_sdk"),
    ):
        dependency_skip = FreeBootstrapper(
            bootstrap_config=FreeConfig(
                sentry_dsn="https://testdsn@localhost/1",
                logging_enabled=False,
                logging_buffer_capacity=0,
            ),
        )

    assert SentryInstrument not in {cls for cls, _ in dependency_skip.skipped_instruments}
    assert SentryInstrument not in {type(i) for i in dependency_skip.instruments}


def test_missing_dependency_warning_logs_via_logger_too(
    free_bootstrapper_config: FreeConfig, caplog: pytest.LogCaptureFixture
) -> None:
    with (
        emulate_package_missing("sentry_sdk"),
        caplog.at_level(logging.WARNING, logger="lite_bootstrap.bootstrappers.base"),
        pytest.warns(UserWarning, match="sentry_sdk"),
    ):
        FreeBootstrapper(bootstrap_config=free_bootstrapper_config)

    matching = [r for r in caplog.records if "sentry_sdk" in r.message and r.levelname == "WARNING"]
    assert matching, [r.message for r in caplog.records]


def test_build_summary_renders_none_for_empty_sections() -> None:
    bootstrapper = FreeBootstrapper(
        bootstrap_config=FreeConfig(
            sentry_dsn="https://testdsn@localhost/1",
            sentry_additional_params={"transport": SentryTestTransport()},
        ),
    )
    bootstrapper.instruments = []
    bootstrapper.skipped_instruments = []
    summary = bootstrapper.build_summary()
    assert summary == "FreeBootstrapper:\n  configured:\n    (none)\n  skipped:\n    (none)"


def test_two_free_bootstrappers_both_bootstrap(free_bootstrapper_config: FreeConfig) -> None:
    """FreeBootstrapper has no application to own, so the double-bootstrap guard must not fire."""
    first = FreeBootstrapper(bootstrap_config=free_bootstrapper_config)
    second = FreeBootstrapper(bootstrap_config=free_bootstrapper_config)

    try:
        first.bootstrap()
        second.bootstrap()

        assert first.is_bootstrapped
        assert second.is_bootstrapped
    finally:
        second.teardown()
        first.teardown()
