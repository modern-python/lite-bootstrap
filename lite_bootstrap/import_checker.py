from importlib.util import find_spec


def _safe_find_spec(module_name: str) -> bool:
    """Return whether a dotted module is importable, treating a missing parent as absent.

    find_spec imports the dotted name's parent first; a present-but-incomplete
    namespace (e.g. opentelemetry-api installed without opentelemetry-instrumentation)
    otherwise raises ModuleNotFoundError, crashing `import lite_bootstrap`.
    """
    try:
        return find_spec(module_name) is not None
    except ModuleNotFoundError:
        return False


is_opentelemetry_installed = find_spec("opentelemetry") is not None
# opentelemetry-api provides the `opentelemetry` namespace (trace, metrics) without the
# sdk. The OTel instrument imports opentelemetry.sdk.* and needs this stricter check;
# api-only consumers (logging trace-injection, framework get_tracer_provider) use the
# flag above.
is_opentelemetry_sdk_installed = _safe_find_spec("opentelemetry.sdk")
is_sentry_installed = find_spec("sentry_sdk") is not None
is_structlog_installed = find_spec("structlog") is not None
is_prometheus_client_installed = find_spec("prometheus_client") is not None
is_fastapi_installed = find_spec("fastapi") is not None
is_litestar_installed = find_spec("litestar") is not None
is_faststream_installed = find_spec("faststream") is not None
is_prometheus_fastapi_instrumentator_installed = find_spec("prometheus_fastapi_instrumentator") is not None
is_fastapi_opentelemetry_installed = is_opentelemetry_installed and _safe_find_spec(
    "opentelemetry.instrumentation.fastapi"
)
is_litestar_opentelemetry_installed = (
    is_opentelemetry_installed and is_litestar_installed and _safe_find_spec("opentelemetry.instrumentation.asgi")
)
is_otlp_grpc_exporter_installed = _safe_find_spec("opentelemetry.exporter.otlp.proto.grpc.trace_exporter")
is_otlp_http_exporter_installed = _safe_find_spec("opentelemetry.exporter.otlp.proto.http.trace_exporter")
is_pyroscope_installed = find_spec("pyroscope") is not None
is_fastmcp_installed = find_spec("fastmcp") is not None
is_orjson_installed = find_spec("orjson") is not None
