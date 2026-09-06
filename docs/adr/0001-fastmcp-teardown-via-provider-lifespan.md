# FastMCP teardown attaches through a Provider lifespan

**Decision:** `FastMcpBootstrapper` wires its `teardown` into FastMCP's shutdown by registering a
`_TeardownProvider` via the public `FastMCP.add_provider()`, whose `async def lifespan(self)` runs
teardown on the exit branch. We will not reach into `FastMCP._lifespan`, rebuild the user's
`FastMCP`, or leave teardown manual.

FastMCP is the one supported framework with no `on_shutdown`-shaped hook. `FastMCP.lifespan` is a
bound method on the `AggregateProvider` mixin, not a settable attribute: assigning `app.lifespan`
succeeds and has zero runtime effect, because the transport runners read the private `_lifespan`
attribute that is only set at construction time. `add_provider()` is the sole public,
post-construction hook whose callback is invoked by the server's ASGI lifespan.

Rejected, with the reasoning that would otherwise be re-litigated:

- **Mutate `app._lifespan` directly.** Works today, but it is private API on a fast-moving
  dependency, and a rename ships as a silent no-teardown rather than an error.
- **Rebuild the user's `FastMCP` with a composed `lifespan=`.** Breaks the contract every other
  bootstrapper keeps — the user owns the application object they passed in, and gets the same
  object back.
- **No automatic wiring; document a manual `teardown()` call.** Adopted briefly and reverted once
  `add_provider` was found. It makes FastMCP the only framework where shutdown is the user's job.

The accepted cost is semantic: `Provider` is FastMCP's general extension abstraction for tools,
resources and prompts, and using one purely for a shutdown callback is thin. A one-line comment at
the registration site says so.

**Revisit trigger:** FastMCP grows a first-class shutdown hook (an `on_shutdown` API, or a
documented public way to compose a lifespan post-construction). At that point the provider is the
indirect route and should be replaced by the direct one.
