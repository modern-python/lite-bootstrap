import asyncio
from unittest.mock import MagicMock

import pytest

from lite_bootstrap.instruments import healthchecks_instrument
from lite_bootstrap.instruments.healthchecks_instrument import HealthChecksConfig, HealthChecksInstrument, HealthProbe
from tests.conftest import ProbeError, failing_probe, passing_probe, raising_probe


def test_healthchecks_instrument_configured_by_default() -> None:
    config = HealthChecksConfig()
    assert HealthChecksInstrument.is_configured(config)


def test_healthchecks_instrument_not_configured_when_disabled() -> None:
    config = HealthChecksConfig(health_checks_enabled=False)
    assert not HealthChecksInstrument.is_configured(config)
    assert (
        HealthChecksInstrument.not_configured_reason == "health_checks_enabled is False or health_checks_path is empty"
    )


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


async def test_healthchecks_probes_run_concurrently() -> None:
    first_started = asyncio.Event()
    second_started = asyncio.Event()

    async def first() -> bool:
        first_started.set()
        await second_started.wait()
        return True

    async def second() -> bool:
        await first_started.wait()
        second_started.set()
        return True

    instrument = HealthChecksInstrument(
        bootstrap_config=HealthChecksConfig(health_checks_probes={"first": first, "second": second}),
    )
    assert await asyncio.wait_for(instrument.define_health_status(), timeout=5)


@pytest.mark.parametrize(
    ("probe", "expected_message", "expected_exception"),
    [
        pytest.param(failing_probe, "Health probe cache failed", None, id="returns-false"),
        pytest.param(raising_probe, "Health probe cache raised", ProbeError, id="raises"),
    ],
)
async def test_failed_probe_makes_health_unhealthy_and_warns(
    probe: HealthProbe,
    expected_message: str,
    expected_exception: type[Exception] | None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    instrument = HealthChecksInstrument(
        bootstrap_config=HealthChecksConfig(health_checks_probes={"db": passing_probe, "cache": probe}),
    )

    assert not await instrument.define_health_status()

    [record] = [record for record in caplog.records if record.name == healthchecks_instrument.__name__]
    assert record.getMessage() == expected_message
    if expected_exception is None:
        assert record.exc_info is None
    else:
        assert record.exc_info
        assert isinstance(record.exc_info[1], expected_exception)


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
