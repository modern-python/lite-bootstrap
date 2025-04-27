# Usage with `Litestar`

*Another example of usage with LiteStar - [litestar-sqlalchemy-template](https://github.com/modern-python/litestar-sqlalchemy-template)*

## 1. Install `lite-bootstrap[litestar-all]`:

=== "uv"

      ```bash
      uv add lite-bootstrapp[litestar-all]
      ```

=== "pip"

      ```bash
      pip install lite-bootstrapp[litestar-all]
      ```

=== "poetry"

      ```bash
      poetry add lite-bootstrapp[litestar-all]
      ```

Read more about available extras [here](../../../introduction/installation):

## 2. Define bootstrapper config and build you application:

```python
from lite_bootstrap import LitestarConfig, LitestarBootstrapper


bootstrapper_config = LitestarConfig(
    service_name="microservice",
    service_version="2.0.0",
    service_environment="test",
    service_debug=False,
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

Read more about available configuration options [here](../../../introduction/configuration):
