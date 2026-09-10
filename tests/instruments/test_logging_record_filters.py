import json
import logging
import typing

import faststream.asgi
import pytest
import structlog
from faststream.redis import RedisBroker

from lite_bootstrap import (
    FastAPIBootstrapper,
    FastAPIConfig,
    FastStreamBootstrapper,
    FastStreamConfig,
    FreeBootstrapper,
    FreeConfig,
    LitestarBootstrapper,
    LitestarConfig,
    TeardownError,
)
from lite_bootstrap.bootstrappers.base import BaseBootstrapper
from lite_bootstrap.instruments.logging_instrument import LoggingConfig, LoggingInstrument
from lite_bootstrap.instruments.sentry_instrument import SentryConfig, SentryInstrument
from tests.conftest import SentryTestTransport


class RecordingFilter(logging.Filter):
    """Records every LogRecord it sees and lets it through unchanged."""

    def __init__(self) -> None:
        super().__init__()
        self.seen: list[logging.LogRecord] = []

    def filter(self, record: logging.LogRecord) -> bool:
        self.seen.append(record)
        return True


class DemotingFilter(logging.Filter):
    """Demotes records whose message contains ``needle`` from ERROR to WARNING."""

    def __init__(self, needle: str) -> None:
        super().__init__()
        self.needle = needle

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno == logging.ERROR and self.needle in record.getMessage():
            record.levelno = logging.WARNING
            record.levelname = "WARNING"
        return True


class SuppressingFilter(logging.Filter):
    def __init__(self, needle: str) -> None:
        super().__init__()
        self.needle = needle

    def filter(self, record: logging.LogRecord) -> bool:
        return self.needle not in record.getMessage()


@pytest.fixture
def rendered_lines(capsys: pytest.CaptureFixture[str]) -> typing.Callable[[], list[dict[str, typing.Any]]]:
    def read() -> list[dict[str, typing.Any]]:
        return [json.loads(line) for line in capsys.readouterr().out.splitlines()]

    return read


@pytest.fixture
def sentry_config(sentry_mock: SentryTestTransport) -> SentryConfig:
    return SentryConfig(
        sentry_dsn="https://testdsn@localhost/1",
        sentry_additional_params={"transport": sentry_mock},
    )


def test_default_config_attaches_no_filters() -> None:
    """A config that does not ask for filters leaves every logger's filter list untouched."""
    package_logger = logging.getLogger("default_compat.package")
    filters_before = list(package_logger.filters)
    instrument = LoggingInstrument(bootstrap_config=LoggingConfig(logging_buffer_capacity=0))
    try:
        instrument.bootstrap()
        assert package_logger.filters == filters_before
        assert instrument._attached_filters == []  # noqa: SLF001
    finally:
        instrument.teardown()


def test_filter_receives_records_from_its_exact_logger() -> None:
    record_filter = RecordingFilter()
    instrument = LoggingInstrument(
        bootstrap_config=LoggingConfig(
            logging_buffer_capacity=0,
            logging_record_filters={"exact_match.package.child": (record_filter,)},
        ),
    )
    try:
        instrument.bootstrap()
        logging.getLogger("exact_match.package.child").error("child speaking")
    finally:
        instrument.teardown()

    assert [record.getMessage() for record in record_filter.seen] == ["child speaking"]


def test_filter_on_parent_logger_does_not_see_child_records() -> None:
    """INVARIANT: a filter registered for one logger name sees only that logger's own records.

    `logging.Logger.handle` consults `self.filters` and then walks *ancestors' handlers*, never
    ancestors' filters, so a filter on `package` is dead weight for anything `package.child` emits.
    Reading `logging_record_filters` as a prefix map is the mistake this pins: a user who writes
    `{"aiokafka": (...)}` expecting to catch `aiokafka.consumer.group_coordinator` gets silence,
    and silence is indistinguishable from a filter that ran and declined to match.
    """
    parent_filter = RecordingFilter()
    instrument = LoggingInstrument(
        bootstrap_config=LoggingConfig(
            logging_buffer_capacity=0,
            logging_record_filters={"no_inheritance.package": (parent_filter,)},
        ),
    )
    try:
        instrument.bootstrap()
        logging.getLogger("no_inheritance.package.child").error("from the child")
        logging.getLogger("no_inheritance.package").error("from the parent")
    finally:
        instrument.teardown()

    assert [record.getMessage() for record in parent_filter.seen] == ["from the parent"]


