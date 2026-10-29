import dataclasses
import types
import typing
from collections.abc import Mapping

import pytest

from lite_bootstrap import ConfigurationError, FastAPIConfig, FastMcpConfig, LitestarConfig
from lite_bootstrap.instruments.base import BaseConfig
from lite_bootstrap.types import UNSET, UnsetType


PARAMS = {"key": "value"}
FIELDS_REMOVED_IN_2_0 = [
    (FastAPIConfig, "prometheus_instrumentator_params"),
    (FastAPIConfig, "prometheus_instrument_params"),
    (FastAPIConfig, "prometheus_expose_params"),
    (FastAPIConfig, "fastapi_logging_middleware_enabled"),
    (FastMcpConfig, "prometheus_instrumentator_params"),
    (FastMcpConfig, "prometheus_instrument_params"),
    (FastMcpConfig, "fastmcp_logging_middleware_enabled"),
    (LitestarConfig, "swagger_extra_params"),
    (LitestarConfig, "litestar_logging_middleware_enabled"),
]


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class RenamingConfig(BaseConfig):
    new_params: dict[str, typing.Any] = dataclasses.field(default_factory=dict)
    _renamed_fields: typing.ClassVar[Mapping[str, str]] = {"old_params": "new_params"}
    old_params: dict[str, typing.Any] | UnsetType = dataclasses.field(default=UNSET, repr=False, compare=False)


@pytest.mark.parametrize(("config_class", "old_name"), FIELDS_REMOVED_IN_2_0)
def test_a_field_name_deprecated_in_1_x_is_rejected(config_class: type[BaseConfig], old_name: str) -> None:
    kwargs: dict[str, typing.Any] = {old_name: PARAMS}
    with pytest.raises(TypeError, match=old_name):
        config_class(**kwargs)


def test_an_old_field_name_sets_the_new_field_and_warns() -> None:
    with pytest.warns(
        DeprecationWarning, match=r"old_params is deprecated.* lite-bootstrap 3\.0; use new_params instead"
    ) as record:
        config = RenamingConfig(old_params=PARAMS)

    assert config.new_params == PARAMS
    assert record[0].filename == __file__


def test_setting_an_old_and_a_new_field_name_together_raises() -> None:
    with pytest.raises(ConfigurationError, match=r"old_params.*new_params"):
        RenamingConfig(old_params=PARAMS, new_params=PARAMS)


def test_from_dict_accepts_an_old_field_name() -> None:
    with pytest.warns(DeprecationWarning, match="old_params"):
        config = RenamingConfig.from_dict({"old_params": PARAMS})

    assert config.new_params == PARAMS


def test_from_object_with_an_old_and_a_new_field_name_raises() -> None:
    settings = types.SimpleNamespace(old_params=PARAMS, new_params={"other": "value"})

    with pytest.raises(ConfigurationError, match=r"old_params.*new_params"):
        RenamingConfig.from_object(settings)


def test_a_config_built_from_an_old_field_name_can_be_replaced() -> None:
    with pytest.warns(DeprecationWarning, match="old_params"):
        config = RenamingConfig(old_params=PARAMS)

    replaced = dataclasses.replace(config, new_params={"other": "value"})

    assert replaced.new_params == {"other": "value"}
