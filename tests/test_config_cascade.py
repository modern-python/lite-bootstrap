import dataclasses
import typing
import warnings

import pytest

from lite_bootstrap import (
    FastAPIConfig,
    FastMcpConfig,
    FastStreamConfig,
    FreeConfig,
    LitestarConfig,
)
from lite_bootstrap.instruments.base import BaseConfig
from lite_bootstrap.instruments.opentelemetry_instrument import OpenTelemetryConfig


_REMOTE_INSECURE_ENDPOINT: typing.Final = "collector.example.com:4317"


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


@pytest.mark.parametrize(
    "config_type",
    [FastAPIConfig, FastStreamConfig, FreeConfig, LitestarConfig],
)
def test_an_insecure_endpoint_warning_names_the_line_that_built_the_config(
    config_type: type[OpenTelemetryConfig],
) -> None:
    """INVARIANT: a warning raised during config validation is attributed to the user's own frame.

    Every frame between the `warnings.warn` call and the user is lite-bootstrap's: the
    `__post_init__` links the MRO cascade walks through, and the `__init__` dataclasses generates,
    which reports itself as `<string>`. None of them is a line the user can edit, so a warning that
    lands on one is unactionable.

    What breaks it is a literal `stacklevel=`: the distance to the user is not a constant. It is the
    number of `__post_init__` links below the warning in *that* config's MRO, which differs per
    framework config and changes whenever a config gains or loses a `__post_init__`. Routing config
    warnings through `warn_at_caller` is what keeps the number right without anyone maintaining it.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        config_type(opentelemetry_endpoint=_REMOTE_INSECURE_ENDPOINT)

    assert [w.filename for w in caught] == [__file__]


@dataclasses.dataclass(kw_only=True, frozen=True)
class _ServiceConfig(FreeConfig):
    """A config subclassed the way a service is expected to subclass one, in the service's own module."""


def test_a_warning_from_a_subclassed_config_still_names_the_line_that_built_it() -> None:
    """INVARIANT: subclassing a framework config does not move the warning off the user's line.

    `dataclasses` writes the `__init__` of a subclass into the subclass's own module, so walking up
    until the frame leaves `lite_bootstrap` stops one frame too early and blames a `<string>` line
    number in a file that has no such line. Skipping dataclass-generated `__init__` frames, whatever
    module they claim, is what keeps the attribution on the construction site.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _ServiceConfig(opentelemetry_endpoint=_REMOTE_INSECURE_ENDPOINT)

    assert [w.filename for w in caught] == [__file__]
