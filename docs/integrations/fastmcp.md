# Usage with `FastMCP`

## 1. Install `lite-bootstrap` with the FastMCP extras and any instruments you want:

`lite-bootstrap` does not ship a `fastmcp-all` rollup extra — compose the extras
you need explicitly.

=== "uv"

      ```bash
      uv add 'lite-bootstrap[fastmcp,fastmcp-metrics,sentry,logging,pyroscope]'
      ```

=== "pip"

      ```bash
      pip install 'lite-bootstrap[fastmcp,fastmcp-metrics,sentry,logging,pyroscope]'
      ```

=== "poetry"

      ```bash
      poetry add 'lite-bootstrap[fastmcp,fastmcp-metrics,sentry,logging,pyroscope]'
      ```

Read more about available extras [here](../../../introduction/installation):

## 2. Define bootstrapper config and build your application:

```python
from fastmcp import FastMCP
from lite_bootstrap import FastMcpBootstrapper, FastMcpConfig


bootstrapper_config = FastMcpConfig(
    service_name="microservice",
    service_version="2.0.0",
    service_environment="test",
    sentry_dsn="https://testdsn@localhost/1",
    prometheus_metrics_path="/custom-metrics/",
    health_checks_path="/custom-health/",
    logging_buffer_capacity=0,
)
bootstrapper = FastMcpBootstrapper(bootstrap_config=bootstrapper_config)
application: FastMCP = bootstrapper.bootstrap()


@application.tool
def greet_person(person_name: str) -> str:
    return f"Hello, {person_name}!"
```

Set `logging_turn_off_middleware=True` on the config to disable the per-MCP-message
access log middleware. Set `health_checks_enabled=False` to omit the health route.

## 3. Teardown

`FastMcpBootstrapper` does not wire teardown automatically (FastMCP captures its
lifespan at construction time only). Call `bootstrapper.teardown()` yourself
during shutdown — typically from a `lifespan=` callable you pass to `FastMCP`,
from an ASGI shutdown handler, or via `atexit`:

```python
import contextlib
from fastmcp import FastMCP


@contextlib.asynccontextmanager
async def lifespan(app: FastMCP):
    try:
        yield
    finally:
        bootstrapper.teardown()


bootstrapper_config = FastMcpConfig(
    service_name="microservice",
    application=FastMCP(lifespan=lifespan),
)
bootstrapper = FastMcpBootstrapper(bootstrap_config=bootstrapper_config)
application = bootstrapper.bootstrap()
```

Read more about available configuration options [here](../../../introduction/configuration):
