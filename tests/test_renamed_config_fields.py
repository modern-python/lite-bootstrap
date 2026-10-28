import dataclasses
import types
import typing

import pytest

from lite_bootstrap import ConfigurationError, FastAPIConfig, FastMcpConfig, LitestarConfig
from lite_bootstrap.instruments.base import BaseConfig


PARAMS = {"key": "value"}
RENAMED_FIELDS = [
    (FastAPIConfig, "prometheus_instrumentator_params", "prometheus_instrumentator_additional_params", PARAMS),
    (FastAPIConfig, "prometheus_instrument_params", "prometheus_instrument_additional_params", PARAMS),
    (FastAPIConfig, "prometheus_expose_params", "prometheus_expose_additional_params", PARAMS),
    (FastAPIConfig, "fastapi_logging_middleware_enabled", "logging_access_log_enabled", True),
    (FastMcpConfig, "prometheus_instrumentator_params", "prometheus_instrumentator_additional_params", PARAMS),
    (FastMcpConfig, "prometheus_instrument_params", "prometheus_instrument_additional_params", PARAMS),
    (FastMcpConfig, "fastmcp_logging_middleware_enabled", "logging_access_log_enabled", True),
    (LitestarConfig, "swagger_extra_params", "swagger_additional_params", PARAMS),
    (LitestarConfig, "litestar_logging_middleware_enabled", "logging_access_log_enabled", True),
]


@pytest.mark.parametrize(("config_class", "old_name", "new_name", "value"), RENAMED_FIELDS)
def test_an_old_field_name_sets_the_new_field_and_warns(
    config_class: type[BaseConfig],
    old_name: str,
    new_name: str,
    value: object,
) -> None:
    kwargs: dict[str, typing.Any] = {old_name: value}
    with pytest.warns(DeprecationWarning, match=f"{old_name} is deprecated.*; use {new_name} instead") as record:
        config = config_class(**kwargs)

    assert getattr(config, new_name) == value
    assert record[0].filename == __file__


@pytest.mark.parametrize(("config_class", "old_name", "new_name", "value"), RENAMED_FIELDS)
def test_setting_an_old_and_a_new_field_name_together_raises(
    config_class: type[BaseConfig],
    old_name: str,
    new_name: str,
    value: object,
) -> None:
    kwargs: dict[str, typing.Any] = {old_name: value, new_name: value}
    with pytest.raises(ConfigurationError, match=f"{old_name}.*{new_name}"):
        config_class(**kwargs)


@pytest.mark.parametrize(("config_class", "old_name", "new_name", "value"), RENAMED_FIELDS)
def test_from_dict_accepts_an_old_field_name(
    config_class: type[BaseConfig],
    old_name: str,
    new_name: str,
    value: object,
) -> None:
    with pytest.warns(DeprecationWarning, match=old_name):
        config = config_class.from_dict({old_name: value})

    assert getattr(config, new_name) == value


def test_from_object_with_an_old_and_a_new_field_name_raises() -> None:
    settings = types.SimpleNamespace(swagger_extra_params=PARAMS, swagger_additional_params={"other": "value"})

    with pytest.raises(ConfigurationError, match=r"swagger_extra_params.*swagger_additional_params"):
        LitestarConfig.from_object(settings)


def test_a_config_built_from_an_old_field_name_can_be_replaced() -> None:
    with pytest.warns(DeprecationWarning, match="swagger_extra_params"):
        config = LitestarConfig(swagger_extra_params=PARAMS)

    replaced = dataclasses.replace(config, swagger_additional_params={"other": "value"})

    assert replaced.swagger_additional_params == {"other": "value"}
