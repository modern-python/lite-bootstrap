# Configuration

## Sentry

Sentry integration uses `sentry_sdk` package under the hood.

To bootstrap Sentry, you must provide at least:

- `sentry_dsn` - tells sentry-sdk where to send the events.

Additional parameters can also be supplied through the settings object:

- `sentry_traces_sample_rate` - in the range of 0.0 to 1.0, the percentage chance a given transaction will be sent 
- `sentry_sample_rate` - in the range of 0.0 to 1.0, the sample rate for error events
- `sentry_max_breadcrumbs` - the total amount of breadcrumbs
- `sentry_max_value_length` - the max event payload length
- `sentry_attach_stacktrace` - if True, stack traces are automatically attached to all messages logged
- `sentry_integrations` - list of integrations to enable
- `sentry_tags` - key/value string pairs that are both indexed and searchable
- `sentry_additional_params** - additional params, which will be passed to `sentry_sdk.init`

Read more about sentry_sdk params [here](https://docs.sentry.io/platforms/python/configuration/options/).


## Prometheus

To bootstrap Prometheus, you must provide at least:

- `prometheus_metrics_path`.

Additional parameters:

- `prometheus_metrics_include_in_schema`.

### Prometheus Litestar

Prometheus's integration for Litestar requires `prometheus_client` package.

Additional parameters for Litestar integration:

- `prometheus_additional_params` - passed to `litestar.plugins.prometheus.PrometheusConfig`.

### Prometheus FastStream

Prometheus's integration for FastStream requires `prometheus_client` package.

To bootstrap Prometheus for FastStream, you must provide additionally:

- `prometheus_middleware_cls`.

### Prometheus FastAPI

Prometheus's integration for FastAPI uses `prometheus_fastapi_instrumentator` package.

Additional parameters for FastAPI integration:

- `prometheus_instrumentator_params` - passed to `prometheus_fastapi_instrumentator.Instrumentator`
- `prometheus_instrument_params` - passed to `method Instrumentator(...).instrument`
- `prometheus_expose_params` - passed to `method Instrumentator(...).expose`.


## Opentelemetry

To bootstrap Opentelemetry, you must provide at least:

- `opentelemetry_endpoint`.

Additional parameters:

- `opentelemetry_service_name`
- `opentelemetry_container_name`
- `opentelemetry_endpoint`
- `opentelemetry_namespace`
- `opentelemetry_insecure`
- `opentelemetry_instrumentors`
- `opentelemetry_span_exporter`

Additional parameters for Litestar and FastAPI:

- `opentelemetry_excluded_urls` - by default, heath checks and metrics paths will be excluded.

For FastStream you must provide additionally:

- `opentelemetry_middleware_cls`


## Structlog

To bootstrap Structlog, you must set `service_debug` to False

Additional parameters:

- `logging_log_level`
- `logging_flush_level`
- `logging_buffer_capacity`
- `logging_extra_processors`
- `logging_unset_handlers`.

## CORS

To bootstrap CORS headers, you must provide `cors_allowed_origins` or `cors_allowed_origin_regex`.

Additional params:

- `cors_allowed_methods`
- `cors_allowed_headers`
- `cors_exposed_headers`
- `cors_allowed_credentials`
- `cors_max_age`

## Swagger

To bootstrap swagger, you have the following parameters:

- `swagger_static_path` - path for offline docs static
- `swagger_path`
- `swagger_offline_docs` - option to turn on offline docs.

For Litestar `swagger_path` is required to bootstrap swagger instrument.

## Health checks

To bootstrap Health checks, you must provide set `health_checks_enabled` to True.

Additional params:

- `health_checks_path`
- `health_checks_include_in_schema`
