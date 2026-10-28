import asyncio
import time
from unittest.mock import MagicMock

import pytest

from lite_bootstrap.instruments import healthchecks_instrument
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
    assert config.health_checks_probes == {}


def test_healthchecks_dependencies_installed() -> None:
    assert HealthChecksInstrument.dependencies_installed() is True


async def test_healthchecks_probes_run_concurrently() -> None:
    interval = 0.2

    async def slow_probe() -> bool:
        await asyncio.sleep(interval)
        return True

    instrument = HealthChecksInstrument(
        bootstrap_config=HealthChecksConfig(health_checks_probes={"first": slow_probe, "second": slow_probe}),
    )
    started = time.perf_counter()
    assert await instrument.define_health_status()
    assert time.perf_counter() - started < interval * 1.5


async def test_healthchecks_status_is_healthy_without_probes() -> None:
    instrument = HealthChecksInstrument(bootstrap_config=HealthChecksConfig())
    assert await instrument.define_health_status()


def test_healthchecks_render_data_unhealthy() -> None:
    instrument = HealthChecksInstrument(bootstrap_config=HealthChecksConfig())
    assert instrument.render_health_check_data(health_status=False)["health_status"] is False


async def test_healthchecks_status_without_probes_skips_gather(monkeypatch: pytest.MonkeyPatch) -> None:
    gather = MagicMock(side_effect=asyncio.gather)
    monkeypatch.setattr(healthchecks_instrument.asyncio, "gather", gather)
    instrument = HealthChecksInstrument(bootstrap_config=HealthChecksConfig())
    assert await instrument.define_health_status()
    gather.assert_not_called()
