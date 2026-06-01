from lite_bootstrap.instruments.prometheus_instrument import PrometheusConfig, PrometheusInstrument


def test_prometheus_instrument_ready_with_default_path() -> None:
    instrument = PrometheusInstrument(bootstrap_config=PrometheusConfig())
    assert instrument.is_ready()


def test_prometheus_instrument_not_ready_with_empty_path() -> None:
    instrument = PrometheusInstrument(bootstrap_config=PrometheusConfig(prometheus_metrics_path=""))
    assert not instrument.is_ready()
    assert instrument.not_ready_message == "prometheus_metrics_path is empty or not valid"


def test_prometheus_instrument_not_ready_with_invalid_path() -> None:
    # No leading slash → invalid per is_valid_path regex.
    instrument = PrometheusInstrument(bootstrap_config=PrometheusConfig(prometheus_metrics_path="metrics"))
    assert not instrument.is_ready()


def test_prometheus_instrument_ready_with_custom_valid_path() -> None:
    instrument = PrometheusInstrument(
        bootstrap_config=PrometheusConfig(prometheus_metrics_path="/custom-metrics/"),
    )
    assert instrument.is_ready()


def test_prometheus_config_defaults() -> None:
    config = PrometheusConfig()
    assert config.prometheus_metrics_path == "/metrics"
    assert config.prometheus_metrics_include_in_schema is False


def test_prometheus_check_dependencies() -> None:
    assert PrometheusInstrument.check_dependencies() is True
