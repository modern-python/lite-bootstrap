import copy
import dataclasses
import json
import logging
import typing
import uuid
from unittest.mock import patch

import pytest
import sentry_sdk
import structlog
from sentry_sdk.integrations.logging import LoggingIntegration

from lite_bootstrap.instruments.logging_instrument import LoggingConfig, LoggingInstrument
from lite_bootstrap.instruments.sentry_instrument import enrich_sentry_event_from_structlog_log
from tests.conftest import LoggingMock, SentryTestTransport


if typing.TYPE_CHECKING:
    from sentry_sdk import _types as sentry_types

from lite_bootstrap.instruments.sentry_instrument import (
    SentryConfig,
    SentryInstrument,
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


def test_sentry_teardown_disables_sdk(
    minimal_sentry_config: SentryConfig, sentry_mock: SentryTestTransport, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SENTRY_DSN", "https://synthetic@example.invalid/1")
    monkeypatch.setattr("sentry_sdk.client.make_transport", lambda options: sentry_mock if options["dsn"] else None)
    instrument = SentryInstrument(bootstrap_config=minimal_sentry_config)
    instrument.bootstrap()
    assert sentry_sdk.get_client().dsn == minimal_sentry_config.sentry_dsn

    instrument.teardown()

    assert not sentry_sdk.get_client().is_active()
    assert sentry_sdk.capture_message("after teardown") is None
    assert sentry_mock.mock_envelopes == []


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
                {"logentry": {"formatted": "event name", "message": "event name", "params": []}, "contexts": {}},
            ),
            (
                {
                    "logentry": {
                        "formatted": '{"event": "event name", "timestamp": 1, "level": "error", "logger": "event.logger", "tracing": {}, "foo": "bar"}'  # noqa: E501
                    },
                    "contexts": {},
                },
                {
                    "logentry": {"formatted": "event name", "message": "event name", "params": []},
                    "contexts": {"structlog": {"foo": "bar"}},
                },
            ),
        ],
    )
    def test_modify_lifts_message_and_attaches_extra(
        self, event_before: "sentry_types.Event", event_after: "sentry_types.Event"
    ) -> None:
        assert enrich_sentry_event_from_structlog_log(event_before, {}) == event_after


