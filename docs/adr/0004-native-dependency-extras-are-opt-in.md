# Native-dependency extras are opt-in, and never per-framework variants

Free-threaded CPython has wheels for neither `orjson` nor `grpcio`, and PEP 508 has no environment
marker for "GIL enabled", so neither can be required conditionally. Both are therefore opt-in:
`orjson` is its own extra (`logging` is `structlog` only) with the logging serializer falling back to
the stdlib `json` accelerator, and OTLP over HTTP is a sibling `otl-http` extra beside a gRPC-only
`otl`. The fallback is a documented performance change, not a correctness one — roughly 2-5x slower,
with non-JSON-native values in log `extra` rendering via `repr`; the GIL fast path is byte-for-byte
unchanged when `[orjson]` is installed.

Both refuse the combinatorial alternative: `*-ft` twins of every logging-bearing and `*-all` extra,
or `fastapi-otl-http`-style framework variants. A free-threaded service composes `[fastapi, otl-http]`
itself. Replacing `orjson` with msgspec, ujson or rapidjson was also rejected — a permanent mandatory
dependency, with a different encoder API and output shape, to paper over a temporary gap
([ijl/orjson#530](https://github.com/ijl/orjson/issues/530) tracks ft wheels); if that resolves,
`orjson` could return to core and the fallback branch retire.

The HTTP exporter deliberately carries no insecure-endpoint warning mirroring the gRPC one: it has no
`insecure` flag to inspect, only a full URL whose scheme is a stronger signal than anything
`__post_init__` could re-derive, and the user typed it explicitly.
