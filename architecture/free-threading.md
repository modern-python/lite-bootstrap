# Free-threaded Python (nogil)

`lite-bootstrap` runs on free-threaded CPython (PEP 703): 3.14t (officially
supported per PEP 779) and 3.13t (experimental). The library is pure Python;
what blocks a given surface on ft is always a native dependency somewhere in
its extra, not `lite-bootstrap` itself.

## Support matrix

| Surface | 3.13t | 3.14t | Notes |
|---|---|---|---|
| core, `logging`, `sentry` | ✅ | ✅ | pure Python; `logging` uses the stdlib-json serializer fallback when `orjson` is absent |
| `fastapi`/`faststream` (+ `-sentry`/`-logging`/`-metrics`) | ✅ | ✅ | pure Python + `pydantic-core` ft wheels |
| `litestar` (+ `litestar-metrics`) | ❌ | ✅ | `msgspec` gates `Py_GIL_DISABLED` to Python 3.14+ — its `_core.c` contains `#error "Py_GIL_DISABLED is only supported in Python 3.14+"` (v0.21.1), so the source build fails on 3.13t. See [`planning/deferred.md`](../planning/deferred.md) |
| `fastmcp` (+ `fastmcp-metrics`) | ❌ | ❌ | 3.13t: `cffi` (via `fastmcp`→`cryptography`) refuses to build free-threaded. 3.14t: `fastmcp` pulls bare `opentelemetry-api` without `opentelemetry-sdk`, so `import lite_bootstrap` still fails. See [`planning/deferred.md`](../planning/deferred.md) |
| `orjson` (opt-in speedup) | ❌ | ❌ | no ft wheels, build refuses ft ([ijl/orjson#530](https://github.com/ijl/orjson/issues/530)). Omit it on ft; the serializer falls back to stdlib json |
| `otl` (gRPC exporter) | ❌ | ❌ | needs `grpcio`, no ft wheels ([grpc/grpc#38762](https://github.com/grpc/grpc/issues/38762)). An HTTP-exporter path is deferred (`planning/deferred.md`) |
| `pyroscope` | ❌ | ❌ | `pyroscope-io` is abi3-only, unmaintained, no ft wheels ([`planning/deferred.md`](../planning/deferred.md)) |

The CI matrix (`.github/workflows/_checks.yml`, `free-threaded` job) installs
per Python version to match this table exactly: the 3.13t leg's extras stop at
`logging,sentry,fastapi,faststream,fastapi-metrics,faststream-metrics`; the
3.14t leg adds `litestar,litestar-metrics`. `orjson`, `otl`, `pyroscope`, and
`fastmcp`/`fastmcp-metrics` are excluded from both legs.

## The `orjson` fallback

`orjson` is used only by the logging serializer. It is an opt-in extra
(`lite-bootstrap[orjson]`), preferred when present (GIL-build output unchanged);
otherwise `logging_factory` serializes with the stdlib `json` accelerator using
compact separators and `ensure_ascii=False`, so output stays byte-identical for
JSON-native values. Trade-off on the fallback: ~2-5x slower JSON, and non-JSON-native
types in log `extra` (datetime/UUID) render via repr instead of orjson's native
encoding. Reverts to the native path automatically once `orjson` ships ft wheels.

## Single-threaded-init invariant

`bootstrap()`/`teardown()` are startup/shutdown, main-thread operations. The
cached mutable state (`is_bootstrapped`, `OpenTelemetryInstrument._tracer_provider`,
the `_lite_bootstrap_teardown_attached` marker) is **not** guarded for concurrent
calls on one bootstrapper — by design. Free-threading parallelizes request
handling, where `lite-bootstrap` does not sit. Do not call `bootstrap()`/`teardown()`
on the same bootstrapper from multiple threads.

## Related import-safety fixes

Verifying `fastmcp` on 3.14t (import-time, still excluded per the matrix above)
surfaced two pre-existing import-safety bugs, now fixed and not ft-specific —
any environment with a partial `opentelemetry` stack could trigger them:
`import_checker.py`'s dotted `find_spec` calls raising `ModuleNotFoundError`
instead of returning `False` on an incomplete parent namespace, and
`opentelemetry_instrument.py` importing the gRPC OTLP exporter unconditionally
under the coarse `is_opentelemetry_installed` guard. See
[`architecture/instruments.md`](instruments.md)'s "Optional-dependency guard"
section for the fix and the honest trade-off it leaves open (a silent OTLP-export
skip), and [`planning/deferred.md`](../planning/deferred.md) for the remaining
sdk-vs-api activation-semantics gap.

## Proof

`.github/workflows/_checks.yml` runs `scripts/ft_smoke.py` on 3.13t and 3.14t:
it asserts a free-threaded interpreter, `orjson` absent, the serializer fallback
round-trips, and a FastAPI bootstrap/teardown succeeds. It is a standalone
script rather than a `just test` run because `tests/conftest.py` hard-imports
`opentelemetry`, which the ft leg does not install.
