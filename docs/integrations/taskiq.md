# Usage with Taskiq

There is no Taskiq bootstrapper: a worker uses `FreeBootstrapper`, plus Taskiq's own OpenTelemetry
instrumentation for task spans.

## 1. Install `lite-bootstrap[free-all]` and `taskiq[opentelemetry]`:

=== "uv"

      ```bash
      uv add "lite-bootstrap[free-all]" "taskiq[opentelemetry]"
      ```

=== "pip"

      ```bash
      pip install "lite-bootstrap[free-all]" "taskiq[opentelemetry]"
      ```

=== "poetry"

      ```bash
      poetry add "lite-bootstrap[free-all]" "taskiq[opentelemetry]"
      ```

On free-threaded CPython, install the instrument extras you need instead of `free-all`, with
`otl-http` in place of `otl`, e.g. `lite-bootstrap[sentry,logging,otl-http]`. Read more about
available extras [here](../introduction/installation.md).

## 2. Bootstrap in the worker:

```python
from taskiq import TaskiqEvents, TaskiqState
from taskiq.instrumentation import TaskiqInstrumentor

from lite_bootstrap import FreeBootstrapper, FreeConfig


broker = ...  # your broker


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def bootstrap_observability(state: TaskiqState) -> None:
    state.bootstrapper = FreeBootstrapper(
        FreeConfig(
            service_name="my-worker",
            opentelemetry_endpoint="otl",
            sentry_dsn="https://testdsn@localhost/1",
        )
    )
    state.bootstrapper.bootstrap()
    TaskiqInstrumentor().instrument_broker(broker)


@broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
async def teardown_observability(state: TaskiqState) -> None:
    state.bootstrapper.teardown()
```

`instrument_broker` adds Taskiq's `OpenTelemetryMiddleware` to the broker you already built, and its
spans go to the `TracerProvider` lite-bootstrap has just installed. `TaskiqInstrumentor().instrument()`
is not a substitute: it patches `AsyncBroker.__init__`, so it only reaches brokers built after it runs.

Read more about available configuration options [here](../introduction/configuration.md).

## Client and worker processes

One broker object serves both the processes that send tasks and the `taskiq worker` processes that
run them. The handlers above fire on the worker events only, so a client process is left alone: it
belongs to its own framework's bootstrapper, e.g. `FastAPIBootstrapper` in the web app that calls
`.kiq()`. Bootstrapping when the broker's module is imported would run in that process too, and set
up logging and tracing a second time.

## Metrics

lite-bootstrap has no Taskiq metrics. Taskiq's own `taskiq.middlewares.PrometheusMiddleware`
(`taskiq[metrics]`) provides them, with two side effects to know about: its constructor sets
`PROMETHEUS_MULTIPROC_DIR` for the whole process, and it serves metrics from its own HTTP server on
`server_port` (default `9000`) rather than on `prometheus_metrics_path`.

## Sentry

`sentry-python` has no Taskiq integration, and none is needed for failing tasks: Taskiq's receiver
logs a task's exception with `logger.exception`, which the `LoggingIntegration` lite-bootstrap adds
reports as an error event. Spans and breadcrumbs follow the Sentry configuration as usual.
