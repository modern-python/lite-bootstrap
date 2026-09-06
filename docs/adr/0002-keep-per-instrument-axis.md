# Keep the per-instrument axis for the instrument × framework matrix

**Decision:** The framework-binding code stays organized around the *instrument* — base instrument
classes own the shared logic, and each framework is a thin subclass overriding only its `bootstrap()`
binding. We reject inverting to a per-framework adapter axis (a
`FastAPIAdapter`/`LitestarAdapter`/… that knows how to attach any instrument, driven by generic
instruments).

## Context

The codebase has an instrument × framework matrix: every filled cell is "how instrument *I* binds to
framework *F*" (e.g. `FastAPIHealthChecksInstrument`, `LitestarPrometheusInstrument`). The
2026-06-23 architecture review raised the matrix as candidate 3 — "no framework-locality; ~28 shallow
per-cell subclasses" — and proposed inverting the axis so a per-framework adapter owns the binding
and instruments become generic.

## Decision & rationale

The candidate's premise and payoff do not hold up:

- **Framework-locality already exists at the file level.** All of a framework's instrument
  subclasses live in its one bootstrapper file, so "what does lite-bootstrap do to my FastAPI app"
  is already answered by reading one file. The review's "five scattered classes" are co-located,
  not scattered.
- **The shared depth is already hoisted.** `render_health_check_data()` lives in the base
  `HealthChecksInstrument`; provider setup in base `OpenTelemetryInstrument`; config validation in
  the base configs. The per-framework subclasses contain *only* the genuinely-different binding,
  which is what you want — the thinness is the result of correct hoisting, not shallowness to fix.
- **The N×M bindings differ genuinely.** FastAPI is imperative (`app.add_middleware`,
  `include_router`), Litestar is declarative *before the app is built* (`application_config.cors_config = …`,
  append to `middleware`/`route_handlers`), FastStream attaches middleware to a *broker* not the
  app, FastMCP uses `custom_route`. A uniform adapter interface (`add_route`/`add_middleware`) would
  have to paper over imperative-vs-declarative-vs-broker and normalize differing handler return
  types — it would leak.
- **Deletion test fails for the inversion.** Inverting relocates the same N×M genuinely-different
  bindings into framework-grouped adapters; the complexity *moves*, it does not *concentrate*. The
  matrix is inherently O(instruments × frameworks); no axis choice removes a cell. Adding an
  instrument touches every framework either way; adding a framework touches every instrument either
  way.

No friction worth a refactor was identified: navigation is satisfied by the file layout, the
cross-cutting change cost is inherent to the matrix, and the per-cell "shallowness" is hoisted-out
depth rather than duplication.

**Revisit trigger:** the per-cell bindings start genuinely converging — the shared part outgrows the
base instrument and the same binding code appears across framework subclasses; then hoist the
convergent part and reconsider an adapter for that specific shared mechanism. Or a new framework
arrives that shares an existing framework's attach mechanism (another ASGI app driven exactly like
FastAPI), turning the hypothetical seam into a real one for that pair.
