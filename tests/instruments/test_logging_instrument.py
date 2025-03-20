import logging
from io import StringIO

import structlog
from opentelemetry.sdk.trace.export import ConsoleSpanExporter
from opentelemetry.trace import get_tracer

from lite_bootstrap.instruments.logging_instrument import LoggingInstrument, MemoryLoggerFactory
from lite_bootstrap.instruments.opentelemetry_instrument import OpenTelemetryInstrument
from lite_bootstrap.service_config import ServiceConfig


logger = structlog.getLogger(__name__)


def test_logging_instrument(service_config: ServiceConfig) -> None:
    logging_instrument = LoggingInstrument(logging_unset_handlers=["uvicorn"], logging_buffer_capacity=0)
    try:
        logging_instrument.bootstrap(service_config)
        logger.info("testing logging", key="value")
    finally:
        logging_instrument.teardown()


def test_logging_instrument_tracer_injection(service_config: ServiceConfig) -> None:
    logging_instrument = LoggingInstrument(logging_unset_handlers=["uvicorn"], logging_buffer_capacity=0)
    opentelemetry_instrument = OpenTelemetryInstrument(
        endpoint="otl",
        span_exporter=ConsoleSpanExporter(),
    )
    try:
        logging_instrument.bootstrap(service_config)
        opentelemetry_instrument.bootstrap(service_config)
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
