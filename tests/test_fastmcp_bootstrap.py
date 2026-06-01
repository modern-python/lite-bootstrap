import pytest
from fastmcp import FastMCP

from lite_bootstrap import FastMcpBootstrapper, FastMcpConfig
from tests.conftest import emulate_package_missing


def test_fastmcp_config_default_application() -> None:
    config = FastMcpConfig()
    assert isinstance(config.application, FastMCP)


def test_fastmcp_bootstrap_returns_same_application() -> None:
    config = FastMcpConfig(service_name="test-mcp", service_version="1.2.3")
    bootstrapper = FastMcpBootstrapper(bootstrap_config=config)
    application = bootstrapper.bootstrap()
    assert application is config.application
    bootstrapper.teardown()


def test_fastmcp_bootstrapper_not_ready() -> None:
    with emulate_package_missing("fastmcp"), pytest.raises(RuntimeError, match="fastmcp is not installed"):
        FastMcpBootstrapper(bootstrap_config=FastMcpConfig())
