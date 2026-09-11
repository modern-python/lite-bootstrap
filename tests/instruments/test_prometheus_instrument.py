from lite_bootstrap.instruments.prometheus_instrument import PrometheusConfig, PrometheusInstrument


def test_prometheus_instrument_configured_with_default_path() -> None:
    config = PrometheusConfig()
    assert PrometheusInstrument.is_configured(config)


def test_prometheus_instrument_not_configured_with_empty_path() -> None:
    config = PrometheusConfig(prometheus_metrics_path="")
    assert not PrometheusInstrument.is_configured(config)
    assert PrometheusInstrument.not_configured_reason == "prometheus_metrics_path is empty or not valid"


def test_prometheus_instrument_not_configured_with_invalid_path() -> None:
    # No leading slash → invalid per is_valid_path regex.
    config = PrometheusConfig(prometheus_metrics_path="metrics")
    assert not PrometheusInstrument.is_configured(config)


def test_prometheus_instrument_configured_with_custom_valid_path() -> None:
    config = PrometheusConfig(prometheus_metrics_path="/custom-metrics/")
    assert PrometheusInstrument.is_configured(config)


def test_prometheus_config_defaults() -> None:
    config = PrometheusConfig()
    assert config.prometheus_metrics_path == "/metrics"
    assert config.prometheus_metrics_include_in_schema is False


def test_prometheus_dependencies_installed() -> None:
    assert PrometheusInstrument.dependencies_installed() is True
