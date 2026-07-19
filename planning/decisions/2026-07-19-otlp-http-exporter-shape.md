---
status: accepted
summary: otl repoints to the grpc exporter package and a new otl-http adds the http exporter (no framework variants); the insecure warning stays gRPC-only (http security is the endpoint URL scheme).
supersedes: null
superseded_by: null
---

# OTLP HTTP exporter: extras shape and http security signal

**Decision:** `otl` → `opentelemetry-exporter-otlp-proto-grpc`; new `otl-http` →
`opentelemetry-exporter-otlp-proto-http` (no grpcio); no framework `*-otl-http`
variants. The `__post_init__` insecure warning stays tied to the gRPC `insecure`
flag; for HTTP, the endpoint URL scheme (`http://` vs `https://`) carries
security and is documented, not warned.

## Context

`otl` bundled `opentelemetry-exporter-otlp` (a meta package pulling grpc→grpcio
and http). To make OTLP export work on free-threaded Python (no grpcio wheels),
the exporter must be selectable and the http path must be installable without
grpcio. Two shape questions arose.

## Decision & rationale

**Extras — `otl`=grpc, `otl-http`=http, base only.** Repointing `otl` to the
grpc exporter package is functionally identical for existing users (it already
defaulted to gRPC and never used the http exporter) and drops only the unused,
transitively-bundled http package. `otl-http` carries the grpcio-free http
exporter for ft. Rejected: keeping `otl` as the meta and layering `otl-http`
on top — leaves `otl` grpcio-bound and redundant (already ships http). Rejected:
framework `*-otl-http` variants (`fastapi-otl-http`, …) — the same combinatorial
extras sprawl avoided in the free-threading work; a ft framework service composes
`[fastapi, otl-http]` and adds its instrumentation package directly.

**HTTP security signal — no warning.** The gRPC exporter has an `insecure` bool
that the config warns about for non-local endpoints. The HTTP exporter has no
such flag; its endpoint is a full URL whose scheme is the security signal.
Re-deriving an "insecure" state by parsing `http://` vs `https://` would add
scheme-parsing to `__post_init__` for a signal the user already controls
explicitly in the URL. Documented instead. Rejected: an http:// non-local
warning — more code for a weaker nudge than the URL itself already gives.

## Revisit trigger

A user asks for a framework-specific ft OTLP-http convenience extra, or for the
http endpoint to accept a bare `host:port` (auto-building the URL) — either would
reopen the extras/URL-handling shape.
