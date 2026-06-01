# Usage with `FastMCP`

## 1. Install `lite-bootstrap[fastmcp-all]`:

=== "uv"

      ```bash
      uv add lite-bootstrap[fastmcp-all]
      ```

=== "pip"

      ```bash
      pip install lite-bootstrap[fastmcp-all]
      ```

=== "poetry"

      ```bash
      poetry add lite-bootstrap[fastmcp-all]
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

Teardown is wired through FastMCP's provider lifecycle — `bootstrapper.teardown()`
runs automatically when the FastMCP server's ASGI lifespan shuts down (i.e. when
the application that serves `application.http_app()` shuts down).

Read more about available configuration options [here](../../../introduction/configuration):
