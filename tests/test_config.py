import dataclasses
import warnings

import pytest

from lite_bootstrap import FastAPIConfig, FastStreamConfig, FreeConfig, LitestarConfig
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
        "opentelemetry_log_traces": True,
        "opentelemetry_instrumentors": [CustomInstrumentor()],
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
        opentelemetry_log_traces=True,
        prometheus_metrics_path="/custom-metrics/",
        sentry_dsn="https://testdsn@localhost/1",
        swagger_offline_docs=True,
    )

    short_config = BaseConfig.from_object(big_config)
    for field in dataclasses.fields(BaseConfig):
        assert getattr(short_config, field.name) == getattr(big_config, field.name)


def test_from_object_skips_none_attribute() -> None:
    @dataclasses.dataclass
    class Source:
        service_name: str | None = None
        service_version: str = "2.0.0"

    config = BaseConfig.from_object(Source())
    assert config.service_name == "micro-service"
    assert config.service_version == "2.0.0"


def test_from_object_skips_missing_attribute() -> None:
    class Source:
        pass

    config = BaseConfig.from_object(Source())
    assert config.service_name == "micro-service"
    assert config.service_version == "1.0.0"
    assert config.service_debug is True


def test_from_object_preserves_falsy_values() -> None:
    @dataclasses.dataclass
    class Source:
        service_name: str = ""
        service_debug: bool = False

    config = BaseConfig.from_object(Source())
    assert config.service_name == ""
    assert config.service_debug is False


def test_from_dict_drops_unknown_keys_silently() -> None:
    config = BaseConfig.from_dict({"service_name": "test", "unknown_key": "value"})
    assert config.service_name == "test"
    assert config.service_version == "1.0.0"


def test_from_dict_explicit_none_overrides_default() -> None:
    config = BaseConfig.from_dict({"service_name": None})
    assert config.service_name is None


@pytest.mark.parametrize("config_cls", [FreeConfig, LitestarConfig, FastStreamConfig, FastAPIConfig])
def test_otel_insecure_warning_fires_through_config_cascade(config_cls: type) -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        config_cls(
            opentelemetry_endpoint="http://collector.example.com:4317",
            opentelemetry_insecure=True,
        )
    matching = [w for w in caught if "unencrypted" in str(w.message)]
    assert matching, f"{config_cls.__name__}: {[str(w.message) for w in caught]}"