def test_filter_demotes_level_before_handlers_render_it(
    rendered_lines: typing.Callable[[], list[dict[str, typing.Any]]],
) -> None:
    observed: list[tuple[int, str]] = []

    class ObservingFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            observed.append((record.levelno, record.levelname))
            return True

    instrument = LoggingInstrument(
        bootstrap_config=LoggingConfig(
            logging_buffer_capacity=0,
            logging_record_filters={
                "demotion.target": (DemotingFilter("expected failure"), ObservingFilter()),
            },
        ),
    )
    try:
        instrument.bootstrap()
        logging.getLogger("demotion.target").error("expected failure, retrying")
    finally:
        instrument.teardown()

    assert observed == [(logging.WARNING, "WARNING")]
    assert [(line["event"], line["level"]) for line in rendered_lines()] == [("expected failure, retrying", "warning")]


def test_demoted_record_creates_no_sentry_issue_event(
    sentry_config: SentryConfig, sentry_mock: SentryTestTransport
) -> None:
    """INVARIANT: a filter demoting a record below Sentry's event level keeps it out of Sentry.

    Sentry's `LoggingIntegration` patches `logging.Logger.callHandlers`, which `Logger.handle`
    reaches only after `self.filter(record)` returns truthy — so a logger filter is upstream of
    Sentry whatever order the bootstrapper installs the two instruments in. Moving this seam to a
    structlog processor or a root *handler* filter is what breaks it: both run downstream of the
    patched `callHandlers`, and the issue is already created by the time they see the record.
    """
    logging_instrument = LoggingInstrument(
        bootstrap_config=LoggingConfig(
            logging_buffer_capacity=0,
            logging_record_filters={"sentry_demotion.target": (DemotingFilter("expected failure"),)},
        ),
    )
    sentry_instrument = SentryInstrument(bootstrap_config=sentry_config)
    try:
        logging_instrument.bootstrap()
        sentry_instrument.bootstrap()

        target_logger = logging.getLogger("sentry_demotion.target")
        target_logger.error("expected failure, retrying")
        assert sentry_mock.mock_envelopes == []

        target_logger.error("a connection reset")
        assert len(sentry_mock.mock_envelopes) == 1
    finally:
        sentry_instrument.teardown()
        logging_instrument.teardown()


def test_suppressing_filter_keeps_record_from_stream_and_sentry(
    sentry_config: SentryConfig,
    sentry_mock: SentryTestTransport,
    rendered_lines: typing.Callable[[], list[dict[str, typing.Any]]],
) -> None:
    logging_instrument = LoggingInstrument(
        bootstrap_config=LoggingConfig(
            logging_buffer_capacity=0,
            logging_record_filters={"suppression.target": (SuppressingFilter("drop me"),)},
        ),
    )
    sentry_instrument = SentryInstrument(bootstrap_config=sentry_config)
    try:
        logging_instrument.bootstrap()
        sentry_instrument.bootstrap()
        logging.getLogger("suppression.target").error("drop me entirely")
    finally:
        sentry_instrument.teardown()
        logging_instrument.teardown()

    assert rendered_lines() == []
    assert sentry_mock.mock_envelopes == []


def test_non_matching_record_renders_identically_with_and_without_filters(
    capsys: pytest.CaptureFixture[str],
) -> None:
    timestamper = structlog.processors.TimeStamper(fmt="iso")

    def render_untouched(record_filters: dict[str, tuple[logging.Filter, ...]]) -> dict[str, typing.Any]:
        instrument = LoggingInstrument(
            bootstrap_config=LoggingConfig(
                logging_buffer_capacity=0,
                logging_time_stamper=timestamper,
                logging_record_filters=record_filters,
            ),
        )
        try:
            instrument.bootstrap()
            logging.getLogger("untouched.target").error("an unrelated failure")
        finally:
            instrument.teardown()
        rendered: dict[str, typing.Any] = json.loads(capsys.readouterr().out)
        del rendered["timestamp"]
        return rendered

    assert render_untouched({"untouched.target": (SuppressingFilter("drop me"),)}) == render_untouched({})


