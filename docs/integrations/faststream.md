# Usage with `FastStream`

## 1. Install `lite-bootstrapp[faststream-all]`:

=== "uv"

      ```bash
      uv add lite-bootstrapp[faststream-all]
      ```

=== "pip"

      ```bash
      pip install lite-bootstrapp[faststream-all]
      ```

=== "poetry"

      ```bash
      poetry add lite-bootstrapp[faststream-all]
      ```

Read more about available extras [here](../../../introduction/installation):

## 2. Define bootstrapper config and build you application:

```python
from lite_bootstrap import FastStreamConfig, FastStreamBootstrapper
from faststream.redis.opentelemetry import RedisTelemetryMiddleware
from faststream.redis.prometheus import RedisPrometheusMiddleware
from faststream.redis import RedisBroker


broker = RedisBroker()
bootstrapper_config = FastStreamConfig(
    service_name="microservice",
    service_version="2.0.0",
    service_environment="test",
    service_debug=False,
    opentelemetry_endpoint="otl",
    opentelemetry_middleware_cls=RedisTelemetryMiddleware,
    prometheus_metrics_path="/custom-metrics/",
    prometheus_middleware_cls=RedisPrometheusMiddleware,
    sentry_dsn="https://testdsn@localhost/1",
    health_checks_path="/custom-health/",
    logging_buffer_capacity=0,
    broker=broker,
)
bootstrapper = FastStreamBootstrapper(bootstrapper_config)
application = bootstrapper.bootstrap()
```

Read more about available configuration options [here](../../../introduction/configuration):
