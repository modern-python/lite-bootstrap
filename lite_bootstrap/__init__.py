import typing
from importlib import import_module

from lite_bootstrap.exceptions import (
    BootstrapperNotReadyError,
    ConfigurationError,
    InstrumentDependencyMissingWarning,
    LiteBootstrapError,
    TeardownError,
)


if typing.TYPE_CHECKING:
    from lite_bootstrap.bootstrappers.fastapi_bootstrapper import FastAPIBootstrapper, FastAPIConfig
    from lite_bootstrap.bootstrappers.fastmcp_bootstrapper import FastMcpBootstrapper, FastMcpConfig
    from lite_bootstrap.bootstrappers.faststream_bootstrapper import FastStreamBootstrapper, FastStreamConfig
    from lite_bootstrap.bootstrappers.free_bootstrapper import FreeBootstrapper, FreeConfig
    from lite_bootstrap.bootstrappers.litestar_bootstrapper import LitestarBootstrapper, LitestarConfig
    from lite_bootstrap.instruments.pyroscope_instrument import PyroscopeConfig, PyroscopeInstrument


__all__ = [
    "BootstrapperNotReadyError",
    "ConfigurationError",
    "FastAPIBootstrapper",
    "FastAPIConfig",
    "FastMcpBootstrapper",
    "FastMcpConfig",
    "FastStreamBootstrapper",
    "FastStreamConfig",
    "FreeBootstrapper",
    "FreeConfig",
    "InstrumentDependencyMissingWarning",
    "LiteBootstrapError",
    "LitestarBootstrapper",
    "LitestarConfig",
    "PyroscopeConfig",
    "PyroscopeInstrument",
    "TeardownError",
]


_LAZY_EXPORTS = {
    "FastAPIBootstrapper": "bootstrappers.fastapi_bootstrapper",
    "FastAPIConfig": "bootstrappers.fastapi_bootstrapper",
    "FastMcpBootstrapper": "bootstrappers.fastmcp_bootstrapper",
    "FastMcpConfig": "bootstrappers.fastmcp_bootstrapper",
    "FastStreamBootstrapper": "bootstrappers.faststream_bootstrapper",
    "FastStreamConfig": "bootstrappers.faststream_bootstrapper",
    "FreeBootstrapper": "bootstrappers.free_bootstrapper",
    "FreeConfig": "bootstrappers.free_bootstrapper",
    "LitestarBootstrapper": "bootstrappers.litestar_bootstrapper",
    "LitestarConfig": "bootstrappers.litestar_bootstrapper",
    "PyroscopeConfig": "instruments.pyroscope_instrument",
    "PyroscopeInstrument": "instruments.pyroscope_instrument",
}


def __getattr__(name: str) -> typing.Any:  # noqa: ANN401
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        msg = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(msg)
    exported = getattr(import_module(f".{module_name}", __name__), name)
    globals()[name] = exported
    return exported


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
