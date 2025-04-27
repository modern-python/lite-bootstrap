# Usage with `Fastapi`

*Another example of usage with FastAPI - [fastapi-sqlalchemy-template](https://github.com/modern-python/fastapi-sqlalchemy-template)*

## 1. Install `lite-bootstrapp[fastapi-all]`:

=== "uv"
 
      ```bash
      uv add lite-bootstrapp[fastapi-all]
      ```
 
=== "pip"

      ```bash
      pip install lite-bootstrapp[fastapi-all]
      ```

=== "poetry"

      ```bash
      poetry add lite-bootstrapp[fastapi-all]
      ```

Read more about available extras [here](../../../introduction/installation):

## 2. Define bootstrapper config and build you application:

```python
from lite_bootstrap import FastAPIConfig, FastAPIBootstrapper


bootstrapper_config = FastAPIConfig(
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
bootstrapper = FastAPIBootstrapper(bootstrapper_config)
application = bootstrapper.bootstrap()
```

Read more about available configuration options [here](../../../introduction/configuration):
