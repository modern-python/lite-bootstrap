# The teardown-attach guard is an attribute marker, and its two limits are accepted

`BaseBootstrapper._attach_teardown_once` detects a second bootstrapper by tagging the attach target
with `_lite_bootstrap_teardown_attached`, so the "attached" bit lives exactly as long as the
application it describes — rather than in a class-level registry or `WeakSet`, which would mean
process-global mutable state and would contradict the `_lite_bootstrap_*` tagging convention the
codebase already follows. The target is tagged only after `attach()` returns, and since #167 hitting
the marker raises `ConfigurationError` from `bootstrap()` rather than warning and leaving a half-wired
application.

Two consequences are accepted rather than designed around:

- **FastMCP detects via the marker, not by scanning `app.providers`.** If that list is cleared after
  the first bootstrap, the second bootstrapper is refused instead of re-attaching. No supported flow
  mutates it, and uniformity across the four app-bearing bootstrappers is worth more than the sliver
  of state-accuracy the structural check gave.
- **Litestar tags the shared `AppConfig`**, because the app does not exist until
  `Litestar.from_config()`. Two configs sharing one `AppConfig` collide — but that pattern is already
  broken independently, since instrument bootstrap mutates the shared config's `cors_config`,
  `route_handlers` and `openapi_config`.
