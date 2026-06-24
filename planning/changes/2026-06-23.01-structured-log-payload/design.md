---
status: approved
date: 2026-06-23
slug: structured-log-payload
summary: Move the structlog→Sentry log-line contract into a StructuredLogPayload value object so the meta-key vocabulary and parse live in one place, closing the silent-drift failure mode.
supersedes: null
superseded_by: null
pr: null
outcome: null
---

# Design: Give the structlog→Sentry payload a deep module

## Summary

The structlog→Sentry enrichment relies on a contract that no module owns: the
logging instrument renders every log line to a flat JSON object, and the Sentry
instrument opportunistically sniffs that shape (`formatted.startswith("{")`),
re-parses it, and strips a hand-maintained set of meta-keys before attaching the
rest to the Sentry event. This change introduces a `StructuredLogPayload` value
object in `logging_factory.py` that owns the parse + the meta-key vocabulary, so
the fragile knowledge lives in one place and the Sentry instrument shrinks to
orchestration. The goal is to close a silent-drift failure mode, not to abstract
for its own sake.

## Motivation

The log-event contract is split across two files and joined only by a string
guess:

- **Producer** (`logging_instrument.py:116`): the structlog processor chain ends
  in `JSONRenderer(serializer=_serialize_log_with_orjson_to_string)`. Every line
  is a flat JSON object — message under `event`, meta-keys `level` / `logger` /
  `tracing` / `timestamp` / `exception`, user kwargs, and an optional
  `skip_sentry`.
- **Consumer** (`sentry_instrument.py:39-71`): `enrich_sentry_event_from_structlog_log`
  sniffs `formatted.startswith("{")`, `orjson.loads` it, drops on `skip_sentry`,
  lifts `event` to the message, and strips `IGNORED_STRUCTLOG_ATTRIBUTES`
  (`sentry_instrument.py:19`) — the same meta-key set the producer emits — before
  attaching the remainder as `contexts.structlog`.

The coupling is one-directional and opportunistic: the producer does not know
Sentry exists; Sentry guesses at structlog's output shape. The meta-key
vocabulary is duplicated/implied across both files and owned by neither. Rename a
meta-key or add a top-level meta-processor without updating
`IGNORED_STRUCTLOG_ATTRIBUTES` and the enrichment silently degrades — either the
key leaks into `contexts.structlog`, or (for a renamed message key) the event
passes through unmodified. There is no test that crosses the producer's
serializer and the consumer's parser together, so the drift is invisible until a
production Sentry event looks wrong.

Applying the deletion test to a fix: a module that owns parse + vocabulary, if
deleted, would scatter the meta-stripping logic and the key set back into Sentry
and concentrate complexity here — it earns its keep. (Surfaced as candidate 1 of
the 2026-06-23 architecture review.)

## Non-goals

- **A neutral third module both instruments import.** There is exactly one
  consumer (Sentry); a shared-for-sharing's-sake module abstracts a sharing that
  does not exist yet and pulls the vocabulary away from the chain that generates
  it. One adapter is a hypothetical seam.
- **A symmetric `serialize()` on the value object.** The producer does not
  construct a `StructuredLogPayload`; it hands structlog's full `event_dict` to
  the existing serializer. A `serialize()` nobody calls would be dead surface.
- **An explicit sentinel/marker key stamped on every log line.** Replacing the
  `startswith("{")` heuristic with a marker pollutes the stdout JSON shape for
  every logging user to serve one consumer. The heuristic is cheap and adequate.
- **An absolute, compile-time-guaranteed drift fix.** That would require changing
  the emitted log shape (nesting user kwargs under a single `extra` key) for all
  users. We deliberately trade "impossible" for "unlikely + caught by a
  round-trip test" to avoid changing the log shape.
- **Renaming `skip_sentry`.** It stays honest-to-today; rename the day a second
  reporter honors it.

## Design

### 1. `StructuredLogPayload` value object in `logging_factory.py`

A consumer-side interpretation type living beside the existing serializer:

```python
@dataclasses.dataclass(frozen=True, slots=True)
class StructuredLogPayload:
    message: str | None       # the structlog `event` key; None when absent
    extra: dict[str, typing.Any]   # user fields, meta-keys already stripped
    skip_sentry: bool

    @classmethod
    def parse(cls, formatted: str) -> "StructuredLogPayload | None":
        """Interpret one rendered structlog line. Returns None when the string
        is not a structlog JSON object (non-JSON, decode error, or not a dict)."""
```

`parse` owns every "is this even a structlog line" guard (the `startswith("{")`
heuristic, `orjson.JSONDecodeError`, non-dict result) and the meta-stripping. No
caller ever sees the raw dict, so no caller can re-implement or forget the strip.
The value object holds **no** Sentry-event-shape knowledge — mapping onto
`event["logentry"]["formatted"]` / `contexts.structlog` stays in the Sentry
instrument.

