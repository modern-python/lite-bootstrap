import logging
from io import StringIO

import structlog
from opentelemetry.trace import get_tracer
from structlog.testing import LogCapture

from lite_bootstrap.instruments.logging_instrument import LoggingConfig, LoggingInstrument, MemoryLoggerFactory
from lite_bootstrap.instruments.opentelemetry_instrument import OpentelemetryConfig, OpenTelemetryInstrument


std_logger = logging.getLogger(__name__)


def test_logging_instrument_simple() -> None:
    log_capture = LogCapture()
    logging_instrument = LoggingInstrument(
        bootstrap_config=LoggingConfig(
            logging_unset_handlers=["uvicorn"],
            logging_buffer_capacity=0,
            service_debug=False,
            logging_extra_processors=[log_capture],
        )
    )
    try:
        logging_instrument.bootstrap()

        logger = structlog.getLogger(__name__)
        logger.info("testing structlog", key="value")
        std_logger.info("testing std logger", extra={"key": "value"})
        try:
            msg = "some error"
            raise ValueError(msg)  # noqa: TRY301
        except ValueError:
            logger.exception("logging error")

        events_number = 2
        assert len(log_capture.entries) == events_number
    finally:
        logging_instrument.teardown()


def test_logging_instrument_tracer_injection() -> None:
    log_capture = LogCapture()
    logging_instrument = LoggingInstrument(
        bootstrap_config=LoggingConfig(
            logging_unset_handlers=["uvicorn"],
            logging_buffer_capacity=0,
            logging_extra_processors=[log_capture],
        )
    )
    opentelemetry_instrument = OpenTelemetryInstrument(
        bootstrap_config=OpentelemetryConfig(
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

        assert log_capture.entries[0]["event"] == "testing tracer injection without spans"

        assert log_capture.entries[1]["event"] == "testing tracer injection without span attributes"
        assert log_capture.entries[2]["event"] == "testing tracer injection with span attributes"

        tracing1 = log_capture.entries[1]["tracing"]
        tracing2 = log_capture.entries[2]["tracing"]
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
        logging_buffer_capacity=test_capacity,
        logging_flush_level=test_flush_level,
        logging_log_level=logging.INFO,
        log_stream=test_stream,
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
        logging_buffer_capacity=test_capacity,
        logging_flush_level=test_flush_level,
        logging_log_level=logging.INFO,
        log_stream=test_stream,
    )
    test_logger = logger_factory()
    error_message = "error message"
    test_logger.error(error_message)
    assert error_message in test_stream.getvalue()
