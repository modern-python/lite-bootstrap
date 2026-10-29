import types

import pytest

import lite_bootstrap
from lite_bootstrap.bootstrappers import free_bootstrapper
from lite_bootstrap.helpers.warn import deprecated_module_getattr
from lite_bootstrap.instruments import logging_factory, logging_instrument, opentelemetry_instrument, sentry_instrument


REMOVED_PROTOCOLS = ["AddressProtocol", "RequestProtocol", "ScopeType"]
NAMES_REMOVED_IN_2_0 = [
    (opentelemetry_instrument, "OpentelemetryConfig"),
    (free_bootstrapper, "FreeBootstrapperConfig"),
    (lite_bootstrap, "FreeBootstrapperConfig"),
    (sentry_instrument, "IGNORED_STRUCTLOG_ATTRIBUTES"),
    *[(module, name) for module in (logging_factory, logging_instrument) for name in REMOVED_PROTOCOLS],
]
TARGET = object()
module_getattr = deprecated_module_getattr("some.module", {"OldName": (TARGET, "NewName"), "GoneName": (TARGET, None)})


@pytest.mark.parametrize(("module", "name"), NAMES_REMOVED_IN_2_0)
def test_a_name_deprecated_in_1_x_is_gone(module: types.ModuleType, name: str) -> None:
    with pytest.raises(AttributeError, match=name):
        getattr(module, name)


def test_a_deprecated_alias_warns_and_still_resolves() -> None:
    with pytest.warns(
        DeprecationWarning, match=r"OldName is deprecated.* lite-bootstrap 3\.0; use NewName instead"
    ) as record:
        resolved = module_getattr("OldName")

    assert resolved is TARGET
    assert record[0].filename == __file__


def test_a_deprecated_alias_without_a_replacement_says_so() -> None:
    with pytest.warns(DeprecationWarning, match="GoneName is deprecated.*; nothing replaces it"):
        assert module_getattr("GoneName") is TARGET


def test_an_unknown_attribute_still_raises_attribute_error() -> None:
    with pytest.raises(AttributeError, match=r"module 'some\.module' has no attribute 'no_such_name'"):
        module_getattr("no_such_name")
