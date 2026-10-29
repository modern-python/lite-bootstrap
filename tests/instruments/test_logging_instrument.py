import contextlib
import json
import logging
from io import StringIO
from unittest.mock import patch

import pytest
import structlog
from opentelemetry.trace import get_tracer

from lite_bootstrap.exceptions import TeardownError
from lite_bootstrap.instruments.logging_factory import _MemoryLoggerFactoryConfig
from lite_bootstrap.instruments.logging_instrument import LoggingConfig, LoggingInstrument, MemoryLoggerFactory
from lite_bootstrap.instruments.opentelemetry_instrument import OpenTelemetryConfig, OpenTelemetryInstrument
from tests.conftest import LoggingMock


def test_logging_instrument_simple(logging_mock: LoggingMock) -> None:
    logging_instrument = LoggingInstrument(
        bootstrap_config=LoggingConfig(
            logging_unset_handlers=["uvicorn"],
            service_debug=False,
            logging_extra_processors=[logging_mock],
        )
    )
    try:
        logging_instrument.bootstrap()

        std_logger = logging.getLogger(__name__)
        std_logger.info("testing std logger", extra={"key": "value"})

        logger = structlog.getLogger(__name__)
        logger.info("testing structlog", key="value")

        try:
            msg = "some error"
            raise ValueError(msg)  # noqa: TRY301
        except ValueError:
            logger.exception("logging error")

        events_number = 3
        assert len(logging_mock.entries) == events_number
    finally:
        logging_instrument.teardown()


def test_logging_instrument_tracer_injection(logging_mock: LoggingMock) -> None:
    logging_instrument = LoggingInstrument(
        bootstrap_config=LoggingConfig(
            logging_unset_handlers=["uvicorn"],
            logging_extra_processors=[logging_mock],
        )
    )
    opentelemetry_instrument = OpenTelemetryInstrument(
        bootstrap_config=OpenTelemetryConfig(
            opentelemetry_log_traces=True,
        )
    )
    try:
        logging_instrument.bootstrap()
        opentelemetry_instrument.bootstrap()

        logger = structlog.getLogger(__name__)
        tracer = get_tracer(__name__)
        logger.info("testing tracer injection without spans")
        with tracer.start_as_current_span("my_fake_span") as span:
            logger.info("testing tracer injection without span attributes")
            span.set_attribute("example_attribute", "value")
            span.add_event("example_event", {"event_attr": 1})
            logger.info("testing tracer injection with span attributes")

        assert logging_mock.entries[0]["event"] == "testing tracer injection without spans"

        assert logging_mock.entries[1]["event"] == "testing tracer injection without span attributes"
        assert logging_mock.entries[2]["event"] == "testing tracer injection with span attributes"

        tracing1 = logging_mock.entries[1]["tracing"]
        tracing2 = logging_mock.entries[2]["tracing"]
        assert tracing1
        assert tracing1 == tracing2
    finally:
        logging_instrument.teardown()
        opentelemetry_instrument.teardown()


def _make_factory(stream: StringIO) -> MemoryLoggerFactory:
    return MemoryLoggerFactory(
        config=_MemoryLoggerFactoryConfig(logging_log_level=logging.INFO, log_stream=stream),
    )


def test_memory_logger_factory_writes_each_line_at_once() -> None:
    test_stream = StringIO()
    logger_factory = _make_factory(test_stream)
    try:
        test_logger = logger_factory("written_at_once")
        test_logger.info("first")
        assert test_stream.getvalue().splitlines() == ["first"]
        test_logger.info("second")
        assert test_stream.getvalue().splitlines() == ["first", "second"]
        assert [type(handler) for handler in test_logger.handlers] == [logging.StreamHandler]
    finally:
        logger_factory.close_handlers()