def test_teardown_removes_only_the_filters_it_attached() -> None:
    preexisting_filter = RecordingFilter()
    configured_filter = RecordingFilter()
    target_logger = logging.getLogger("teardown_isolation.target")
    target_logger.addFilter(preexisting_filter)

    instrument = LoggingInstrument(
        bootstrap_config=LoggingConfig(
            logging_buffer_capacity=0,
            logging_record_filters={"teardown_isolation.target": (configured_filter,)},
        ),
    )
    try:
        instrument.bootstrap()
        assert target_logger.filters == [preexisting_filter, configured_filter]

        instrument.teardown()

        assert target_logger.filters == [preexisting_filter]
        assert instrument._attached_filters == []  # noqa: SLF001
    finally:
        target_logger.removeFilter(preexisting_filter)


def test_teardown_removes_filters_even_when_a_handler_close_fails() -> None:
    configured_filter = RecordingFilter()
    target_logger = logging.getLogger("teardown_despite_error.target")

    class ExplodingHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            """Never called: this handler exists only to fail on close."""

        def close(self) -> None:
            msg = "boom"
            raise RuntimeError(msg)

    instrument = LoggingInstrument(
        bootstrap_config=LoggingConfig(
            logging_buffer_capacity=0,
            logging_record_filters={"teardown_despite_error.target": (configured_filter,)},
        ),
    )
    instrument.bootstrap()
    exploding_handler = ExplodingHandler()
    logging.getLogger().addHandler(exploding_handler)

    with pytest.raises(TeardownError):
        instrument.teardown()

    assert target_logger.filters == []
    assert instrument._attached_filters == []  # noqa: SLF001


def test_bootstrap_teardown_bootstrap_attaches_each_filter_once() -> None:
    configured_filter = RecordingFilter()
    target_logger = logging.getLogger("filter_lifecycle.target")
    instrument = LoggingInstrument(
        bootstrap_config=LoggingConfig(
            logging_buffer_capacity=0,
            logging_record_filters={"filter_lifecycle.target": (configured_filter,)},
        ),
    )
    try:
        instrument.bootstrap()
        instrument.teardown()
        instrument.bootstrap()

        assert target_logger.filters == [configured_filter]
        target_logger.error("once through")
        assert len(configured_filter.seen) == 1
    finally:
        instrument.teardown()

    assert target_logger.filters == []


BootstrapperBuilder = typing.Callable[
    [dict[str, tuple[logging.Filter, ...]]],
    BaseBootstrapper[typing.Any],
]


def _build_free_bootstrapper(record_filters: dict[str, tuple[logging.Filter, ...]]) -> FreeBootstrapper:
    return FreeBootstrapper(
        bootstrap_config=FreeConfig(logging_buffer_capacity=0, logging_record_filters=record_filters),
    )


def _build_fastapi_bootstrapper(record_filters: dict[str, tuple[logging.Filter, ...]]) -> FastAPIBootstrapper:
    return FastAPIBootstrapper(
        bootstrap_config=FastAPIConfig(logging_buffer_capacity=0, logging_record_filters=record_filters),
    )


def _build_faststream_bootstrapper(record_filters: dict[str, tuple[logging.Filter, ...]]) -> FastStreamBootstrapper:
    return FastStreamBootstrapper(
        bootstrap_config=FastStreamConfig(
            logging_buffer_capacity=0,
            logging_record_filters=record_filters,
            application=faststream.asgi.AsgiFastStream(RedisBroker()),
        ),
    )


def _build_litestar_bootstrapper(record_filters: dict[str, tuple[logging.Filter, ...]]) -> LitestarBootstrapper:
    return LitestarBootstrapper(
        bootstrap_config=LitestarConfig(logging_buffer_capacity=0, logging_record_filters=record_filters),
    )


@pytest.mark.parametrize(
    ("framework", "build_bootstrapper"),
    [
        ("free", _build_free_bootstrapper),
        ("fastapi", _build_fastapi_bootstrapper),
        ("faststream", _build_faststream_bootstrapper),
        ("litestar", _build_litestar_bootstrapper),
    ],
)
def test_every_bootstrapper_installs_configured_filters(
    framework: str, build_bootstrapper: BootstrapperBuilder
) -> None:
    configured_filter = RecordingFilter()
    logger_name = f"bootstrapper_filters.{framework}"
    target_logger = logging.getLogger(logger_name)

    bootstrapper = build_bootstrapper({logger_name: (configured_filter,)})
    bootstrapper.bootstrap()
    try:
        target_logger.error("through the bootstrapper")
    finally:
        bootstrapper.teardown()

    assert [record.getMessage() for record in configured_filter.seen] == ["through the bootstrapper"]
    assert target_logger.filters == []
