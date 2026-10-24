# Usage with `FastStream`

## 1. Install `lite-bootstrap[faststream-all]`:

=== "uv"

      ```bash
      uv add "lite-bootstrap[faststream-all]"
      ```

=== "pip"

      ```bash
      pip install "lite-bootstrap[faststream-all]"
      ```

=== "poetry"

      ```bash
      poetry add "lite-bootstrap[faststream-all]"
      ```

Read more about available extras [here](../introduction/installation.md).

## 2. Define bootstrapper config and build your application:

```python
from lite_bootstrap import FastStreamConfig, FastStreamBootstrapper
from faststream.asgi import AsgiFastStream
from faststream.redis.opentelemetry import RedisTelemetryMiddleware
from faststream.redis.prometheus import RedisPrometheusMiddleware
from faststream.redis import RedisBroker


broker = RedisBroker()
bootstrapper_config = FastStreamConfig(
    service_name="microservice",
    service_version="2.0.0",
    service_environment="test",
    opentelemetry_endpoint="otl",
    opentelemetry_middleware_cls=RedisTelemetryMiddleware,
    prometheus_metrics_path="/custom-metrics/",
    prometheus_middleware_cls=RedisPrometheusMiddleware,
    sentry_dsn="https://testdsn@localhost/1",
    health_checks_path="/custom-health/",
    logging_buffer_capacity=0,
    application=AsgiFastStream(broker),
)
bootstrapper = FastStreamBootstrapper(bootstrapper_config)
application = bootstrapper.bootstrap()
```

Read more about available configuration options [here](../introduction/configuration.md).

## Multiple brokers

Tracing, metrics and logging cover every broker the application has when `bootstrap()` runs. Add
brokers with `add_broker` before calling `bootstrap()`: a broker added later is not instrumented.

Each FastStream middleware class handles one broker type. A single class in
`opentelemetry_middleware_cls` or `prometheus_middleware_cls` goes on every broker of the first
broker's type. For an application with brokers of different types, pass a mapping from broker class
to middleware class:

```python
from faststream.kafka import KafkaBroker
from faststream.kafka.opentelemetry import KafkaTelemetryMiddleware
from faststream.kafka.prometheus import KafkaPrometheusMiddleware
from faststream.redis import RedisBroker
from faststream.redis.opentelemetry import RedisTelemetryMiddleware
from faststream.redis.prometheus import RedisPrometheusMiddleware


application = AsgiFastStream(KafkaBroker(), RedisBroker())
bootstrapper_config = FastStreamConfig(
    service_name="microservice",
    opentelemetry_endpoint="otl",
    opentelemetry_middleware_cls={
        KafkaBroker: KafkaTelemetryMiddleware,
        RedisBroker: RedisTelemetryMiddleware,
    },
    prometheus_middleware_cls={
        KafkaBroker: KafkaPrometheusMiddleware,
        RedisBroker: RedisPrometheusMiddleware,
    },
    application=application,
)
```

A broker whose type has no middleware class is left uninstrumented, and `bootstrap()` warns with its
type name.

All brokers share one Prometheus registry. Each metric's `broker` label holds the messaging system,
such as `kafka` or `redis`, so it separates a Kafka broker from a Redis broker. Two brokers on the same
system get the same label, and if both have a handler with the same name, their counts merge into
one series.
