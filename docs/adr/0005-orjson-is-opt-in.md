# `orjson` is an opt-in extra with a stdlib-`json` fallback

**Decision:** `orjson` is its own extra (`lite-bootstrap[orjson]`), the `logging` extra is
`structlog` only, and the logging serializer falls back to the stdlib `json` accelerator when
`orjson` is absent. It is not bundled with `logging`/`*-all`, and it is not replaced by a
free-threading-ready native encoder.

## Context

`orjson` used to be a mandatory core dependency, used only by the logging serializer, and it
hard-blocks free-threaded installs: no ft wheels, and the build refuses to compile on ft (verified
on 3.14t). PEP 508 has **no environment marker for "GIL enabled"**, so `orjson` cannot be required
conditionally on GIL builds only. That missing marker is what forces the choice.

## Rejected alternatives

**Keep `orjson` reachable by default and add parallel `*-ft` extras that omit it.** Zero behaviour
change for GIL users, at the cost of an ft twin for every logging-bearing and `*-all` extra —
`fastapi-logging-ft`, `free-all-ft`, and so on. That is exactly the combinatorial extras sprawl this
project refuses; the same argument later rejected `*-otl-http` framework variants (ADR-0006).

**Replace `orjson` with an ft-ready native encoder — msgspec, ujson, rapidjson.** A permanent new
mandatory dependency to paper over a *temporary* gap ([ijl/orjson#530](https://github.com/ijl/orjson/issues/530)
tracks ft wheels). msgspec's encoder API differs (`enc_hook`, not orjson's `default=`) and so does
its output shape, forcing a serializer rewrite and a test re-baseline — for a dependency that would
outlive the problem.

The chosen shape keeps one coherent rule: `orjson` is a per-build opt-in speedup, and no extra drags
it in. It also fixed a standing hygiene defect — a JSON encoder had no business being a mandatory
core dependency. The GIL fast path is byte-for-byte unchanged when `[orjson]` is present; the cost
is a documented, opt-in performance change (stdlib `json`, roughly 2-5x slower, same correctness,
and non-JSON-native values in log `extra` render via `repr` rather than orjson's native encoding).

**Revisit trigger:** `orjson` ships free-threaded wheels (#530 resolves). At that point it could
return to `logging`/core as a hard dependency and the fallback branch retire — reopen then to decide
whether that simplification is worth removing the opt-in extra.
