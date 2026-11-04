# Lifecycle ownership spike

Throwaway code, not a production implementation. Based on main `2af92e041eb0d22fffe1ef3e3961cfad031342c5`;
compares alternatives to PR [#443](https://github.com/modern-python/lite-bootstrap/pull/443), head `840f6ce`.

## Decision

Use the framework lifespan as the normal owner of observability. Let code that drives
`start()` / `stop()` manually own cleanup explicitly. Share the resource ownership and
error-preservation policy internally. Keep the existing bootstrapper interface for 2.0.

This is a deliberate change to manual-operation behavior. Update #434's contract before
changing #443. The prototype does not authorize that compatibility change or implement it.

An explicit context around every runner is feasible, but replacing the normal framework
lifespan with it would increase deployment responsibilities for callers. A broad new
public observability interface is not justified by this experiment.

## Run and inspect

From the repository root:

```bash
uv run --no-sync python research/lifecycle-prototype/run.py
```

Every case gets a fresh process because OTel's global tracer provider is set once.
The command prints each outcome and saves full observations in [results.json](results.json).
No production modules are changed, no telemetry goes to a network exporter, and broker
network start/stop are replaced with local stand-ins.

Individual working examples:

```bash
uv run --no-sync python research/lifecycle-prototype/run.py fastapi lifespan happy
uv run --no-sync python research/lifecycle-prototype/run.py faststream lifespan happy
uv run --no-sync python research/lifecycle-prototype/run.py faststream explicit manual
uv run --no-sync python research/lifecycle-prototype/run.py fastapi explicit combined-error
```

[demo.html](demo.html) is a self-contained recorded walkthrough and free-play model.
Its recorded data comes from the Python runs; its free-play state machine is illustrative.
Browser preview was blocked by the browser's local-file URL policy, so the HTML has not
received visual verification. The Python experiments ran successfully.

## What was compared

Both designs use the same proposed `observability()` owner in [run.py](run.py).
It creates a provider only when none exists, shuts down only that provider, and preserves
the original error if cleanup also fails. This isolates lifecycle placement from SDK policy.

| | A: Framework lifespan | B: Explicit runner context |
|---|---|---|
| Actual placement | `managed_lifespan(user_lifespan, state)` passed to the framework constructor | `with observability(state)` around the runner |
| Shutdown order | Framework shutdown, user shutdown, telemetry cleanup | Framework shutdown, user shutdown, telemetry cleanup |
| Ordinary ASGI caller | Framework enters and exits the owner | Caller must enclose the server's complete run |
| Manual FastStream start/stop | Requires explicit ownership | Works inside the context |
| Installed prototype hooks / flags | Constructor lifespan helper; no instance replacement or active flag | No lifecycle hooks or active flag |
| Existing bootstrapper compatibility | Can retain the existing interface with one lifespan replacement | Requires caller entry-point changes |

The prototype's constructor helper is an illustrative seam, not a proposed public function
with a diagnostic `state` parameter. Retaining lite-bootstrap's existing application-taking
interface would still replace its lifespan callable. That implementation cost remains.

## Evidence

34 isolated runs: **33 passed, one unsupported by the chosen contract**. The unsupported
case calls FastStream start/stop directly with design A, so neither telemetry initialization
nor automatic cleanup is entered. This is a visible limitation, not a passing cleanup case.

| Observation | A | B |
|---|---|---|
| FastAPI request span, user startup/shutdown spans, lifespan state | Preserved | Preserved |
| FastStream work, shutdown-hook, broker-drain and user-shutdown spans | Preserved | Preserved |
| FastStream configured lifespan argument | Preserved | Preserved |
| Telemetry setup failure | Owned provider closed once | Owned provider closed once |
| User startup/shutdown failure | Original exception preserved; provider closed once | Same |
| Broker/shutdown-hook failure | User cleanup runs before telemetry closes | Same |
| Exporter shutdown failure | Reported | Reported |
| Lifecycle failure plus exporter shutdown failure | Original exception plus cleanup note | Same |
| Existing external provider | Same provider, zero owner shutdowns, still exports afterward | Same |

Installed versions: FastAPI 0.162.0, FastStream 0.7.8, Starlette 1.10.0,
OTel SDK 1.45.2 and FastAPI instrumentation 0.66b2. Additionally ran the FastStream 0.6.0
lifespan happy path and explicit combined-error path successfully, using the isolated
package in `/tmp/lite-faststream-floor-434`. These are spot checks, not full floor validation.

The naive constructor wrapper failed FastStream's injection with
`unexpected keyword argument 'context__'`. Preserving the original callable with
`functools.wraps` fixed it. [naive-wrapper-result.json](naive-wrapper-result.json) preserves
that observation. Reproduce it by removing only the wrapper's `functools.wraps` decorator.

## Caller setup and deployment cost

Design A adds lifespan composition at construction in the prototype. Framework-controlled
startup then determines the correct lifetime. Constructor composition must preserve the
user callable's signature; wrapping FastStream's already-injected `lifespan_context`, as
#443 does, avoids that particular injection problem.

Design B adds a context around the complete runner. It fits embedded servers, scripts,
and manual broker operation. An application exported for a server to import cannot hold
a synchronous module-level `with` block open through serving. Such deployments still need
a per-worker initialization/cleanup hook, naturally the ASGI lifespan.

The installed Uvicorn runner also requires an import string for reload or multiple workers
(`uvicorn/main.py`, reload/worker validation and supervisor branches). A context around the
parent launcher is insufficient evidence of worker ownership. Worker/reload behavior was
read in source, not executed in this spike; no support claim is made for it.

## Exact simplification available in #443

If 2.0 adopts explicit cleanup for manual operation:

1. In `FastStreamBootstrapper._wrap_lifecycle`, delete the captured `application_stop`,
   `lifespan_active`, its `nonlocal` declaration and reset, the nested `stop()` wrapper,
   and `application.stop = stop` including its type-checker suppression.
2. Keep one lifespan wrapper. Keep exception-safe cleanup and the one-bootstrapper guard.
   A smaller interface does not remove error-preservation or SDK ownership requirements.
3. Replace the six new automatic-manual-cleanup regression cases with coverage and examples
   for the agreed explicit manual-cleanup contract. Preserve shutdown-span and failure-path
   regressions for the ASGI lifespan.
4. Keep FastAPI's existing lifespan attachment. Share cleanup-error policy privately where
   the two real implementations need it; do not introduce a universal framework adapter.
5. Update the migration guide to state that direct start/stop and application context-manager
   usage require an explicit telemetry owner or `bootstrapper.teardown()` in `finally`.

If automatic cleanup for manual operation remains a requirement, keep #443's stop fallback.
It implements a real compatibility promise; renaming or moving it would not remove that cost.

## Limits and next implementation

The spike validates tracing lifetime and one provider's ownership. It does not implement
logging, Sentry, metrics, profiling, provider conflicts, partial custom-instrumentor rollback,
external instrumentor ownership, worker startup, cancellation, or repeated lifetimes.
Process-global SDK state remains set once and a closed provider cannot be made reusable by
this interface. Issue #436's ownership/rollback work remains necessary.

The recommended next implementation is a narrow revision of #434's manual-operation contract
and #443's lifecycle glue. Defer configuration and public-interface redesign. No production
changes, PR updates, merge, release, or issue-contract edits are part of this spike.
