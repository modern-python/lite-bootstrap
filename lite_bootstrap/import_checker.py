from importlib.util import find_spec


is_opentelemetry_installed = find_spec("opentelemetry") is not None
is_sentry_installed = find_spec("sentry_sdk") is not None
is_structlog_installed = find_spec("structlog") is not None
is_prometheus_client_installed = find_spec("prometheus_client") is not None
is_fastapi_installed = find_spec("fastapi") is not None
is_litestar_installed = find_spec("litestar") is not None
is_faststream_installed = find_spec("faststream") is not None
is_prometheus_fastapi_instrumentator_installed = find_spec("prometheus_fastapi_instrumentator") is not None
