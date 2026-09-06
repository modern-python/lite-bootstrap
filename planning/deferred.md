# Deferred Work

Items raised in reviews or audits that are real but not actionable now.
Each is parked here with the reason it's deferred and the concrete trigger
that should bring it back. This is the long-tail register — not a backlog
of planned work. When an item is picked up it graduates to a spec/plan
change file in [`changes/active/`](changes/active/); see [AGENTS.md](../AGENTS.md#workflow).

## Open

### Pyroscope on free-threaded Python

`pyroscope-io` is abi3-only, unmaintained, ships no ft wheels and has no pure
fallback, so the `pyroscope` extra cannot install on ft. No action possible from
this repo.
**Trigger:** `pyroscope-io` ships ft wheels (or a maintained ft-capable
replacement appears).

### fastmcp on free-threaded Python 3.13 (cffi gates Py_GIL_DISABLED to 3.14+)

`fastmcp`/`fastmcp-metrics` run on the **3.14t** ft CI leg
(`.github/workflows/_checks.yml`) but are excluded from **3.13t**: `fastmcp` →
`fastmcp-slim[server]` → `joserfc` → `cryptography` → `cffi`, and `cffi` (v2.1.0)
refuses to build on free-threaded 3.13 ("CFFI does not support the free-threaded
build of CPython 3.13. Upgrade to free-threaded 3.14 or newer to use CFFI with
the free-threaded build.") — an upstream gate, the same shape as msgspec's 3.13t
gate below. Reproduced 2026-07-18: `uv pip install --python <3.13t venv>
".[fastmcp]"` fails building `cffi`. (The three opentelemetry-stack import bugs
that previously also blocked 3.14t are fixed in `changes/2026-07-18.01` and
`changes/2026-07-19.01`.)
**Trigger:** `cffi` ships free-threaded 3.13 wheels.

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
