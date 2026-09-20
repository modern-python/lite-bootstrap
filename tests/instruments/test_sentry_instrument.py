import copy
import dataclasses
import logging
import typing
from unittest.mock import patch

import pytest
import sentry_sdk
import structlog
from sentry_sdk.integrations.logging import LoggingIntegration

from lite_bootstrap.instruments import sentry_instrument
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
    """enrich_* owns the Sentry-event-shape guards and the orchestration branches.

    Line-content parsing (meta-stripping, skip detection, JSON guards) is the
    StructuredLogPayload.parse contract and is covered in test_structured_log_payload.py.
    """

    @pytest.mark.parametrize(
        "event",
        [
            {},  # no logentry
            {"logentry": {"formatted": b""}},  # formatted is not a str
            {"logentry": {"formatted": "hi"}, "contexts": {}},  # parse returns None (not a structlog line)
            {"logentry": {"formatted": "{}"}, "contexts": {}},  # parsed, but no `event` key -> no message
        ],
    )
    def test_passthrough_leaves_event_unmodified(self, event: "sentry_types.Event") -> None:
        assert enrich_sentry_event_from_structlog_log(copy.deepcopy(event), {}) == event

    def test_drops_event_on_skip_sentry_before_message_check(self) -> None:
        # Ordering pin: skip_sentry is honored before the message-presence check, so a
        # line with skip_sentry truthy and no `event` key still drops (returns None).
        event: sentry_types.Event = {"logentry": {"formatted": '{"skip_sentry": true}'}, "contexts": {}}
        assert enrich_sentry_event_from_structlog_log(event, {}) is None

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
        ],
    )
    def test_modify_lifts_message_and_attaches_extra(
        self, event_before: "sentry_types.Event", event_after: "sentry_types.Event"
    ) -> None:
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


def installed_logging_integration() -> LoggingIntegration:
    integration = sentry_sdk.get_client().integrations[LoggingIntegration.identifier]
    assert isinstance(integration, LoggingIntegration)
    return integration


def test_sentry_bootstrap_disables_the_sentry_logs_handler(minimal_sentry_config: SentryConfig) -> None:
    instrument = SentryInstrument(bootstrap_config=minimal_sentry_config)
    instrument.bootstrap()

    try:
        integration = installed_logging_integration()
        assert integration._sentry_logs_handler is None  # noqa: SLF001
        assert integration._breadcrumb_handler is not None  # noqa: SLF001
        assert integration._handler is not None  # noqa: SLF001
        assert minimal_sentry_config.sentry_integrations == []
    finally:
        instrument.teardown()


def test_sentry_bootstrap_keeps_a_user_supplied_logging_integration(minimal_sentry_config: SentryConfig) -> None:
    supplied = LoggingIntegration(sentry_logs_level=logging.INFO)
    bootstrap_config = dataclasses.replace(minimal_sentry_config, sentry_integrations=[supplied])
    instrument = SentryInstrument(bootstrap_config=bootstrap_config)
    instrument.bootstrap()

    try:
        assert sentry_sdk.get_client().integrations[LoggingIntegration.identifier] is supplied
    finally:
        instrument.teardown()


def test_sentry_bootstrap_adds_no_logging_integration_without_default_integrations(
    minimal_sentry_config: SentryConfig,
) -> None:
    bootstrap_config = dataclasses.replace(minimal_sentry_config, sentry_default_integrations=False)
    instrument = SentryInstrument(bootstrap_config=bootstrap_config)
    instrument.bootstrap()

    try:
        assert LoggingIntegration.identifier not in sentry_sdk.get_client().integrations
    finally:
        instrument.teardown()


@pytest.mark.parametrize("breadcrumb_level", [logging.INFO, None], ids=["info", "disabled"])
def test_sentry_logging_breadcrumb_level_controls_the_breadcrumb_handler(
    minimal_sentry_config: SentryConfig, breadcrumb_level: int | None
) -> None:
    bootstrap_config = dataclasses.replace(minimal_sentry_config, sentry_logging_breadcrumb_level=breadcrumb_level)
    instrument = SentryInstrument(bootstrap_config=bootstrap_config)
    instrument.bootstrap()

    try:
        integration = installed_logging_integration()
        assert (integration._breadcrumb_handler is None) is (breadcrumb_level is None)  # noqa: SLF001
    finally:
        instrument.teardown()


