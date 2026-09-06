from lite_bootstrap.instruments.logging_factory import (
    STRUCTLOG_META_KEYS,
    StructuredLogPayload,
    _dumps_orjson,
    _dumps_stdlib,
    _serialize_log_to_string,
)


def test_parse_normal_line_lifts_message_and_strips_meta() -> None:
    formatted = (
        '{"event": "hello", "level": "info", "logger": "app", "timestamp": "2026-06-23T00:00:00Z", "foo": "bar"}'
    )

    payload = StructuredLogPayload.parse(formatted)

    assert payload is not None
    assert payload.message == "hello"
    assert payload.extra == {"foo": "bar"}
    assert payload.skip_sentry is False


def test_parse_non_json_line_returns_none() -> None:
    assert StructuredLogPayload.parse("plain text message") is None


def test_parse_non_object_json_returns_none() -> None:
    assert StructuredLogPayload.parse("[1, 2, 3]") is None


def test_parse_malformed_json_object_returns_none() -> None:
    assert StructuredLogPayload.parse('{"event": ') is None


def test_parse_line_without_event_has_no_message() -> None:
    payload = StructuredLogPayload.parse('{"level": "info", "foo": "bar"}')

    assert payload is not None
    assert payload.message is None
    assert payload.extra == {"foo": "bar"}


def test_parse_truthy_skip_sentry_sets_flag() -> None:
    payload = StructuredLogPayload.parse('{"event": "drop me", "skip_sentry": true}')

    assert payload is not None
    assert payload.skip_sentry is True


def test_parse_falsy_skip_sentry_is_stripped_from_extra() -> None:
    # A falsy skip_sentry flag must not leak into extra; it is a meta-key,
    # stripped regardless of value.
    payload = StructuredLogPayload.parse('{"event": "keep", "skip_sentry": false, "foo": "bar"}')

    assert payload is not None
    assert payload.skip_sentry is False
    assert payload.extra == {"foo": "bar"}


def test_round_trip_through_real_serializer_strips_every_meta_key() -> None:
    # Drift net: a representative event_dict the producer's structlog chain emits,
    # serialized by the real serializer and parsed back. If a meta-key the chain
    # emits is missing from STRUCTLOG_META_KEYS, it leaks into extra and this fails.
    event_dict = {
        "event": "request handled",
        "level": "info",
        "logger": "app.api",
        "tracing": {"span_id": "abc", "trace_id": "def"},
        "timestamp": "2026-06-23T00:00:00Z",
        "skip_sentry": False,
        "user_id": 42,
        "path": "/health",
    }

    formatted = _serialize_log_to_string(event_dict)
    payload = StructuredLogPayload.parse(formatted)

    assert payload is not None
    assert payload.message == "request handled"
    assert payload.extra == {"user_id": 42, "path": "/health"}
    assert not (payload.extra.keys() & STRUCTLOG_META_KEYS)


def test_dumps_stdlib_matches_orjson_output() -> None:
    event = {"event": "hello café", "level": "info", "n": 1, "ok": True, "nested": {"a": [1, 2]}}
    assert _dumps_stdlib(event) == _dumps_orjson(event)


def test_dumps_stdlib_is_compact_utf8() -> None:
    assert _dumps_stdlib({"k": "café", "n": 1}) == '{"k":"café","n":1}'


def test_parse_round_trips_under_active_loader() -> None:
    formatted = _serialize_log_to_string({"event": "hi", "level": "info", "x": 1})
    payload = StructuredLogPayload.parse(formatted)
    assert payload is not None
    assert payload.message == "hi"
    assert payload.extra == {"x": 1}
