---
status: accepted
summary: orjson becomes an opt-in extra with a stdlib-json fallback (not bundled in logging/*-all, not replaced by msgspec) so every extra installs on free-threaded CPython.
supersedes: null
superseded_by: null
---

# orjson is opt-in for free-threaded support

**Decision:** Make `orjson` its own opt-in extra with a stdlib-`json` fallback in
the logging serializer, rather than (B) keeping it bundled with `logging`/`*-all`
behind parallel ft-variant extras, or (C) replacing it with an ft-ready native
encoder (msgspec/ujson/rapidjson).

## Context

`orjson` is a mandatory core dep but hard-blocks free-threaded installs: no ft
wheels, and its build refuses to compile on ft (verified on 3.14t). It is used
only by the logging serializer. Three ways to unblock ft:

- **A (chosen):** `orjson` → opt-in extra; `logging` = `structlog`-only; serializer
  falls back to stdlib `json`.
- **B:** keep `orjson` reachable by default on GIL builds (left in core, or moved
  into the `logging` extra) and add parallel ft-variant extras (`*-ft`) that omit
  it — zero behaviour change for GIL users.
- **C:** replace `orjson` with msgspec (ft wheels ready today, litestar already
  uses it) or ujson/rapidjson as the single serializer.

PEP 508 has **no environment marker for "GIL enabled"**, so `orjson` cannot be
conditionally required only on GIL builds — the constraint that forces the choice.

## Decision & rationale

**A** keeps one coherent rule — *every* extra installs on ft, `orjson` is a
per-build opt-in speedup — with no combinatorial extras sprawl. It also fixes a
standing hygiene defect (a JSON encoder had no business being a mandatory core
dep). The GIL-build fast path is byte-for-byte unchanged when `[orjson]` is
present; the only cost is a documented, opt-in perf change for logging users who
don't add the extra (stdlib `json`, ~2-5x slower, same correctness).

**B rejected:** bundling `orjson` in `logging` means every logging-bearing and
`*-all` extra needs an ft twin (`fastapi-logging`, `free-all`, …) — the extras
matrix the maintainer explicitly wanted to avoid. Zero GIL change is not worth
that sprawl.

**C rejected:** a permanent new mandatory dependency to paper over a *temporary*
orjson gap ([ijl/orjson#530](https://github.com/ijl/orjson/issues/530) tracks ft
wheels toward the 3.15/abi3t timeframe). msgspec's encoder API differs (`enc_hook`,
not orjson's `default=`) and its output shape differs, forcing a serializer
rewrite and test re-baseline. The stdlib fallback is fully reversible — it simply
stops being exercised once `orjson` ships ft wheels.

## Revisit trigger

`orjson` ships free-threaded wheels (resolves #530). At that point `orjson` may
return to `logging`/core as a hard dep and the fallback branch retired — reopen
to decide whether the simplification is worth removing the opt-in extra.
