import contextlib
import json
import logging
import threading
import typing
from io import StringIO
from unittest.mock import patch

import pytest
import structlog
from opentelemetry.trace import get_tracer

from lite_bootstrap.exceptions import TeardownError
from lite_bootstrap.instruments.logging_instrument import LoggingConfig, LoggingInstrument
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


def test_unnamed_structlog_logger_is_named_after_its_caller(capsys: pytest.CaptureFixture[str]) -> None:
    logging_instrument = LoggingInstrument(bootstrap_config=LoggingConfig())
    try:
        logging_instrument.bootstrap()
        structlog.getLogger().info("unnamed")
    finally:
        logging_instrument.teardown()

    assert json.loads(capsys.readouterr().out)["logger"] == __name__


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
    assert root_logger.level == logging.WARNING
    # And the broken handler must have been removed from root despite raising.
    assert target_handler not in root_logger.handlers


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

    The root handler's formatter has to pass that string through. If it treated the record as
    foreign, it would render the JSON line again as the `event` of a second JSON object, and
    stdlib's `Logger.exception`, which sets `exc_info=True` on the record, would add the same
    traceback a second time.
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


def test_stdlib_lines_on_a_structlog_logger_name_stay_json(capsys: pytest.CaptureFixture[str]) -> None:
    logging_instrument = LoggingInstrument(bootstrap_config=LoggingConfig())
    try:
        logging_instrument.bootstrap()
        structlog.getLogger("shared_name").info("from structlog")
        logging.getLogger("shared_name").info("from stdlib %s", "same name")
        logging.getLogger("shared_name.child").info("from stdlib child")
        try:
            msg = "some error"
            raise ValueError(msg)  # noqa: TRY301
        except ValueError:
            logging.getLogger("shared_name").exception("stdlib exception")
    finally:
        logging_instrument.teardown()

    payloads = [json.loads(line) for line in capsys.readouterr().out.splitlines()]

    assert [(payload["logger"], payload["event"]) for payload in payloads] == [
        ("shared_name", "from structlog"),
        ("shared_name", "from stdlib same name"),
        ("shared_name.child", "from stdlib child"),
        ("shared_name", "stdlib exception"),
    ]
    assert "ValueError: some error" in payloads[-1]["exception"]


def test_concurrent_first_use_of_a_logger_name_writes_each_line_once(capsys: pytest.CaptureFixture[str]) -> None:
    thread_count: typing.Final = 8
    start_barrier: typing.Final = threading.Barrier(thread_count)

    def log_once(thread_number: int) -> None:
        start_barrier.wait()
        structlog.getLogger("concurrent_first_use").info(f"thread {thread_number}")

    logging_instrument = LoggingInstrument(bootstrap_config=LoggingConfig())
    try:
        logging_instrument.bootstrap()
        threads = [threading.Thread(target=log_once, args=(number,)) for number in range(thread_count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert logging.getLogger("concurrent_first_use").handlers == []
    finally:
        logging_instrument.teardown()

    events = sorted(json.loads(line)["event"] for line in capsys.readouterr().out.splitlines())

    assert events == sorted(f"thread {number}" for number in range(thread_count))
