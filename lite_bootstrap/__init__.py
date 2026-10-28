import typing

from lite_bootstrap.bootstrappers.fastapi_bootstrapper import FastAPIBootstrapper, FastAPIConfig
from lite_bootstrap.bootstrappers.fastmcp_bootstrapper import FastMcpBootstrapper, FastMcpConfig
from lite_bootstrap.bootstrappers.faststream_bootstrapper import FastStreamBootstrapper, FastStreamConfig
from lite_bootstrap.bootstrappers.free_bootstrapper import FreeBootstrapper, FreeConfig
from lite_bootstrap.bootstrappers.litestar_bootstrapper import LitestarBootstrapper, LitestarConfig
from lite_bootstrap.exceptions import (
    BootstrapperNotReadyError,
    ConfigurationError,
    InstrumentDependencyMissingWarning,
    InstrumentSkippedWarning,
    LiteBootstrapError,
    TeardownError,
)
from lite_bootstrap.helpers.warn import deprecated_module_getattr
from lite_bootstrap.instruments.pyroscope_instrument import PyroscopeConfig, PyroscopeInstrument


if typing.TYPE_CHECKING:
    from lite_bootstrap.bootstrappers.free_bootstrapper import FreeBootstrapperConfig as FreeBootstrapperConfig


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
    "InstrumentSkippedWarning",
    "LiteBootstrapError",
    "LitestarBootstrapper",
    "LitestarConfig",
    "PyroscopeConfig",
    "PyroscopeInstrument",
    "TeardownError",
]


__getattr__ = deprecated_module_getattr(__name__, {"FreeBootstrapperConfig": (FreeConfig, "FreeConfig")})
