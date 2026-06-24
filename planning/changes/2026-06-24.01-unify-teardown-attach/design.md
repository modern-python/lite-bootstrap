---
status: shipped
date: 2026-06-24
slug: unify-teardown-attach
summary: Move the teardown-on-shutdown attach behind one BaseBootstrapper._attach_teardown_once seam with a uniform marker, extending the double-attach guard to Litestar and FastStream.
supersedes: null
superseded_by: null
pr: 130
outcome: Shipped as designed — one _attach_teardown_once seam owns detection + warning + skip; FastAPI/FastMCP migrated behavior-preserving; Litestar/FastStream gained the guard; attach typed Callable[[], object]; 100% coverage held.
---

# Design: Unify the teardown-on-shutdown attach behind one guarded seam

## Summary

"Register this bootstrapper's `teardown` to run on the framework's shutdown" is a
real seam implemented ad-hoc in five `__init__` bodies. The double-attach guard +
warning is copy-pasted between FastAPI and FastMCP (with two different detection
mechanisms) and absent from Litestar and FastStream. This change moves the guard
into one `BaseBootstrapper._attach_teardown_once(target, attach)` method that owns
detection (a uniform `_lite_bootstrap_teardown_attached` marker), the warning, and
the skip; each framework's `__init__` shrinks to "here is my target, here is how I
attach." The guard extends uniformly to Litestar and FastStream, closing a
behavioral inconsistency.

## Motivation

The teardown-attach is wired five different ways (verified across
`bootstrappers/*.py`):

- **FastAPI** (`fastapi_bootstrapper.py:204-217`): reads a marker
  `_lite_bootstrap_lifespan_attached`, warns + skips if set, else marks and merges
  its lifespan via `_merge_lifespan_context`.
- **FastMCP** (`fastmcp_bootstrapper.py:155-163`): **structural** check
  `any(isinstance(p, _TeardownProvider) for p in app.providers)`, warns + skips,
  else adds a `_TeardownProvider`.
- **Litestar** (`litestar_bootstrapper.py:281`): bare
  `application_config.on_shutdown.append(self.teardown)` — **no guard**.
- **FastStream** (`faststream_bootstrapper.py:208`): bare
  `application.on_shutdown(self.teardown)` — **no guard**.
- **Free** (`free_bootstrapper.py`): no app, no shutdown lifecycle — out of scope.

The same user error — two bootstrappers constructed against one app — is handled
inconsistently: FastAPI/FastMCP warn and skip (their guard is tested at
`test_fastapi_bootstrap.py:130` and `test_fastmcp_bootstrap.py:283`), while
Litestar/FastStream silently double-register `teardown`. The shared logic (check →
warn → skip → else mark + attach) and near-identical warning text live in two
copies; detection is reinvented per framework. Deletion test on a unified guard:
delete it and the guard + warning re-duplicate across FastAPI/FastMCP and the gap
on Litestar/FastStream reopens — it concentrates complexity, so it earns its keep.
(Surfaced as candidate 2 of the 2026-06-23 architecture review; marked "worth
exploring".)

## Non-goals

- **Unifying the attach mechanism.** The four mechanisms (lifespan merge, provider,
  `on_shutdown` list append, `on_shutdown()` method call) are genuinely different
  and stay framework-specific. Only detection + warn + skip are shared.
- **A class-level registry / WeakSet for "already attached".** Considered, rejected:
  it would contradict the documented `_lite_bootstrap_*` app-tagging convention
  (`architecture/bootstrappers.md:68`) and introduce process-global mutable state
  with test-isolation hazards. The marker keeps the "attached" bit local to the
  app's lifetime.
- **A free-function helper module.** The guard is bootstrapper-lifecycle logic and
  belongs on `BaseBootstrapper` next to `teardown()`, where `type(self).__name__`
  is available for the warning.
- **Changing the warn-and-skip policy to raise.** FastAPI/FastMCP keep lenient
  warn+skip; Litestar/FastStream adopt the same. No escalation to an error.
- **Bringing Free into the seam.** It has no app to attach to.

## Design

### 1. The seam: `BaseBootstrapper._attach_teardown_once`

One method on the base owns detection, warning, and skip; the marker name is a
class constant:

```python
class BaseBootstrapper(abc.ABC, typing.Generic[ApplicationT]):
    _TEARDOWN_MARKER: typing.ClassVar[str] = "_lite_bootstrap_teardown_attached"

    def _attach_teardown_once(self, target: object, attach: typing.Callable[[], None]) -> None:
        if getattr(target, self._TEARDOWN_MARKER, False):
            warnings.warn(
                f"The application passed to {type(self).__name__} already has a lite-bootstrap "
                f"teardown hook attached; skipping. This {type(self).__name__}'s teardown will "
                f"not run on shutdown — construct one {type(self).__name__} per application.",
                stacklevel=3,
            )
            return
        setattr(target, self._TEARDOWN_MARKER, True)  # noqa: B010 — documented _lite_bootstrap_ tag
        attach()
```

`stacklevel=3` points the warning at the user's construction site (warn ←
`_attach_teardown_once` ← subclass `__init__` ← user). The warning noun is derived
from `type(self).__name__`, so no per-class label is needed.

