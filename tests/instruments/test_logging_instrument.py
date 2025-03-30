import logging
from io import StringIO

import structlog
from opentelemetry.sdk.trace.export import ConsoleSpanExporter
from opentelemetry.trace import get_tracer

from lite_bootstrap.instruments.logging_instrument import LoggingConfig, LoggingInstrument, MemoryLoggerFactory
from lite_bootstrap.instruments.opentelemetry_instrument import OpentelemetryConfig, OpenTelemetryInstrument


logger = structlog.getLogger(__name__)


def test_logging_instrument() -> None:
    logging_instrument = LoggingInstrument(
        bootstrap_config=LoggingConfig(logging_unset_handlers=["uvicorn"], logging_buffer_capacity=0)
    )
    try:
        logging_instrument.bootstrap()
        logger.info("testing logging", key="value")
    finally:
        logging_instrument.teardown()


def test_logging_instrument_tracer_injection() -> None:
    logging_instrument = LoggingInstrument(
        bootstrap_config=LoggingConfig(logging_unset_handlers=["uvicorn"], logging_buffer_capacity=0)
    )
    opentelemetry_instrument = OpenTelemetryInstrument(
        bootstrap_config=OpentelemetryConfig(
            opentelemetry_endpoint="otl",
            opentelemetry_span_exporter=ConsoleSpanExporter(),
        )
    )
    try:
        logging_instrument.bootstrap()
        opentelemetry_instrument.bootstrap()
        tracer = get_tracer(__name__)
        logger.info("testing tracer injection without spans")
        with tracer.start_as_current_span("my_fake_span") as span:
            logger.info("testing tracer injection without span attributes")
            span.set_attribute("example_attribute", "value")
            span.add_event("example_event", {"event_attr": 1})
            logger.info("testing tracer injection with span attributes")
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
