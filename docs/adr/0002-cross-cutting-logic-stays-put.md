# Cross-cutting logic stays where it is: per-instrument, and in one method

Two re-organizations have been proposed and rejected for the same reason — each moves complexity
rather than concentrating it, and the matrix is inherently O(instruments × frameworks) whichever axis
it is cut along.

The instrument × framework matrix keeps its **per-instrument axis**: base instruments own the hoisted
logic and each framework is a thin `bootstrap()` subclass, rather than per-framework adapters driving
generic instruments. The bindings genuinely differ — FastAPI imperative (`add_middleware`,
`include_router`), Litestar declarative before the app is built, FastStream attaching to a broker,
FastMCP via `custom_route` — so a uniform `add_route`/`add_middleware` interface would leak; and
framework-locality already exists, because all of a framework's subclasses live in its one
bootstrapper file. Reconsider if the per-cell bindings start converging, or if a new framework shares
an existing one's attach mechanism exactly.

`_build_excluded_urls` likewise keeps the whole trace-exclusion policy in **one method** that reads
its siblings' paths through `getattr(..., None)` — those sibling configs are genuinely optional, so
the defensive read is correct rather than a smell. A per-instrument contribution mechanism would
spread the policy across `PrometheusConfig`, `HealthChecksConfig` and OpenTelemetry while still
needing `opentelemetry_generate_health_check_spans`, so the coupling would not even disappear. The
real risk — renaming `prometheus_metrics_path` and silently stopping the exclusion — is answered by a
test pinning each sibling path in the built set. Reconsider when a user-supplied instrument needs
paths the policy cannot know about.
