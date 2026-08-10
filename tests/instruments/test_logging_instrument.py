import contextlib
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
            logging_buffer_capacity=0,
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
            logging_buffer_capacity=0,
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


def test_memory_logger_factory_info() -> None:
    test_capacity = 10
    test_flush_level = logging.ERROR
    test_stream = StringIO()

    logger_factory = MemoryLoggerFactory(
        config=_MemoryLoggerFactoryConfig(
            logging_buffer_capacity=test_capacity,
            logging_flush_level=test_flush_level,
            logging_log_level=logging.INFO,
            log_stream=test_stream,
        ),
    )
    test_logger = logger_factory()
    test_message = "test message"

    for current_log_index in range(test_capacity):
        test_logger.info(test_message)
        log_contents = test_stream.getvalue()
        if current_log_index == test_capacity - 1:
            assert test_message in log_contents
        else:
            assert not log_contents


def test_memory_logger_factory_error() -> None:
    test_capacity = 10
    test_flush_level = logging.ERROR
    test_stream = StringIO()

    logger_factory = MemoryLoggerFactory(
        config=_MemoryLoggerFactoryConfig(
            logging_buffer_capacity=test_capacity,
            logging_flush_level=test_flush_level,
            logging_log_level=logging.INFO,
            log_stream=test_stream,
        ),
    )
    test_logger = logger_factory()
    error_message = "error message"
    test_logger.error(error_message)
    assert error_message in test_stream.getvalue()


def test_logging_instrument_lifecycle_replay(logging_mock: LoggingMock) -> None:
    instrument = LoggingInstrument(
        bootstrap_config=LoggingConfig(
            logging_buffer_capacity=0,
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
        bootstrap_config=LoggingConfig(logging_buffer_capacity=0),
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
        bootstrap_config=LoggingConfig(logging_buffer_capacity=0),
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
        bootstrap_config=LoggingConfig(logging_buffer_capacity=0),
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
    """The memory logger writes to the stdout in effect at bootstrap, not the one bound at import."""
    redirected_stdout = StringIO()
    logging_instrument = LoggingInstrument(bootstrap_config=LoggingConfig(logging_buffer_capacity=0))
    try:
        with contextlib.redirect_stdout(redirected_stdout):
            logging_instrument.bootstrap()
            structlog.getLogger("log_stream_binding").info("bound at bootstrap")
    finally:
        logging_instrument.teardown()

    assert "bound at bootstrap" in redirected_stdout.getvalue()
