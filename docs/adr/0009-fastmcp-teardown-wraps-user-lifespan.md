# FastMCP teardown wraps the user lifespan

Supersedes [ADR 0001](0001-fastmcp-teardown-via-provider-lifespan.md).

FastMCP 4 enters the user lifespan before entering provider lifespans. The provider approach
therefore shuts down tracing before user shutdown code runs. The bootstrapper wraps the
constructor-supplied lifespan on the existing server and forwards its result to FastMCP.
Teardown runs after that context exits, including when startup or shutdown raises.

FastMCP 4.0.0 through 4.1.6 releases tested here read the private `_lifespan` callable from their lifecycle manager.
This dependency keeps the supplied server instance and applies to transports that share that
manager. The regression exercises the manager through a FastMCP client.

## Breaking changes

Lite-bootstrap teardown runs after FastMCP user lifespan shutdown.
