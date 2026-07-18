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
