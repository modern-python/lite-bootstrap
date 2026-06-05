import copy
import logging
import typing
from unittest.mock import patch

import pytest
import sentry_sdk
import structlog

from lite_bootstrap.instruments.logging_instrument import LoggingConfig, LoggingInstrument
from tests.conftest import LoggingMock, SentryTestTransport


if typing.TYPE_CHECKING:
    from sentry_sdk import _types as sentry_types

from lite_bootstrap.instruments.sentry_instrument import (
    SentryConfig,
    SentryInstrument,
    enrich_sentry_event_from_structlog_log,
)


std_logger = logging.getLogger(__name__)
logger = structlog.getLogger(__name__)


@pytest.fixture
def minimal_sentry_config(sentry_mock: SentryTestTransport) -> SentryConfig:
    return SentryConfig(
        sentry_dsn="https://testdsn@localhost/1",
        sentry_tags={"test": "test"},
        sentry_additional_params={"transport": sentry_mock},
    )


def test_sentry_instrument_with_raise(minimal_sentry_config: SentryConfig, sentry_mock: SentryTestTransport) -> None:
    instrument = SentryInstrument(bootstrap_config=minimal_sentry_config)
    instrument.bootstrap()

    try:
        std_logger.error("some error")
        assert len(sentry_mock.mock_envelopes) == 1
    finally:
        instrument.teardown()


def test_sentry_instrument_with_structlog_error(
    minimal_sentry_config: SentryConfig, sentry_mock: SentryTestTransport, logging_mock: LoggingMock
) -> None:
    sentry_instrument = SentryInstrument(bootstrap_config=minimal_sentry_config)
    sentry_instrument.bootstrap()
    logging_instrument = LoggingInstrument(
        bootstrap_config=LoggingConfig(
            logging_unset_handlers=["uvicorn"],
            logging_buffer_capacity=0,
            service_debug=False,
            logging_extra_processors=[logging_mock],
        )
    )
    logging_instrument.bootstrap()

    try:
        logger.error("some error")
        logger.error("some error, skipping sentry", skip_sentry=True)
        assert len(sentry_mock.mock_envelopes) == 1
    finally:
        logging_instrument.teardown()
        sentry_instrument.teardown()


def test_sentry_teardown_disables_sdk(minimal_sentry_config: SentryConfig) -> None:
    instrument = SentryInstrument(bootstrap_config=minimal_sentry_config)
    instrument.bootstrap()
    assert sentry_sdk.get_client().dsn == minimal_sentry_config.sentry_dsn

    instrument.teardown()

    assert sentry_sdk.get_client().dsn is None


def test_sentry_instrument_empty_dsn() -> None:
    SentryInstrument(bootstrap_config=SentryConfig(sentry_dsn="")).bootstrap()


class TestSentryEnrichEventFromStructlog:
    @pytest.mark.parametrize(
        "event",
        [
            {},
            {"logentry": None},
            {"logentry": {}},
            {"logentry": {"formatted": b""}},
            {"logentry": {"formatted": ""}},
            {"logentry": {"formatted": "hi"}},
            {"logentry": {"formatted": "[]"}},
            {"logentry": {"formatted": "[{}]"}},
            {"logentry": {"formatted": "{"}, "contexts": {}},
            {"logentry": {"formatted": "{}"}, "contexts": {}},
        ],
    )
    def test_skip(self, event: "sentry_types.Event") -> None:
        assert enrich_sentry_event_from_structlog_log(copy.deepcopy(event), {}) == event

    @pytest.mark.parametrize(
        ("event_before", "event_after"),
        [
            (
                {"logentry": {"formatted": '{"event": "event name"}'}, "contexts": {}},
                {"logentry": {"formatted": "event name"}, "contexts": {}},
            ),
            (
                {
                    "logentry": {
                        "formatted": '{"event": "event name", "timestamp": 1, "level": "error", "logger": "event.logger", "tracing": {}, "foo": "bar"}'  # noqa: E501
                    },
                    "contexts": {},
                },
                {
                    "logentry": {"formatted": "event name"},
                    "contexts": {"structlog": {"foo": "bar"}},
                },
            ),
            (
                {
                    "logentry": {"formatted": '{"event": "event name", "skip_sentry": false, "foo": "bar"}'},
                    "contexts": {},
                },
                {
                    "logentry": {"formatted": "event name"},
                    "contexts": {"structlog": {"foo": "bar"}},
                },
            ),
        ],
    )
    def test_modify(self, event_before: "sentry_types.Event", event_after: "sentry_types.Event") -> None:
        assert enrich_sentry_event_from_structlog_log(event_before, {}) == event_after


def test_sentry_teardown_runs_init_when_flush_raises(minimal_sentry_config: SentryConfig) -> None:
    instrument = SentryInstrument(bootstrap_config=minimal_sentry_config)
    instrument.bootstrap()

    with (
        patch("sentry_sdk.flush", side_effect=RuntimeError("flush boom")),
        pytest.raises(RuntimeError, match="flush boom"),
    ):
        instrument.teardown()

    # init() still ran (in the finally), so SDK is now disabled.
    assert sentry_sdk.get_client().dsn is None