### 2. Each framework's `__init__` becomes target + attach thunk

The detection and warning vanish from every subclass; each supplies only its
target and how it attaches:

```python
# FastAPI — target is the app; attach merges the lifespan
self._attach_teardown_once(application, lambda: self._wrap_lifespan(application))

# FastMCP — target is the app; attach adds the provider (still the attach mechanism)
self._attach_teardown_once(
    self.bootstrap_config.application,
    lambda: self.bootstrap_config.application.add_provider(_TeardownProvider(self.teardown)),
)

# Litestar — target is the AppConfig (the built app is slotted); now guarded
self._attach_teardown_once(
    self.bootstrap_config.application_config,
    lambda: self.bootstrap_config.application_config.on_shutdown.append(self.teardown),
)

# FastStream — target is the app; now guarded
self._attach_teardown_once(
    self.bootstrap_config.application,
    lambda: self.bootstrap_config.application.on_shutdown(self.teardown),
)
```

FastAPI's lifespan merge moves to a small `_wrap_lifespan` helper (or stays an
inline lambda). The early-`return`-from-`__init__` guards collapse into the
method's skip; nothing runs after the attach in any subclass `__init__`, so
behavior is preserved.

### 3. Detection unified to the marker; two consequences

Detection becomes one marker on the attach target. A probe confirmed all four
targets accept an arbitrary attribute and are weakref-able — including Litestar's
`AppConfig` (the *built* `Litestar` app is slotted, but it is never the attach
target). Two consequences, on the record:

- **FastMCP** migrates from its structural `isinstance(p, _TeardownProvider)`
  detection to the marker. The `_TeardownProvider` class stays — it is how FastMCP
  *attaches*; it just stops being how FastMCP *detects*.
- **FastAPI**'s marker renames `_lite_bootstrap_lifespan_attached` →
  `_lite_bootstrap_teardown_attached`. It is an internal tag on the user's app, not
  a public symbol, so it renames freely.

### 4. Behavior change: Litestar and FastStream gain the guard

This is the intended effect of the unification, not a side effect. A second
bootstrapper constructed against the same Litestar `AppConfig` / FastStream app now
emits the warning and skips the second attach, instead of silently registering
`teardown` twice. Because `BaseBootstrapper.teardown()` is idempotent
(`test_free_bootstrap.py:117`), the prior double-register was non-fatal but
silent; the new behavior is consistent and observable.

## Operations

None.

## Testing

Test-first. Two layers:

- **Direct unit test of the seam (new — the depth payoff).** On a cheap concrete
  `FreeBootstrapper` (no app), call the inherited `_attach_teardown_once` against a
  dummy `types.SimpleNamespace()` target with a spy thunk: first call runs the
  thunk and sets the marker; second call warns and does **not** run the thunk. No
  framework, no ASGI lifespan.
- **Per-framework "routes through the guard" (uniform).** Each of the four asserts
  the warning fires on a second construction against the same target. FastAPI /
  FastMCP: keep existing double-attach tests, update the `match=` string to the
  unified wording, keep their attach-once assertions (lifespan not re-wrapped /
  single `_TeardownProvider`). Litestar / FastStream: **new** tests asserting the
  warning fires and the hook is registered once (Litestar via
  `len(application_config.on_shutdown)`; FastStream via the warning).

`just test` green at 100%, `just lint-ci` clean (`ty` included).

## Risk

- **Behavior change on Litestar/FastStream (med likelihood × low impact).** Code
  that knowingly constructs two bootstrappers on one app now gets a warning. This
  is the intended consistency, non-fatal (warn + skip), and the first
  bootstrapper's teardown still runs. Called out here and for the retro.
- **FastMCP detection migration (low × med).** Switching structural → marker must
  preserve the tested outcome (second bootstrapper warns, single `_TeardownProvider`
  added). Mitigation: the existing FastMCP double-attach test is retained, only its
  message match updated; the ASGI-lifespan teardown test
  (`test_fastmcp_bootstrap.py:61`) pins that the provider still fires.
- **Marker rename leaving a stale tag (low × low).** `_lite_bootstrap_lifespan_attached`
  disappears; nothing public reads it. Grep confirms it is referenced only in
  FastAPI's own code, its test, and the arch docs (all updated here).
