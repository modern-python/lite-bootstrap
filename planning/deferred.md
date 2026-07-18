# Deferred Work

Items raised in reviews or audits that are real but not actionable now.
Each is parked here with the reason it's deferred and the concrete trigger
that should bring it back. This is the long-tail register — not a backlog
of planned work. When an item is picked up it graduates to a spec/plan
change file in [`changes/active/`](changes/active/); see [CLAUDE.md](../CLAUDE.md#workflow).

## Open

### OTLP export on free-threaded Python (HTTP exporter path)

The `otl` extra pulls `grpcio` (via the gRPC OTLP exporter), which has no
free-threaded wheels, so `otl` is uninstallable on ft. `opentelemetry_instrument.py`
hardwires the gRPC exporter (`from opentelemetry.exporter.otlp.proto.grpc...`).
Fix would add an `opentelemetry_exporter_protocol` field (grpc|http) + an
`otl-http` extra on `opentelemetry-exporter-otlp-proto-http` (no grpcio; protobuf
falls back to pure-python). Deferred from the 2026-07-18 free-threading change to
keep that change orjson-only.
**Trigger:** a user needs OTLP trace export on ft, **or** `grpcio` ships ft wheels
([grpc/grpc#38762](https://github.com/grpc/grpc/issues/38762)) making the swap moot.

### Pyroscope on free-threaded Python

`pyroscope-io` is abi3-only, unmaintained, ships no ft wheels and has no pure
fallback, so the `pyroscope` extra cannot install on ft. No action possible from
this repo.
**Trigger:** `pyroscope-io` ships ft wheels (or a maintained ft-capable
replacement appears).

### fastmcp on free-threaded Python (import_checker crash, not an install failure)

`fastmcp` *installs* fine on ft (3.14t confirmed), but importing `lite_bootstrap`
afterward crashes. `fastmcp` requires `fastmcp-slim[client,server]`, which
unconditionally requires `opentelemetry-api` — independent of lite-bootstrap's own
`otl` extra. On the ft leg `otl` is excluded (see the OTLP entry above), so
`opentelemetry-api` ends up installed without `opentelemetry-instrumentation`.
`lite_bootstrap/import_checker.py` then calls
`find_spec("opentelemetry.instrumentation.fastapi")` /
`find_spec("opentelemetry.instrumentation.asgi")`; `importlib.util.find_spec` imports
the dotted name's parent package first, and since `opentelemetry.instrumentation`
isn't installed, that raises `ModuleNotFoundError` instead of returning `None`,
crashing `import lite_bootstrap` entirely. Reproduced 2026-07-18 on 3.14t: `uv pip
install ".[fastmcp]"` succeeds, but `python -c "import lite_bootstrap"` raises
`ModuleNotFoundError: No module named 'opentelemetry.instrumentation'`. `fastmcp`
and `fastmcp-metrics` are excluded from the ft CI leg
(`.github/workflows/_checks.yml`) and from `scripts/ft_smoke.py`'s local
verification command pending this fix.
**Trigger:** fastmcp support on ft is needed, or `import_checker.py`'s two
`is_fastapi_opentelemetry_installed` / `is_litestar_opentelemetry_installed` checks
are made defensive against a present-but-incomplete `opentelemetry` namespace
package (e.g. wrap in `try/except ModuleNotFoundError`) — a fix worth making
regardless of ft, since any environment with `opentelemetry-api` but not
`opentelemetry-instrumentation` installed hits the same crash.

### litestar on free-threaded Python 3.13 (msgspec gates Py_GIL_DISABLED to 3.14+)

`litestar` unconditionally requires `msgspec`, which has no free-threaded wheel for
3.13t and fails to build from source there: `msgspec`'s own `_core.c` contains
`#error "Py_GIL_DISABLED is only supported in Python 3.14+"` (msgspec v0.21.1) — an
intentional upstream gate, not a build-environment problem. Reproduced 2026-07-18:
`uv pip install --python <3.13t venv> "litestar>=2.9"` fails compiling
`msgspec._core`; the same install against a 3.14t venv succeeds cleanly and
`scripts/ft_smoke.py`-equivalent checks pass. Because the ft CI leg
(`.github/workflows/_checks.yml`) runs one shared install step across the whole
`{3.13t, 3.14t}` matrix, `litestar` and `litestar-metrics` are excluded from that
step (and from the local verification command) for both Python versions, even
though litestar itself is ft-clean on 3.14t.
**Trigger:** `msgspec` extends `Py_GIL_DISABLED` support to 3.13, **or** the ft CI
leg is worth splitting into a per-python-version install step so `litestar` /
`litestar-metrics` can be added back for the 3.14t leg only.
