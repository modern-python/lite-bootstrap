# The structlog→Sentry seam is a value object, not a marker key

`StructuredLogPayload` in `logging_factory.py` owns both the parse of a rendered log line and the
meta-key vocabulary (`STRUCTLOG_META_KEYS`), leaving `sentry_instrument.py` only the orchestration.
The problem solved was ownership, not the heuristic: the meta-key set was duplicated across the
producer's processor chain and the consumer's strip list and owned by neither, so renaming a meta-key
silently degraded Sentry enrichment. The producer still emits flat JSON and the consumer still
recognises it by `startswith("{")` — an explicit marker key would pollute user-visible stdout for
every logging user to serve one consumer, and a neutral third module both instruments import would
abstract a sharing that does not exist.

The trap worth knowing before "fixing" it: structlog's own idiomatic
`ProcessorFormatter.wrap_for_formatter` is incompatible with this seam. It defers rendering to
handler-flush time, so `record.msg` is an `EventDict`, `sentry_sdk` builds `logentry.formatted` from
`record.getMessage()`, and the resulting Python repr opens with `{` — which the parser accepts, fails
to decode, and returns `None` from, silently dropping both `skip_sentry` and `contexts.structlog`.
The seam requires the line to be rendered before it becomes a `LogRecord`.

A known accepted limit: a custom top-level meta-processor whose key is not added to
`STRUCTLOG_META_KEYS` still leaks into the payload. Nesting user kwargs under one `extra` key would
make that impossible, at the cost of changing the emitted log shape for every user; a round-trip test
is the trade taken instead.
