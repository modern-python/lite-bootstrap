# OTLP over HTTP is a sibling extra, and HTTP carries no insecure warning

**Decision:** `otl` points at `opentelemetry-exporter-otlp-proto-grpc`; a sibling `otl-http` carries
`opentelemetry-exporter-otlp-proto-http` (no `grpcio`). There are no framework `*-otl-http` variants.
The `__post_init__` insecure-endpoint warning stays tied to the gRPC `insecure` flag; for HTTP the
endpoint URL's scheme is the security signal, and it is documented rather than warned about.

## Context

`otl` used to pull `opentelemetry-exporter-otlp`, a meta package that drags in the gRPC exporter and
therefore `grpcio`. `grpcio` has no free-threaded wheels, so OTLP export on ft needs the HTTP
exporter to be installable on its own.

## Rejected alternatives

**Keep `otl` as the meta package and layer `otl-http` on top.** Leaves `otl` `grpcio`-bound and
redundant, since the meta package already ships the HTTP exporter. Repointing `otl` at the gRPC
exporter package is functionally identical for existing users — the exporter already defaulted to
gRPC and the HTTP package was never used — and drops only an unused transitive dependency.

**Framework `*-otl-http` variants (`fastapi-otl-http`, `litestar-otl-http`, …).** The same
combinatorial sprawl rejected for `orjson` in ADR-0005. A free-threaded framework service composes
`[fastapi, otl-http]` and adds its own instrumentation package directly.

**An `http://`-non-local warning mirroring the gRPC one.** The gRPC exporter has an `insecure` bool
that the config can inspect; the HTTP exporter has no such flag, only a full endpoint URL. Re-deriving
an "insecure" state would mean parsing `http://` vs `https://` in `__post_init__` to nudge the user
about a signal they already typed explicitly into the URL — more code for a weaker signal than the
URL itself gives.

**Revisit trigger:** a user asks for a framework-specific free-threaded OTLP-HTTP convenience extra,
or for the HTTP endpoint to accept a bare `host:port` and auto-build the URL. Either reopens the
extras shape or the URL handling.
