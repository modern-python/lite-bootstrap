# The structlog→Sentry seam is a value object, not a marker key or a shared module

**Decision:** `StructuredLogPayload` in `logging_factory.py` owns the parse of a rendered log line
and the meta-key vocabulary (`STRUCTLOG_META_KEYS`); `sentry_instrument.py` keeps only the
orchestration — drop on `skip_sentry`, lift `message`, attach `extra` under `contexts.structlog`.
The producer still emits a plain flat JSON object and the consumer still recognises one by
`startswith("{")`.

The problem being solved was ownership, not the heuristic: the meta-key set was duplicated across
the producer's processor chain and the consumer's strip list and owned by neither, so renaming a
meta-key silently degraded Sentry enrichment with nothing failing.

## Rejected alternatives

**Stamp an explicit sentinel/marker key on every log line** instead of sniffing `startswith("{")`.
This pollutes the stdout JSON shape for every logging user in order to serve one consumer. The
heuristic is cheap and adequate, and the log shape is user-visible output.

**A neutral third module both instruments import.** There is exactly one consumer. A
shared-for-sharing's-sake module abstracts a sharing that does not exist and pulls the vocabulary
away from the chain that generates it — the value object belongs next to the serializer that
produces what it parses.

**A symmetric `serialize()` on the value object.** The producer never constructs a
`StructuredLogPayload`; it hands structlog's full `event_dict` to the existing serializer. A
`serialize()` nobody calls would be dead surface.

**An absolute, compile-time drift fix.** Nesting user kwargs under a single `extra` key would make
drift impossible, and would change the emitted log shape for every user. The deliberate trade is
"unlikely and caught by a round-trip test" over "impossible and a breaking change": a custom
top-level meta-processor whose key is not added to `STRUCTLOG_META_KEYS` still leaks, and that is a
known, accepted limit.

**Deferring the render to `ProcessorFormatter.wrap_for_formatter`.** This is structlog's own
idiomatic stdlib integration, it is already what `_configure_foreign_loggers` uses ten lines away,
and it was the obvious fix for #193's double-rendered traceback. It is incompatible with this seam.
`wrap_for_formatter` moves rendering to handler-flush time, so `record.msg` is the `EventDict`
rather than a rendered line; `sentry_sdk` builds `logentry.formatted` from `record.getMessage()`,
which for a dict `msg` is a Python repr. That repr opens with `{`, so `StructuredLogPayload.parse`
accepts it, fails to decode it, and returns `None` — `skip_sentry` stops being honoured and
`contexts.structlog` stops being attached, with nothing failing. The seam requires that the line
be rendered before it becomes a `LogRecord`; anything downstream of the chain is transport only.

`IGNORED_STRUCTLOG_ATTRIBUTES` survives in `sentry_instrument.py` as a silent alias of
`STRUCTLOG_META_KEYS` for external importers of the old name.

**Revisit trigger:** a second consumer honours `skip_sentry` or needs the parsed payload. At that
point the value object has a real audience, `skip_sentry` should be renamed to something reporter-
neutral, and a marker key stops being a cost paid for one consumer.
