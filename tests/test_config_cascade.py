import pytest

from lite_bootstrap import (
    FastAPIConfig,
    FastMcpConfig,
    FastStreamConfig,
    FreeConfig,
    LitestarConfig,
)
from lite_bootstrap.instruments.base import BaseConfig


@pytest.mark.parametrize(
    "config_type",
    [FastAPIConfig, FastMcpConfig, FastStreamConfig, FreeConfig, LitestarConfig],
)
def test_every_framework_config_post_init_cascade_reaches_base_config(
    config_type: type[BaseConfig], monkeypatch: pytest.MonkeyPatch
) -> None:
    """INVARIANT: constructing any framework config runs the whole `__post_init__` chain.

    Framework configs compose instrument configs by multiple inheritance, and several of those
    define `__post_init__` — `CorsConfig` rejects the credentials-plus-wildcard combination,
    `OpenTelemetryConfig` warns on a remote insecure endpoint, `FastAPIConfig` builds the
    application. A dataclass gives each class one `__post_init__` slot resolved through the MRO, so
    the chain only continues while every link calls `super().__post_init__()`. A link that returns
    early, or a newly added config whose author does not know the rule, silently disables the
    validation of every class after it in the MRO rather than failing.

    That is what breaks it, and it has broken once already: `CorsConfig.__post_init__` shipped
    without the `super()` call and switched off `OpenTelemetryConfig`'s insecure-endpoint warning for
    every FastAPI user, with nothing failing. `BaseConfig.__post_init__` is the no-op terminator, so
    reaching it proves the chain ran to the end; spying on it is how this test sees the whole chain
    without knowing which classes are in it.

    Adding a config with no `__post_init__` at all is fine — the MRO simply skips it.
    """
    reached: list[type] = []
    monkeypatch.setattr(BaseConfig, "__post_init__", lambda self: reached.append(type(self)))

    config_type()

    assert reached == [config_type]