def test_memory_logger_factory_configures_each_logger_once() -> None:
    test_stream = StringIO()
    logger_factory = _make_factory(test_stream)
    try:
        first = logger_factory("configured_once")
        second = logger_factory("configured_once")
        second.info("one line")

        assert first is second
        assert len(first.handlers) == 1
        assert test_stream.getvalue().splitlines() == ["one line"]
    finally:
        logger_factory.close_handlers()

    assert logging.getLogger("configured_once").handlers == []


def test_memory_logger_factory_names_unnamed_logger_after_caller() -> None:
    logger_factory = _make_factory(StringIO())
    try:
        assert logger_factory().name == __name__
    finally:
        logger_factory.close_handlers()


def test_memory_logger_factory_keeps_a_level_set_beforehand() -> None:
    preset_logger = logging.getLogger("preset_level")
    preset_logger.setLevel(logging.DEBUG)
    logger_factory = _make_factory(StringIO())
    try:
        assert logger_factory("preset_level").level == logging.DEBUG
        assert logger_factory("unset_level").level == logging.INFO
    finally:
        logger_factory.close_handlers()
        preset_logger.setLevel(logging.NOTSET)
        logging.getLogger("unset_level").setLevel(logging.NOTSET)


def test_memory_logger_factory_close_handlers_restores_the_level_it_set() -> None:
    logger_factory = _make_factory(StringIO())
    logger_factory("restored_level")
    logger_factory.close_handlers()

    assert logging.getLogger("restored_level").level == logging.NOTSET


def test_logging_instrument_lifecycle_replay(logging_mock: LoggingMock) -> None:
    instrument = LoggingInstrument(
        bootstrap_config=LoggingConfig(
            logging_extra_processors=[logging_mock],
        ),
    )
    try:
        instrument.bootstrap()
        instrument.teardown()
        instrument.bootstrap()
        logger = structlog.getLogger(__name__)
        logger.info("after replay")
        assert any(e.get("event") == "after replay" for e in logging_mock.entries)
    finally:
        instrument.teardown()


def test_logging_instrument_teardown_resets_factory_when_close_handlers_raises() -> None:
    instrument = LoggingInstrument(
        bootstrap_config=LoggingConfig(),
    )
    instrument.bootstrap()
    factory = instrument._logger_factory  # noqa: SLF001
    assert factory is not None

    with (
        patch.object(factory, "close_handlers", side_effect=RuntimeError("boom")),
        pytest.raises(TeardownError) as excinfo,
    ):
        instrument.teardown()

    assert any("boom" in str(err) for _, err in excinfo.value.errors)
    assert instrument._logger_factory is None  # noqa: SLF001


def test_logging_instrument_teardown_aggregates_handler_close_errors() -> None:
    instrument = LoggingInstrument(
        bootstrap_config=LoggingConfig(),
    )
    instrument.bootstrap()
    root_logger = logging.getLogger()

    # Find the StreamHandler added by _configure_foreign_loggers and patch its close.
    bootstrap_added = [h for h in root_logger.handlers if isinstance(h, logging.StreamHandler)]
    assert bootstrap_added, "bootstrap should have added at least one StreamHandler to root"
    target_handler = bootstrap_added[0]

    with (
        patch.object(target_handler, "close", side_effect=RuntimeError("boom")),
        pytest.raises(TeardownError, match="boom") as excinfo,
    ):
        instrument.teardown()
    assert isinstance(excinfo.value.__cause__, RuntimeError)
    assert any("boom" in str(err) for _, err in excinfo.value.errors)

    # After teardown despite the raise, post-loop cleanup must have completed:
    assert instrument._logger_factory is None  # noqa: SLF001
    assert root_logger.level == logging.WARNING
    # And the broken handler must have been removed from root despite raising.
    assert target_handler not in root_logger.handlers


