from lite_bootstrap.instruments.healthchecks_instrument import HealthChecksConfig, HealthChecksInstrument


def test_healthchecks_instrument_configured_by_default() -> None:
    config = HealthChecksConfig()
    assert HealthChecksInstrument.is_configured(config)


def test_healthchecks_instrument_not_configured_when_disabled() -> None:
    config = HealthChecksConfig(health_checks_enabled=False)
    assert not HealthChecksInstrument.is_configured(config)
    assert HealthChecksInstrument.not_configured_reason == "health_checks_enabled is False"


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


def test_healthchecks_dependencies_installed() -> None:
    assert HealthChecksInstrument.dependencies_installed() is True
