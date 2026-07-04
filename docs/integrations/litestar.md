# Usage with `Litestar`

*Another example of usage with LiteStar - [litestar-sqlalchemy-template](https://github.com/modern-python/litestar-sqlalchemy-template)*

## 1. Install `lite-bootstrap[litestar-all]`:

=== "uv"

      ```bash
      uv add lite-bootstrap[litestar-all]
      ```

=== "pip"

      ```bash
      pip install lite-bootstrap[litestar-all]
      ```

=== "poetry"

      ```bash
      poetry add lite-bootstrap[litestar-all]
      ```

Read more about available extras [here](../introduction/installation.md).

## 2. Define bootstrapper config and build your application:

```python
from lite_bootstrap import LitestarConfig, LitestarBootstrapper


bootstrapper_config = LitestarConfig(
    service_name="microservice",
    service_version="2.0.0",
    service_environment="test",
    cors_allowed_origins=["http://test"],
    health_checks_path="/custom-health/",
    opentelemetry_endpoint="otl",
    prometheus_metrics_path="/custom-metrics/",
    sentry_dsn="https://testdsn@localhost/1",
    swagger_offline_docs=True,
)
bootstrapper = LitestarBootstrapper(bootstrapper_config)
application = bootstrapper.bootstrap()
```

Read more about available configuration options [here](../introduction/configuration.md).

## Logging

Structlog is integrated via Litestar's `StructlogPlugin`, which makes `request.logger` available in route handlers:

```python
from litestar import Request, get


@get("/items")
async def list_items(request: Request) -> list[str]:
    request.logger.info("listing items")
    return []
```

## Prometheus

`prometheus_group_path` defaults to `True`, so the `path` metric label uses the
route template (`/users/{id}`) instead of the raw URL. This bounds metric
cardinality; without it, parameterized routes mint a new series per distinct
value and grow memory unbounded ([litestar#4891](https://github.com/litestar-org/litestar/issues/4891)).

Set `prometheus_group_path=False` to record raw paths. Anything in
`prometheus_additional_params` (including `group_path`) overrides the default:

```python
LitestarConfig(
    service_name="microservice",
    prometheus_group_path=False,  # raw paths
    prometheus_additional_params={"exclude_unhandled_paths": True},
)
```
