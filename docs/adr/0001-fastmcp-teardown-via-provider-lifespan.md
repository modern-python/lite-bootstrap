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

## FastMCP 4 fired the trigger, and the replacement was rejected

FastMCP 4 added `FastMCP.add_extension(extension: ServerExtension)`, whose
`ServerExtension.lifespan()` is documented as "A context manager entered with the server's lifespan,
exited on shutdown", to "start and stop resources an extension owns". That is literally the second
clause of this ADR's original trigger, "a documented public way to compose a lifespan
post-construction". The first clause did not fire: `on_shutdown` and `on_startup` are still absent
in 4.0.3.

Rejected: **switch `_TeardownProvider` to a `ServerExtension`.** It trades a thin misuse for a
client-visible one. `ServerExtension.identifier` is a required reverse-DNS string, validated at
registration, and its own comment states it is "advertised under `ServerCapabilities.extensions`".
Registering one purely for a shutdown callback would announce a protocol capability the bootstrapper
does not implement, where the `Provider` route's thinness is invisible outside the process. A
teardown hook must not change what the server tells its clients it can do.

Reinforcing it: the `fastmcp` extra declares an unbounded `"fastmcp"`, so `ServerExtension` may not
exist at runtime. Adopting it would force a `fastmcp>=4` floor on an optional extra to buy a
semantically worse hook.

**Revisit trigger:** FastMCP grows a shutdown hook that is neither client-visible nor tied to
another abstraction's semantics, most likely an `on_shutdown` API. `add_extension` does not qualify
and should not be revisited on version bumps alone.
