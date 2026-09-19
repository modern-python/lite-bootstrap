# FastMCP teardown attaches through a Provider lifespan

FastMCP is the one supported framework with no `on_shutdown`-shaped hook: `FastMCP.lifespan` is a
bound method on the `AggregateProvider` mixin, so assigning to it succeeds and does nothing — the
transport runners read the private `_lifespan`, set only at construction — which leaves
`add_provider()` as the single public post-construction hook the server's ASGI lifespan actually
invokes. `FastMcpBootstrapper` therefore registers a `_TeardownProvider` whose `lifespan` runs
teardown on the exit branch, accepting that `Provider` is FastMCP's extension abstraction for tools,
resources and prompts and that using one for a shutdown callback is thin.

Rejected: mutating `app._lifespan` (private API on a fast-moving dependency, where a rename ships as
silent no-teardown rather than an error); rebuilding the user's `FastMCP` with a composed `lifespan=`
(every other bootstrapper hands back the object it was given); and documenting a manual `teardown()`
call (adopted briefly, reverted once `add_provider` was found). If FastMCP grows a real shutdown
hook, the provider becomes the indirect route and should be replaced.
