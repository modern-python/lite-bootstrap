import dataclasses

from opentelemetry.sdk.trace.export import ConsoleSpanExporter

from lite_bootstrap import FastAPIConfig
from lite_bootstrap.instruments.base import BaseConfig
from tests.conftest import CustomInstrumentor


def test_config_from_dict() -> None:
    raw_config = {
        "service_name": "microservice",
        "service_version": "2.0.0",
        "service_environment": "test",
        "service_debug": False,
        "cors_allowed_origins": ["http://test"],
        "health_checks_path": "/custom-health/",
        "logging_buffer_capacity": 0,
        "opentelemetry_endpoint": "otl",
        "opentelemetry_instrumentors": [CustomInstrumentor()],
        "opentelemetry_span_exporter": ConsoleSpanExporter(),
        "prometheus_metrics_path": "/custom-metrics/",
        "sentry_dsn": "https://testdsn@localhost/1",
        "swagger_offline_docs": True,
        "extra_key": "extra_value",
    }
    config = FastAPIConfig.from_dict(raw_config)

    for field in dataclasses.fields(FastAPIConfig):
        if field.name in raw_config:
            assert getattr(config, field.name) == raw_config[field.name]


def test_config_from_object() -> None:
    big_config = FastAPIConfig(
        service_name="microservice",
        service_version="2.0.0",
        service_environment="test",
        service_debug=False,
        cors_allowed_origins=["http://test"],
        health_checks_path="/custom-health/",
        logging_buffer_capacity=0,
        opentelemetry_endpoint="otl",
        opentelemetry_instrumentors=[CustomInstrumentor()],
        opentelemetry_span_exporter=ConsoleSpanExporter(),
        prometheus_metrics_path="/custom-metrics/",
        sentry_dsn="https://testdsn@localhost/1",
        swagger_offline_docs=True,
    )

    short_config = BaseConfig.from_object(big_config)
    for field in dataclasses.fields(BaseConfig):
        assert getattr(short_config, field.name) == getattr(big_config, field.name)
