from lite_bootstrap.instruments.healthchecks_instrument import HealthChecksConfig, HealthChecksInstrument


def test_healthchecks_instrument_ready_by_default() -> None:
    instrument = HealthChecksInstrument(bootstrap_config=HealthChecksConfig())
    assert instrument.is_ready()


def test_healthchecks_instrument_not_ready_when_disabled() -> None:
    instrument = HealthChecksInstrument(bootstrap_config=HealthChecksConfig(health_checks_enabled=False))
    assert not instrument.is_ready()
    assert instrument.not_ready_message == "health_checks_enabled is False"


def test_healthchecks_render_data_default() -> None:
    instrument = HealthChecksInstrument(bootstrap_config=HealthChecksConfig())
    data = instrument.render_health_check_data()
    assert data == {
        "service_version": "1.0.0",
        "service_name": "micro-service",
        "health_status": True,
    }


def test_healthchecks_render_data_custom() -> None:
    instrument = HealthChecksInstrument(
        bootstrap_config=HealthChecksConfig(service_name="my-svc", service_version="2.0.0"),
    )
    data = instrument.render_health_check_data()
    assert data == {
        "service_version": "2.0.0",
        "service_name": "my-svc",
        "health_status": True,
    }


def test_healthchecks_config_defaults() -> None:
    config = HealthChecksConfig()
    assert config.health_checks_enabled is True
    assert config.health_checks_path == "/health/"
    assert config.health_checks_include_in_schema is False


def test_healthchecks_check_dependencies() -> None:
    assert HealthChecksInstrument.check_dependencies() is True
