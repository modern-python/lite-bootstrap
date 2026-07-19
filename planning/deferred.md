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

### fastmcp on free-threaded Python

`fastmcp` and `fastmcp-metrics` are excluded from both ft CI legs
(`.github/workflows/_checks.yml`) and from `scripts/ft_smoke.py`'s local
verification commands, for two separate, independent reasons — one per leg:

- **3.13t (install-time, upstream, not fixable here):** `fastmcp` →
  `fastmcp-slim[server]` → `joserfc` → `cryptography` → `cffi`, and `cffi`
  (v2.1.0) refuses to build on free-threaded 3.13: "CFFI does not support the
  free-threaded build of CPython 3.13. Upgrade to free-threaded 3.14 or newer
  to use CFFI with the free-threaded build." — an upstream gate, not a
  build-environment problem, the same shape as msgspec's 3.13t gate below.
  Reproduced 2026-07-18: `uv pip install --python <3.13t venv> ".[fastmcp]"`
  fails building `cffi`.
- **3.14t (now importable):** `fastmcp` transitively pulls bare
  `opentelemetry-api` with no other `opentelemetry-*` package. The three
  incomplete-opentelemetry-stack bugs this exposed are all fixed — the
  `import_checker` namespace crash and the unconditional grpc-exporter import in
  `changes/2026-07-18.01`, and the api-vs-sdk conflation
  (`opentelemetry_instrument.py` importing `opentelemetry.sdk.*` and
  `check_dependencies()` under the api-only flag) in `changes/2026-07-19.01`. So
  `uv pip install ".[fastmcp]"` + `import lite_bootstrap` now succeeds on 3.14t;
  it is simply not yet wired into the 3.14t leg's extras.

**Trigger:** `cffi` ships free-threaded 3.13 wheels (unblocks 3.13t), **or** add
`fastmcp`/`fastmcp-metrics` to the 3.14t leg's extras in `_checks.yml` (import
now works there).

### litestar on free-threaded Python 3.13 (msgspec gates Py_GIL_DISABLED to 3.14+)

`litestar` unconditionally requires `msgspec`, which has no free-threaded wheel for
3.13t and fails to build from source there: `msgspec`'s own `_core.c` contains
`#error "Py_GIL_DISABLED is only supported in Python 3.14+"` (msgspec v0.21.1) — an
intentional upstream gate, not a build-environment problem. Reproduced 2026-07-18:
`uv pip install --python <3.13t venv> "litestar>=2.9"` fails compiling
`msgspec._core`; the same install against a 3.14t venv succeeds cleanly and
`scripts/ft_smoke.py`-equivalent checks pass. The ft CI leg
(`.github/workflows/_checks.yml`) now installs per Python version, so `litestar`
and `litestar-metrics` run on the 3.14t leg and are excluded only from 3.13t.
**Trigger:** `msgspec` extends `Py_GIL_DISABLED` support to 3.13, at which point
`litestar` / `litestar-metrics` can be added to the 3.13t leg too.