def test_sentry_teardown_disables_sdk_when_flush_raises(
    minimal_sentry_config: SentryConfig, sentry_mock: SentryTestTransport, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SENTRY_DSN", "https://synthetic@example.invalid/1")
    monkeypatch.setattr("sentry_sdk.client.make_transport", lambda options: sentry_mock if options["dsn"] else None)
    instrument = SentryInstrument(bootstrap_config=minimal_sentry_config)
    instrument.bootstrap()

    with (
        patch("sentry_sdk.flush", side_effect=RuntimeError("flush boom")),
        pytest.raises(RuntimeError, match="flush boom"),
    ):
        instrument.teardown()

    assert not sentry_sdk.get_client().is_active()
    assert sentry_sdk.capture_message("after teardown") is None
    assert sentry_mock.mock_envelopes == []


def installed_logging_integration() -> LoggingIntegration:
    integration = sentry_sdk.get_client().integrations[LoggingIntegration.identifier]
    assert isinstance(integration, LoggingIntegration)
    return integration


def test_sentry_bootstrap_turns_error_logs_into_events_and_sends_no_sentry_logs(
    minimal_sentry_config: SentryConfig, sentry_mock: SentryTestTransport, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger=std_logger.name)
    instrument = SentryInstrument(bootstrap_config=minimal_sentry_config)
    instrument.bootstrap()

    try:
        std_logger.info("some info")
        std_logger.error("some error")
        sentry_sdk.flush()
        assert [item.type for envelope in sentry_mock.mock_envelopes for item in envelope.items] == ["event"]
    finally:
        instrument.teardown()


def raise_with_secret_locals() -> None:
    password = "hunter2"  # noqa: S105
    api_token = "abc123"  # noqa: S105
    raise RuntimeError(len(password) + len(api_token))


def test_sentry_filters_secret_stack_frame_variables(
    minimal_sentry_config: SentryConfig, sentry_mock: SentryTestTransport
) -> None:
    instrument = SentryInstrument(bootstrap_config=minimal_sentry_config)
    instrument.bootstrap()

    try:
        try:
            raise_with_secret_locals()
        except RuntimeError:
            sentry_sdk.capture_exception()
        event = sentry_mock.mock_envelopes[0].get_event()
        assert event is not None
        frame_vars = event["exception"]["values"][0]["stacktrace"]["frames"][-1]["vars"]
        assert {frame_vars["password"], frame_vars["api_token"]} == {repr("[Filtered]")}
    finally:
        instrument.teardown()


def test_sentry_collects_no_user_info_or_http_bodies_by_default(minimal_sentry_config: SentryConfig) -> None:
    instrument = SentryInstrument(bootstrap_config=minimal_sentry_config)
    instrument.bootstrap()

    try:
        data_collection = sentry_sdk.get_client().options["data_collection"]
        assert data_collection["user_info"] is False
        assert data_collection["http_bodies"] == []
    finally:
        instrument.teardown()


def test_sentry_additional_params_data_collection_replaces_the_default(minimal_sentry_config: SentryConfig) -> None:
    bootstrap_config = dataclasses.replace(
        minimal_sentry_config,
        sentry_additional_params={**minimal_sentry_config.sentry_additional_params, "data_collection": {}},
    )
    instrument = SentryInstrument(bootstrap_config=bootstrap_config)
    instrument.bootstrap()

    try:
        assert sentry_sdk.get_client().options["data_collection"]["user_info"] is True
    finally:
        instrument.teardown()


def test_sentry_bootstrap_keeps_a_user_supplied_logging_integration(minimal_sentry_config: SentryConfig) -> None:
    supplied = LoggingIntegration()
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


@pytest.mark.parametrize("breadcrumb_level", [logging.INFO, logging.WARNING, None], ids=["info", "warning", "disabled"])
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


def test_sentry_breadcrumbs_start_at_warning_by_default(minimal_sentry_config: SentryConfig) -> None:
    instrument = SentryInstrument(bootstrap_config=minimal_sentry_config)
    instrument.bootstrap()

    try:
        breadcrumb_handler = installed_logging_integration()._breadcrumb_handler  # noqa: SLF001
        assert breadcrumb_handler is not None
        assert breadcrumb_handler.level == logging.WARNING
    finally:
        instrument.teardown()


def test_sentry_error_event_carries_no_info_breadcrumbs_by_default(
    minimal_sentry_config: SentryConfig, sentry_mock: SentryTestTransport, caplog: pytest.LogCaptureFixture
) -> None:
    probe_logger = logging.getLogger("breadcrumb_probe")
    caplog.set_level(logging.INFO, logger=probe_logger.name)
    instrument = SentryInstrument(bootstrap_config=minimal_sentry_config)
    instrument.bootstrap()

    try:
        probe_logger.info("an info record")
        probe_logger.warning("a warning record")
        probe_logger.error("some error")
        event = sentry_mock.mock_envelopes[0].get_event()
        assert event is not None
        breadcrumbs = event["breadcrumbs"]
        assert isinstance(breadcrumbs, dict)
        probe_crumbs = [crumb for crumb in breadcrumbs["values"] if crumb.get("category") == probe_logger.name]
        assert [crumb["message"] for crumb in probe_crumbs] == ["a warning record"]
    finally:
        instrument.teardown()


def test_sentry_does_not_track_sessions_by_default(minimal_sentry_config: SentryConfig) -> None:
    instrument = SentryInstrument(bootstrap_config=minimal_sentry_config)
    instrument.bootstrap()

    try:
        assert sentry_sdk.get_client().options["auto_session_tracking"] is False
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


def test_sentry_warns_when_a_non_default_info_breadcrumb_level_is_ignored(minimal_sentry_config: SentryConfig) -> None:
    bootstrap_config = dataclasses.replace(
        minimal_sentry_config, sentry_logging_breadcrumb_level=logging.INFO, sentry_default_integrations=False
    )
    instrument = SentryInstrument(bootstrap_config=bootstrap_config)

    with pytest.warns(UserWarning, match="sentry_default_integrations is False"):
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


_AUTO_ENABLED_IN_THE_TEST_ENVIRONMENT: typing.Final = frozenset({"aiohttp", "httpx", "redis"})


def _active_integrations(bootstrap_config: SentryConfig) -> set[str]:
    instrument = SentryInstrument(bootstrap_config=bootstrap_config)
    instrument.bootstrap()
    try:
        return set(sentry_sdk.get_client().integrations)
    finally:
        instrument.teardown()


def test_sentry_leaves_auto_enabling_integrations_off_while_tracing_is_off(
    minimal_sentry_config: SentryConfig,
) -> None:
    active = _active_integrations(minimal_sentry_config)

    assert not _AUTO_ENABLED_IN_THE_TEST_ENVIRONMENT & active
    assert "logging" in active


@pytest.mark.parametrize(
    "tracing_overrides",
    [
        pytest.param({"sentry_traces_sample_rate": 0.0}, id="sentry_traces_sample_rate"),
        pytest.param({"sentry_additional_params": {"traces_sample_rate": 0.5}}, id="traces_sample_rate"),
        pytest.param({"sentry_additional_params": {"traces_sampler": lambda _: 0.5}}, id="traces_sampler"),
    ],
)
def test_sentry_keeps_auto_enabling_integrations_while_tracing_is_on(
    minimal_sentry_config: SentryConfig, tracing_overrides: dict[str, typing.Any]
) -> None:
    additional_params = {
        **minimal_sentry_config.sentry_additional_params,
        **tracing_overrides.pop("sentry_additional_params", {}),
    }
    bootstrap_config = dataclasses.replace(
        minimal_sentry_config, sentry_additional_params=additional_params, **tracing_overrides
    )

    assert _active_integrations(bootstrap_config) >= _AUTO_ENABLED_IN_THE_TEST_ENVIRONMENT


@pytest.mark.parametrize(
    ("auto_enabling_integrations", "traces_sample_rate", "expected"),
    [
        pytest.param(True, None, True, id="on-while-tracing-is-off"),
        pytest.param(False, 1.0, False, id="off-while-tracing-is-on"),
    ],
)
def test_sentry_auto_enabling_integrations_set_explicitly_wins(
    minimal_sentry_config: SentryConfig,
    auto_enabling_integrations: bool,
    traces_sample_rate: float | None,
    expected: bool,
) -> None:
    bootstrap_config = dataclasses.replace(
        minimal_sentry_config,
        sentry_auto_enabling_integrations=auto_enabling_integrations,
        sentry_traces_sample_rate=traces_sample_rate,
    )
    instrument = SentryInstrument(bootstrap_config=bootstrap_config)
    instrument.bootstrap()

    try:
        assert sentry_sdk.get_client().options["auto_enabling_integrations"] is expected
    finally:
        instrument.teardown()


def test_sentry_additional_params_auto_enabling_integrations_wins_over_the_field(
    minimal_sentry_config: SentryConfig,
) -> None:
    bootstrap_config = dataclasses.replace(
        minimal_sentry_config,
        sentry_auto_enabling_integrations=False,
        sentry_additional_params={**minimal_sentry_config.sentry_additional_params, "auto_enabling_integrations": True},
    )

    assert _active_integrations(bootstrap_config) >= _AUTO_ENABLED_IN_THE_TEST_ENVIRONMENT


@pytest.mark.parametrize(
    ("service_version", "sentry_release_env", "expected_release"),
    [
        pytest.param("2.3.4", None, "2.3.4", id="service-version"),
        pytest.param("2.3.4", "from-env", "2.3.4", id="service-version-wins-over-env"),
        pytest.param(None, "from-env", "from-env", id="env-when-unset"),
    ],
)
def test_sentry_release_follows_service_version(
    monkeypatch: pytest.MonkeyPatch,
    minimal_sentry_config: SentryConfig,
    service_version: str | None,
    sentry_release_env: str | None,
    expected_release: str,
) -> None:
    if sentry_release_env is None:
        monkeypatch.delenv("SENTRY_RELEASE", raising=False)
    else:
        monkeypatch.setenv("SENTRY_RELEASE", sentry_release_env)
    config = minimal_sentry_config
    if service_version is not None:
        config = dataclasses.replace(config, service_version=service_version)
    instrument = SentryInstrument(bootstrap_config=config)
    instrument.bootstrap()

    try:
        assert sentry_sdk.get_client().options["release"] == expected_release
    finally:
        instrument.teardown()


@pytest.mark.parametrize("attach_stacktrace", [False, True])
def test_structlog_envelope_redacts_kwargs_and_excludes_skipped_breadcrumbs(
    minimal_sentry_config: SentryConfig, sentry_mock: SentryTestTransport, *, attach_stacktrace: bool
) -> None:
    def before_breadcrumb(
        crumb: "sentry_types.Breadcrumb", _: "sentry_types.BreadcrumbHint"
    ) -> "sentry_types.Breadcrumb | None":
        if crumb.get("message") == "dropped by hook":
            return None
        return crumb

    def before_send(event: "sentry_types.Event", _: "sentry_types.Hint") -> "sentry_types.Event":
        event.setdefault("tags", {})["hook"] = "called"
        return event

    config = dataclasses.replace(
        minimal_sentry_config,
        sentry_attach_stacktrace=attach_stacktrace,
        sentry_additional_params={
            **minimal_sentry_config.sentry_additional_params,
            "before_breadcrumb": before_breadcrumb,
            "before_send": before_send,
        },
    )
    sentry = SentryInstrument(bootstrap_config=config)
    logs = LoggingInstrument(bootstrap_config=LoggingConfig())
    sentry.bootstrap()
    logs.bootstrap()
    try:
        marker = uuid.uuid4().hex
        skipped = uuid.uuid4().hex
        logger.warning("breadcrumb", password=marker, component="worker")
        logger.warning(skipped, skip_sentry=True)
        std_logger.warning("dropped by hook")
        logger.error("error", password=marker, component="worker")
        logger.error("error", component="other-worker")
        logger.error("")
        first, repeated, second = sentry_mock.mock_envelopes
        for envelope in sentry_mock.mock_envelopes:
            assert marker.encode() not in envelope.serialize()
            assert skipped.encode() not in envelope.serialize()
        event = first.get_event()
        assert event is not None
        assert ("threads" in event) == attach_stacktrace
        repeated_event = repeated.get_event()
        assert repeated_event is not None
        assert repeated_event["logentry"] == event["logentry"]
        assert event["tags"]["hook"] == "called"
        assert event["logentry"] == {"message": "error", "formatted": "error", "params": []}
        assert event["contexts"]["structlog"]["component"] == "worker"
        breadcrumbs = event["breadcrumbs"]
        assert isinstance(breadcrumbs, dict)
        assert not any(crumb.get("message") == "dropped by hook" for crumb in breadcrumbs["values"])
        assert any(crumb.get("data", {}).get("component") == "worker" for crumb in breadcrumbs["values"])
        empty = second.get_event()
        assert empty is not None
        assert empty["logentry"] == {"message": "", "formatted": "", "params": []}
    finally:
        logs.teardown()
        sentry.teardown()


@pytest.mark.parametrize("attach_stacktrace", [False, True])
def test_structlog_stored_exception_reaches_sentry_and_stdout(
    minimal_sentry_config: SentryConfig,
    sentry_mock: SentryTestTransport,
    capsys: pytest.CaptureFixture[str],
    *,
    attach_stacktrace: bool,
) -> None:
    config = dataclasses.replace(minimal_sentry_config, sentry_attach_stacktrace=attach_stacktrace)
    sentry = SentryInstrument(bootstrap_config=config)
    logs = LoggingInstrument(bootstrap_config=LoggingConfig())
    sentry.bootstrap()
    logs.bootstrap()
    try:
        try:
            int("original stored error")
        except ValueError as exc:
            stored = exc

        marker = uuid.uuid4().hex
        padding = "x" * config.sentry_max_value_length
        logger.error("stored exception", exc_info=stored, component="worker", password=marker, padding=padding)

        line = json.loads(capsys.readouterr().out.splitlines()[-1])
        assert line["password"] == marker
        assert line["padding"] == padding
        assert "Traceback (most recent call last)" in line["exception"]
        assert "ValueError: invalid literal for int() with base 10: 'original stored error'" in line["exception"]
        envelope = sentry_mock.mock_envelopes[0]
        assert marker.encode() not in envelope.serialize()
        event = envelope.get_event()
        assert event is not None
        (exception,) = event["exception"]["values"]
        assert exception["type"] == "ValueError"
        assert exception["value"] == "invalid literal for int() with base 10: 'original stored error'"
        assert exception["stacktrace"]["frames"][-1]["function"] == (
            "test_structlog_stored_exception_reaches_sentry_and_stdout"
        )
        assert event["contexts"]["structlog"]["component"] == "worker"
        assert event["contexts"]["structlog"]["password"] == "[Filtered]"  # noqa: S105
    finally:
        logs.teardown()
        sentry.teardown()


@pytest.mark.parametrize("attach_stacktrace", [False, True])
@pytest.mark.parametrize("oversized", [False, True])
def test_structlog_envelope_privacy_across_string_limit(
    minimal_sentry_config: SentryConfig,
    sentry_mock: SentryTestTransport,
    capsys: pytest.CaptureFixture[str],
    *,
    attach_stacktrace: bool,
    oversized: bool,
) -> None:
    limit = 1024
    marker = uuid.uuid4().hex
    padding = "x" * (limit + 1 if oversized else limit - 256)
    callback_events: list[sentry_types.Event] = []

    def before_send(event: "sentry_types.Event", _: "sentry_types.Hint") -> "sentry_types.Event":
        callback_events.append(copy.deepcopy(event))
        return event

    config = dataclasses.replace(
        minimal_sentry_config,
        sentry_max_value_length=limit,
        sentry_attach_stacktrace=attach_stacktrace,
        sentry_before_send=before_send,
    )
    sentry = SentryInstrument(bootstrap_config=config)
    logs = LoggingInstrument(bootstrap_config=LoggingConfig())
    sentry.bootstrap()
    logs.bootstrap()
    try:
        logger.error("failure", password=marker, padding=padding)
        logger.error("suppressed", password=marker, padding=padding, skip_sentry=True)

        lines = capsys.readouterr().out.splitlines()
        expected_lines = 2
        assert len(lines) == expected_lines
        for line in lines:
            assert (len(line) > limit) == oversized
            rendered = json.loads(line)
            assert rendered["password"] == marker
            assert rendered["padding"] == padding
        assert json.loads(lines[1])["skip_sentry"] is True
        (envelope,) = sentry_mock.mock_envelopes
        assert marker.encode() not in envelope.serialize()
        (event,) = callback_events
        assert event["logentry"] == {"message": "failure", "formatted": "failure", "params": []}
        assert event["contexts"]["structlog"]["password"] == "[Filtered]"  # noqa: S105
        assert ("threads" in event) == attach_stacktrace
    finally:
        logs.teardown()
        sentry.teardown()


def test_message_less_structlog_error_is_scrubbed_in_sentry_envelopes(
    minimal_sentry_config: SentryConfig, sentry_mock: SentryTestTransport, capsys: pytest.CaptureFixture[str]
) -> None:
    marker = uuid.uuid4().hex
    sentry = SentryInstrument(bootstrap_config=minimal_sentry_config)
    logs = LoggingInstrument(bootstrap_config=LoggingConfig())
    sentry.bootstrap()
    logs.bootstrap()
    try:
        logger.error(password=marker, component="worker")
        logger.error("later error")

        first_line, second_line = map(json.loads, capsys.readouterr().out.splitlines())
        assert "event" not in first_line
        assert first_line["password"] == marker
        assert first_line["component"] == "worker"
        assert second_line["event"] == "later error"

        first, second = sentry_mock.mock_envelopes
        assert marker.encode() not in first.serialize()
        assert marker.encode() not in second.serialize()
        first_event = first.get_event()
        assert first_event is not None
        assert first_event["contexts"]["structlog"]["component"] == "worker"
        second_event = second.get_event()
        assert second_event is not None
        assert second_event["logentry"]["message"] == "later error"
        breadcrumbs = second_event["breadcrumbs"]
        assert isinstance(breadcrumbs, dict)
        assert any(crumb.get("data", {}).get("component") == "worker" for crumb in breadcrumbs["values"])
    finally:
        logs.teardown()
        sentry.teardown()


@pytest.mark.parametrize("template", ["plain %s", "{invalid %s", '{"unrelated":"%s"}'])
def test_unstructured_log_keeps_sdk_truncation(
    minimal_sentry_config: SentryConfig, sentry_mock: SentryTestTransport, template: str
) -> None:
    limit = 256
    config = dataclasses.replace(minimal_sentry_config, sentry_max_value_length=limit)
    sentry = SentryInstrument(bootstrap_config=config)
    sentry.bootstrap()
    try:
        std_logger.error(template, "x" * (limit * 2))
        (envelope,) = sentry_mock.mock_envelopes
        event = envelope.get_event()
        assert event is not None
        formatted = event["logentry"]["formatted"]
        assert isinstance(formatted, str)
        assert len(formatted) <= limit
        assert event["logentry"]["message"] == template
        assert "structlog" not in event["contexts"]
    finally:
        sentry.teardown()