### 2. Meta-key vocabulary moves and is renamed

`IGNORED_STRUCTLOG_ATTRIBUTES` (`sentry_instrument.py:19`) moves to
`logging_factory.py` as the public symbol `STRUCTLOG_META_KEYS` — named for what
it *is* (the producer's meta-key vocabulary) rather than what Sentry does with
it. It keeps the `STRUCTLOG_` prefix because the keys are structlog / our-chain
conventions. `parse` uses it internally; the round-trip test references it
directly.

The drift gap is handled pragmatically, not absolutely (see Non-goals):

- The set lives in `logging_factory`, which `logging_instrument` already imports;
  `logging_factory` cannot import `logging_instrument` back (circular), so the
  set cannot be *adjacent* to the chain.
- A cross-reference comment at `tracer_injection` / the processor chain in
  `logging_instrument.py` directs anyone adding a top-level meta-processor to
  extend `STRUCTLOG_META_KEYS`.
- The round-trip test (§4) is the regression net.

Only `tracing` (from our own `tracer_injection`) is a custom meta-key; the rest
(`level`, `logger`, `timestamp`, `exception`) are stable structlog-stdlib
processor outputs and `event` / `skip_sentry` are conventions. The real drift
surface is narrow: someone adds another custom top-level meta-processor and
forgets the set.

### 3. Sentry instrument shrinks to orchestration

`enrich_sentry_event_from_structlog_log` keeps its name and signature (it is the
`before_send` callback) and becomes:

```python
payload = StructuredLogPayload.parse(formatted_message)
if payload is None:        return event   # not a structlog JSON line
if payload.skip_sentry:    return None    # drop — checked BEFORE message
if not payload.message:    return event   # JSON without an `event` key
event["logentry"]["formatted"] = payload.message
if payload.extra:
    event["contexts"]["structlog"] = payload.extra
return event
```

The branch ordering is preserved exactly from the current implementation:
`skip_sentry` is honored before the message-presence check, so a line with
`skip_sentry` truthy and no `event` key still drops. `wrap_before_send_callbacks`
is untouched (it chains callbacks; orthogonal to payload parsing).

### 4. Seam direction and backward compatibility

The dependency is `sentry → logging_factory` — honest: Sentry consumes logging's
output format, and `logging_factory` is a lower-level mechanics module (it
imports neither instrument), so this is not peer-coupling between instruments.

`IGNORED_STRUCTLOG_ATTRIBUTES` is a public-named symbol on a shipped (1.1.x)
package, though it is not in `lite_bootstrap.__all__`. A silent module-level
alias `IGNORED_STRUCTLOG_ATTRIBUTES = STRUCTLOG_META_KEYS` stays in
`sentry_instrument.py` per the repo's rename convention, so any external import
keeps working.

## Operations

None. No infra, DNS, or external-account changes.

## Out of scope

Covered under Non-goals.

## Testing

Test-first (red before green). Three layers:

- **`StructuredLogPayload.parse` table (new).** Raw JSON string in → `message` /
  `extra` / `skip_sentry` out, no Sentry event constructed: non-JSON → `None`;
  JSON non-dict → `None`; dict without `event` → `message is None`; normal line →
  meta-keys stripped from `extra`; `skip_sentry` truthy → flag set; **DES-4**:
  `skip_sentry=False` stripped from `extra` (relocated from the Sentry layer with
  a comment naming its DES-4 audit origin).
- **Round-trip (new).** A representative `event_dict` → real
  `_serialize_log_with_orjson_to_string` → `parse` → assert `message` / `extra` /
  `skip_sentry`. Exercises producer serializer + consumer parse + vocabulary
  together; this is the drift net.
- **Sentry orchestration (slimmed).** `enrich_sentry_event_from_structlog_log`
  over Sentry-shaped events, three outcomes only — drop (`skip_sentry`),
  modify+attach (normal), passthrough (non-structlog / `event`-less). Shape
  detail now lives at the value-object layer.

`just test` green, `just lint-ci` clean (`ty` included).

## Risk

- **Behavior change masquerading as a refactor (med likelihood × high impact).**
  The three branch outcomes and the skip-before-message ordering must be
  byte-identical to today. Mitigation: the slimmed Sentry orchestration tests pin
  all three outcomes; the DES-4 case is preserved (relocated, not deleted); the
  ordering is an explicit test case.
- **Residual drift (low × med).** A future custom meta-processor whose key is not
  added to `STRUCTLOG_META_KEYS` still leaks. Mitigation: cross-reference comment
  at the chain + the round-trip test (catches it only if the fixture includes the
  new key — documented as a known limit, the deliberate trade from Non-goals).
- **Back-compat miss (low × med).** An external importer of
  `IGNORED_STRUCTLOG_ATTRIBUTES` breaks. Mitigation: silent alias retained.