@pytest.mark.parametrize("auto_session_tracking", [True, False], ids=["on", "off"])
def test_sentry_auto_session_tracking_reaches_the_client(
    minimal_sentry_config: SentryConfig, auto_session_tracking: bool
) -> None:
    bootstrap_config = dataclasses.replace(minimal_sentry_config, sentry_auto_session_tracking=auto_session_tracking)
    instrument = SentryInstrument(bootstrap_config=bootstrap_config)
    instrument.bootstrap()

    try:
        assert sentry_sdk.get_client().options["auto_session_tracking"] is auto_session_tracking
    finally:
        instrument.teardown()


def test_sentry_additional_params_override_the_explicit_init_params(minimal_sentry_config: SentryConfig) -> None:
    bootstrap_config = dataclasses.replace(
        minimal_sentry_config,
        sentry_auto_session_tracking=True,
        sentry_additional_params={
            **minimal_sentry_config.sentry_additional_params,
            "auto_session_tracking": False,
        },
    )
    instrument = SentryInstrument(bootstrap_config=bootstrap_config)
    instrument.bootstrap()

    try:
        assert sentry_sdk.get_client().options["auto_session_tracking"] is False
    finally:
        instrument.teardown()


@pytest.mark.parametrize(
    ("overrides", "expected_reason"),
    [
        ({"sentry_integrations": [LoggingIntegration()]}, "already supplies a LoggingIntegration"),
        ({"sentry_default_integrations": False}, "sentry_default_integrations is False"),
    ],
    ids=["user_integration", "no_default_integrations"],
)
def test_sentry_warns_when_the_breadcrumb_level_is_ignored(
    minimal_sentry_config: SentryConfig, overrides: dict[str, typing.Any], expected_reason: str
) -> None:
    bootstrap_config = dataclasses.replace(minimal_sentry_config, sentry_logging_breadcrumb_level=None, **overrides)
    instrument = SentryInstrument(bootstrap_config=bootstrap_config)

    with pytest.warns(UserWarning, match=expected_reason):
        instrument.bootstrap()
    instrument.teardown()


def test_sentry_does_not_warn_when_the_breadcrumb_level_is_left_at_its_default(
    minimal_sentry_config: SentryConfig, recwarn: pytest.WarningsRecorder
) -> None:
    bootstrap_config = dataclasses.replace(minimal_sentry_config, sentry_integrations=[LoggingIntegration()])
    instrument = SentryInstrument(bootstrap_config=bootstrap_config)
    instrument.bootstrap()

    try:
        assert [one for one in recwarn if "sentry_logging_breadcrumb_level" in str(one.message)] == []
    finally:
        instrument.teardown()


@pytest.mark.parametrize("supported", [True, False], ids=["sdk_has_it", "sdk_lacks_it"])
def test_sentry_passes_sentry_logs_level_only_when_the_sdk_accepts_it(
    minimal_sentry_config: SentryConfig, monkeypatch: pytest.MonkeyPatch, supported: bool
) -> None:
    """INVARIANT: `sentry_logs_level` reaches only the sentry-sdk versions that accept it.

    It arrived in sentry-sdk 2.25 while the declared floor is 2.1, where passing it raises
    `TypeError: LoggingIntegration.__init__() got an unexpected keyword argument` at bootstrap.
    Below 2.25 there is no Sentry Logs feature, so there is no handler to disable either.
    """
    monkeypatch.setattr(sentry_instrument, "SENTRY_LOGS_LEVEL_SUPPORTED", supported)
    integrations = SentryInstrument(bootstrap_config=minimal_sentry_config)._build_integrations()  # noqa: SLF001

    logging_integration = next(one for one in integrations if isinstance(one, LoggingIntegration))
    assert (logging_integration._sentry_logs_handler is None) is supported  # noqa: SLF001
