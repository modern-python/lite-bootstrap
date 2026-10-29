from lite_bootstrap.instruments.base import BaseConfig, BaseInstrument


def test_base_instrument_defaults() -> None:
    assert BaseInstrument.not_configured_reason == ""
    assert BaseInstrument.missing_dependency_message == ""
    assert BaseInstrument.dependencies_installed() is True
    assert BaseInstrument.is_configured(BaseConfig()) is True
