# Cross-cutting logic stays where it is: per-instrument, and in one method

Two re-organizations have been proposed and rejected for the same reason: each moves complexity
around without reducing it, and the matrix is O(instruments × frameworks) whichever axis it is cut
along.

The instrument × framework matrix keeps its per-instrument axis: base instruments own the hoisted
logic and each framework is a thin `bootstrap()` subclass, rather than per-framework adapters driving
generic instruments. The bindings differ (FastAPI imperative with `add_middleware` and
`include_router`, Litestar declarative before the app is built, FastStream attaching to a broker,
FastMCP via `custom_route`), so a uniform `add_route`/`add_middleware` interface would leak; and
framework-locality already exists, because all of a framework's subclasses live in its one
bootstrapper file. Reconsider if the per-cell bindings start converging, or if a new framework shares
an existing one's attach mechanism exactly.

OpenTelemetry's `_build_infrastructure_excluded_paths` owns the exclusion policy for
the metrics route and the health route. Framework bindings apply those paths alongside
caller-supplied URL patterns. HTTP-level tests verify the resulting exclusions.
A per-instrument contribution mechanism would distribute the same policy across
configuration classes while retaining their dependency on the health span setting.
