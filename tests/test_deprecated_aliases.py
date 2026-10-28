import types
import warnings

import pytest

import lite_bootstrap
from lite_bootstrap.bootstrappers import free_bootstrapper
from lite_bootstrap.instruments import logging_factory, logging_instrument, opentelemetry_instrument, sentry_instrument


# Tests elsewhere reload instrument modules, so a replacement is looked up when the test runs.
DEPRECATED_ALIASES = [
    (opentelemetry_instrument, "OpentelemetryConfig", opentelemetry_instrument, "OpenTelemetryConfig"),
    (free_bootstrapper, "FreeBootstrapperConfig", free_bootstrapper, "FreeConfig"),
    (lite_bootstrap, "FreeBootstrapperConfig", free_bootstrapper, "FreeConfig"),
    (sentry_instrument, "IGNORED_STRUCTLOG_ATTRIBUTES", logging_factory, "STRUCTLOG_META_KEYS"),
]
DEPRECATED_PROTOCOLS = ["AddressProtocol", "RequestProtocol", "ScopeType"]
MODULES_WITH_DEPRECATIONS = [
    lite_bootstrap,
    free_bootstrapper,
    logging_factory,
    logging_instrument,
    opentelemetry_instrument,
    sentry_instrument,
]


@pytest.mark.parametrize(("module", "name", "replacement_module", "replacement"), DEPRECATED_ALIASES)
def test_a_deprecated_alias_warns_and_still_resolves(
    module: types.ModuleType,
    name: str,
    replacement_module: types.ModuleType,
    replacement: str,
) -> None:
    with pytest.warns(DeprecationWarning, match=f"{name} is deprecated.*; use {replacement} instead") as record:
        resolved = getattr(module, name)

    assert resolved is getattr(replacement_module, replacement)
    assert record[0].filename == __file__


@pytest.mark.parametrize("module", [logging_factory, logging_instrument])
@pytest.mark.parametrize("name", DEPRECATED_PROTOCOLS)
def test_an_unused_logging_protocol_warns_and_still_resolves(module: types.ModuleType, name: str) -> None:
    with pytest.warns(DeprecationWarning, match=f"{name} is deprecated.*; nothing replaces it"):
        resolved = getattr(module, name)

    assert resolved is not None


@pytest.mark.parametrize("module", MODULES_WITH_DEPRECATIONS)
def test_an_unknown_attribute_still_raises_attribute_error(module: types.ModuleType) -> None:
    with pytest.raises(AttributeError, match="no_such_name"):
        _ = module.no_such_name


@pytest.mark.parametrize("module", MODULES_WITH_DEPRECATIONS)
def test_a_star_import_does_not_warn(module: types.ModuleType) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        exec(f"from {module.__name__} import *", {})  # noqa: S102
