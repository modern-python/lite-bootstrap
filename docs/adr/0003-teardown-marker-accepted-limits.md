# The teardown-attach guard is an attribute marker, and its two limits are accepted

**Decision:** `BaseBootstrapper._attach_teardown_once` detects a second bootstrapper by tagging the
attach target with the `_lite_bootstrap_teardown_attached` attribute (#130). Two consequences of
that choice — FastMCP detecting via the attribute rather than a provider-list scan, and Litestar
tagging the shared `AppConfig` rather than a built app — are accepted rather than designed around.

## Why an attribute on the target

Rejected: **a class-level registry or `WeakSet` of already-attached applications.** It would
contradict the `_lite_bootstrap_*` app-tagging convention the codebase already follows, and it
introduces process-global mutable state with the test-isolation hazards that come with it. The
marker keeps the "attached" bit local to the application's own lifetime, which is exactly the
lifetime the fact is true for.

Rejected: **a free-function helper module.** The guard is bootstrapper-lifecycle logic and belongs on
`BaseBootstrapper` next to `teardown()`, where `type(self).__name__` is available for the warning.

## The two accepted limits

1. **FastMCP detects via the marker, not structurally.** FastMCP previously detected double-attach
   by scanning `any(isinstance(p, _TeardownProvider) for p in app.providers)`, which reads the actual
   attach state. If the providers list is cleared after the first bootstrap while the marker
   survives, the second bootstrapper is refused rather than re-attaching. Accepted: uniformity across
   all four app-bearing bootstrappers is worth more than the sliver of state-accuracy the scan gave,
   the only scenario the guard exists for is detected identically either way, and the regression
   requires user or framework code to mutate `app.providers` after bootstrap, which no supported flow
   does. Keeping FastMCP on a bespoke structural check would re-fragment detection and defeat the
   seam's whole point.

2. **Litestar tags the `AppConfig`.** The Litestar app does not exist at `__init__` time — it is
   built later by `Litestar.from_config()` — so the attach, and therefore the marker, lands on
   `application_config`. Two `LitestarConfig` instances that *share* one `AppConfig` but intend two
   distinct apps will collide. Accepted: config-level is the only option while the app is built
   lazily, and sharing one mutable `AppConfig` across two intended apps is already broken
   independently of teardown — instrument bootstrap mutates the shared config's `cors_config`,
   `route_handlers` and `openapi_config`. The marker collision is one symptom of an
   already-unsupported pattern, not a new hazard.

The genuinely actionable finding from the same review — the marker being set before a fallible
`attach()` — was *fixed*, not accepted: the target is tagged only after `attach()` returns.

Since #167 the consequence of hitting the marker is louder in both cases: the losing bootstrapper's
`bootstrap()` raises `ConfigurationError` before any instrument is applied, rather than warning and
leaving a half-wired application whose teardown never runs. The marker and these two limits are
unchanged.

**Revisit trigger:** for FastMCP, a supported flow starts mutating `FastMCP.providers` after
bootstrap (a documented hot-reload or provider-swap API), making the attribute diverge from real
attach state — then move back to structural detection or reconcile the two. For Litestar, sharing one
`AppConfig` across multiple apps becomes a supported pattern, or the attach is restructured to run at
`bootstrap()` time when the app exists — then tag the built `Litestar` app instead.