def test_logging_instrument_teardown_aggregates_handler_and_factory_errors() -> None:
    instrument = LoggingInstrument(
        bootstrap_config=LoggingConfig(),
    )
    instrument.bootstrap()
    root_logger = logging.getLogger()
    factory = instrument._logger_factory  # noqa: SLF001
    assert factory is not None

    target_handler = next(h for h in root_logger.handlers if isinstance(h, logging.StreamHandler))

    with (
        patch.object(target_handler, "close", side_effect=RuntimeError("handler boom")),
        patch.object(factory, "close_handlers", side_effect=RuntimeError("factory boom")),
        pytest.raises(TeardownError) as excinfo,
    ):
        instrument.teardown()

    error_msgs = [str(err) for _, err in excinfo.value.errors]
    assert any("handler boom" in m for m in error_msgs), error_msgs
    assert any("factory boom" in m for m in error_msgs), error_msgs
    assert instrument._logger_factory is None  # noqa: SLF001


def test_logging_instrument_binds_log_stream_at_bootstrap() -> None:
    """The structlog logger writes to the stdout in effect at bootstrap, not the one bound at import."""
    redirected_stdout = StringIO()
    logging_instrument = LoggingInstrument(bootstrap_config=LoggingConfig())
    try:
        with contextlib.redirect_stdout(redirected_stdout):
            logging_instrument.bootstrap()
            structlog.getLogger("log_stream_binding").info("bound at bootstrap")
    finally:
        logging_instrument.teardown()

    assert "bound at bootstrap" in redirected_stdout.getvalue()


def test_one_rendered_event_is_one_physical_line(capsys: pytest.CaptureFixture[str]) -> None:
    """INVARIANT: a structlog event reaches stdout as exactly one physical line.

    The processor chain renders the whole event — traceback included, under the `exception` key —
    before the string ever becomes a `LogRecord`. Everything downstream of that is transport, so
    the handler must emit the rendered string verbatim.

    Dropping the formatter from the stream handler `MemoryLoggerFactory` builds is what breaks it,
    and the break is invisible until something raises: stdlib's `Logger.exception` hardcodes
    `exc_info=True` on the record, so the default `logging.Formatter` appends `record.exc_text`
    after the JSON and the same traceback ships twice. Every line-oriented log shipper reads the
    suffix as four malformed events.
    """
    logging_instrument = LoggingInstrument(bootstrap_config=LoggingConfig())
    try:
        logging_instrument.bootstrap()
        logger = structlog.getLogger("one_physical_line")
        try:
            msg = "some error"
            raise ValueError(msg)  # noqa: TRY301
        except ValueError:
            logger.exception("logging error")
    finally:
        logging_instrument.teardown()

    lines = capsys.readouterr().out.splitlines()

    assert len(lines) == 1, lines
    payload = json.loads(lines[0])
    assert payload["event"] == "logging error"
    assert "ValueError: some error" in payload["exception"]


def test_foreign_logger_exception_is_one_physical_line(capsys: pytest.CaptureFixture[str]) -> None:
    """The same one-line contract holds for a plain stdlib logger going through the root handler."""
    logging_instrument = LoggingInstrument(bootstrap_config=LoggingConfig())
    try:
        logging_instrument.bootstrap()
        try:
            msg = "some error"
            raise ValueError(msg)  # noqa: TRY301
        except ValueError:
            logging.getLogger("foreign_one_physical_line").exception("logging error")
    finally:
        logging_instrument.teardown()

    lines = capsys.readouterr().out.splitlines()

    assert len(lines) == 1, lines
    payload = json.loads(lines[0])
    assert payload["event"] == "logging error"
    assert "ValueError: some error" in payload["exception"]


def test_structlog_lines_are_written_at_once_and_in_order_with_stdlib_lines(
    capsys: pytest.CaptureFixture[str],
) -> None:
    logging_instrument = LoggingInstrument(bootstrap_config=LoggingConfig())
    try:
        logging_instrument.bootstrap()
        structlog.getLogger("ordered_app").info("1")
        logging.getLogger("ordered_lib").warning("2")
        structlog.getLogger("ordered_app").info("3")

        events = [json.loads(line)["event"] for line in capsys.readouterr().out.splitlines()]
    finally:
        logging_instrument.teardown()

    assert events == ["1", "2", "3"]
