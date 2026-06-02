from lite_bootstrap.instruments.swagger_instrument import SwaggerConfig, SwaggerInstrument


def test_swagger_instrument_configured_by_default() -> None:
    config = SwaggerConfig()
    assert SwaggerInstrument.is_configured(config)


def test_swagger_config_defaults() -> None:
    config = SwaggerConfig()
    assert config.swagger_static_path == "/static"
    assert config.swagger_path == "/docs"
    assert config.swagger_offline_docs is False


def test_swagger_check_dependencies() -> None:
    assert SwaggerInstrument.check_dependencies() is True
