---
status: accepted
summary: Keep the per-instrument axis for the instrument×framework matrix; reject inverting to per-framework adapters.
supersedes: null
superseded_by: null
---

# Keep the per-instrument axis for the instrument × framework matrix

**Decision:** The framework-binding code stays organized around the *instrument*
(base instrument classes own the shared logic; each framework is a thin subclass
overriding only its `bootstrap()` binding). We reject inverting to a per-framework
adapter axis (a `FastAPIAdapter`/`LitestarAdapter`/… that knows how to attach any
instrument, driven by generic instruments).

## Context

The codebase has an instrument × framework matrix: every filled cell is "how
instrument *I* binds to framework *F*" (e.g. `FastAPIHealthChecksInstrument`,
`LitestarPrometheusInstrument`). The 2026-06-23 architecture review raised candidate
3 — "the matrix has no framework-locality; ~28 shallow per-cell subclasses" — and
proposed inverting the axis so a per-framework adapter owns the binding and
instruments become generic.

Two organizations were on the table:

- **Per-instrument (current):** instrument is the base class and owns shared depth;
  framework is a subclass per cell. Subclasses are co-located one-file-per-framework
  (`fastapi_bootstrapper.py` holds all `FastAPI*Instrument` classes, etc.).
- **Per-framework (proposed):** framework adapter is primary and owns the binding;
  instruments call a small adapter interface (`add_route`, `add_middleware`, …).

## Decision & rationale

Keep the per-instrument axis. The candidate's premise and payoff do not hold up:

- **Framework-locality already exists at the file level.** All of a framework's
  instrument subclasses live in its one bootstrapper file, so "what does
  lite-bootstrap do to my FastAPI app" is already answered by reading one file. The
  review's "five scattered classes" are co-located, not scattered.
- **The shared depth is already hoisted.** `render_health_check_data()` lives in the
  base `HealthChecksInstrument`; provider setup in base `OpenTelemetryInstrument`;
  config validation in the base configs. The per-framework subclasses contain *only*
  the genuinely-different binding, which is what you want — the thinness is the result
  of correct hoisting, not shallowness to fix.
- **The N×M bindings differ genuinely.** FastAPI is imperative (`app.add_middleware`,
  `include_router`), Litestar is declarative *before the app is built*
  (`application_config.cors_config = …`, append to `middleware`/`route_handlers`),
  FastStream attaches middleware to a *broker* not the app, FastMCP uses
  `custom_route`. A uniform adapter interface (`add_route`/`add_middleware`) would
  have to paper over imperative-vs-declarative-vs-broker and normalize differing
  handler return types — it would leak.
- **Deletion test fails for the inversion.** Inverting relocates the same N×M
  genuinely-different bindings into framework-grouped adapters; the complexity
  *moves*, it does not *concentrate*. The matrix is inherently O(instruments ×
  frameworks); no axis choice removes a cell. Adding an instrument touches every
  framework either way; adding a framework touches every instrument either way.

No friction worth a refactor was identified (navigation is satisfied by the file
layout; the cross-cutting change cost is inherent to the matrix; the per-cell
"shallowness" is hoisted-out depth, not duplication).

## Revisit trigger

- The per-cell bindings start genuinely **converging/duplicating** — the shared part
  outgrows the base instrument and the same binding code appears across framework
  subclasses. Then hoist the convergent part (possibly into a small shared helper),
  and reconsider an adapter for that specific shared mechanism.
- A new framework arrives that **shares an existing framework's attach mechanism**
  (e.g. another ASGI app driven exactly like FastAPI). Two adapters with the same
  shape turn the hypothetical seam into a real one, and a per-framework adapter for
  that pair becomes justified.
