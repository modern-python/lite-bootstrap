---
status: accepted
summary: Two deliberate limits of the unified teardown marker — FastMCP detects via attribute not provider scan, and Litestar tags the shareable AppConfig.
supersedes: null
superseded_by: null
---

# Accepted limits of the unified teardown-attach marker

**Decision:** The `_lite_bootstrap_teardown_attached` marker introduced in
[unify-teardown-attach](../changes/2026-06-24.01-unify-teardown-attach.md)
(#130) carries two known limits that we accept rather than design around:
FastMCP detects double-attach via the attribute marker (not a provider-list scan),
and Litestar tags the shared `AppConfig` (not a built app). Both surfaced in the
#130 code review and were judged not worth the added complexity.

## Context

The unified seam `BaseBootstrapper._attach_teardown_once(target, attach)` detects a
second bootstrapper on the same target by tagging the target with one marker
attribute. Two consequences came up in review:

1. **FastMCP detection change.** FastMCP previously detected double-attach
   structurally — `any(isinstance(p, _TeardownProvider) for p in app.providers)` —
   which reads the actual attach state. The unified marker replaces that with an
   attribute on the app. If the app's `providers` list is cleared after the first
   bootstrap while the marker survives, a second bootstrapper warns-and-skips
   instead of re-attaching.
2. **Litestar marker target.** The Litestar app does not exist at `__init__` time
   (it is built later via `Litestar.from_config`), so the attach — and therefore
   the marker — lands on the `application_config` (`AppConfig`). Two `LitestarConfig`
   instances that *share* one `AppConfig` but intend two distinct apps will collide:
   the second warns and skips, and its teardown never runs.

## Decision & rationale

Both are accepted. Rationale, so they are not re-litigated:

- **FastMCP (marker over structural):** uniformity across all four app-bearing
  bootstrappers is worth more than the sliver of state-accuracy the provider scan
  gave. The only scenario the guard exists for — a second bootstrapper on the same
  app — is detected identically by the marker. The regression requires user/framework
  code to mutate `app.providers` *after* bootstrap, which no supported flow does.
  Considered and rejected: keeping FastMCP on a bespoke structural check, which would
  re-fragment detection and defeat the seam's whole point.
- **Litestar (config-level marker):** attaching at config level is the *only* option
  given the app is built lazily; tagging the built app would require restructuring the
  attach to bootstrap time. And sharing one mutable `AppConfig` across two intended
  apps is already broken independently of teardown — instrument bootstrap mutates the
  shared config's `cors_config`, `route_handlers`, and `openapi_config`. The marker
  collision is one symptom of an already-unsupported pattern, not a new hazard. The
  #130 warning text was reworded to name "this application or its configuration" so
  the remediation is accurate.

The genuinely actionable review finding from the same pass — marker set before a
fallible `attach()` — was *fixed* in #130 (mark only after `attach()` succeeds), not
accepted; it is out of scope for this decision.

## Revisit trigger

- **FastMCP:** a supported flow starts mutating `FastMCP.providers` after bootstrap
  (e.g. a documented hot-reload / provider-swap API), making the attribute marker
  diverge from real attach state. Then move FastMCP back to structural detection or
  reconcile the marker with the provider list.
- **Litestar:** sharing one `AppConfig` across multiple apps becomes a supported,
  documented pattern, or the attach is restructured to run at `bootstrap()` time
  (when the app exists). Then tag the built `Litestar` app instead of the config.

## Update (1.4.0)

[double-bootstrap-guard](../changes/2026-08-10.04-double-bootstrap-guard.md) changed
the consequence both scenarios above describe. The FastMCP case is no longer "a
second bootstrapper warns-and-skips instead of re-attaching" — its `bootstrap()`
now raises `ConfigurationError`. The Litestar case is no longer "the second warns
and skips, and its teardown never runs" — its `bootstrap()` raises before any
instrument is applied, so there is nothing left half-wired. The marker and its two
accepted limits are unchanged; only what happens once the marker is hit got louder.
