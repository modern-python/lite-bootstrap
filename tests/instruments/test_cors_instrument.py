import pytest

from lite_bootstrap.exceptions import ConfigurationError
from lite_bootstrap.instruments.cors_instrument import CorsConfig, CorsInstrument


def test_cors_instrument_not_configured_without_origins_or_regex() -> None:
    config = CorsConfig()
    assert not CorsInstrument.is_configured(config)
    assert CorsInstrument.not_ready_message == "cors_allowed_origins or cors_allowed_origin_regex must be provided"


def test_cors_instrument_configured_with_origins() -> None:
    config = CorsConfig(cors_allowed_origins=["http://test"])
    assert CorsInstrument.is_configured(config)


def test_cors_instrument_configured_with_regex() -> None:
    config = CorsConfig(cors_allowed_origin_regex=r"https?://.*")
    assert CorsInstrument.is_configured(config)


def test_cors_instrument_configured_with_both() -> None:
    config = CorsConfig(
        cors_allowed_origins=["http://test"],
        cors_allowed_origin_regex=r"https?://.*",
    )
    assert CorsInstrument.is_configured(config)


def test_cors_instrument_config_defaults() -> None:
    config = CorsConfig()
    assert config.cors_allowed_origins == []
    assert config.cors_allowed_methods == []
    assert config.cors_allowed_headers == []
    assert config.cors_exposed_headers == []
    assert config.cors_allowed_credentials is False
    assert config.cors_allowed_origin_regex is None
    expected_max_age = 600
    assert config.cors_max_age == expected_max_age


def test_cors_check_dependencies() -> None:
    assert CorsInstrument.check_dependencies() is True


@pytest.mark.parametrize(
    ("origins", "regex"),
    [
        (["*"], None),
        ([], ".*"),
        ([], r".+"),
        (["*", "http://safe.example.com"], None),
    ],
)
def test_cors_config_rejects_wildcard_with_credentials(origins: list[str], regex: str | None) -> None:
    with pytest.raises(ConfigurationError, match="Unsafe CORS"):
        CorsConfig(
            cors_allowed_origins=origins,
            cors_allowed_origin_regex=regex,
            cors_allowed_credentials=True,
        )


def test_cors_config_accepts_credentials_with_explicit_origins() -> None:
    config = CorsConfig(
        cors_allowed_origins=["http://example.com"],
        cors_allowed_credentials=True,
    )
    assert config.cors_allowed_credentials is True


def test_cors_config_accepts_wildcard_without_credentials() -> None:
    config = CorsConfig(
        cors_allowed_origins=["*"],
        cors_allowed_credentials=False,
    )
    assert config.cors_allowed_origins == ["*"]
