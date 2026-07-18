import sys

import opentelemetry.instrumentation.asgi
import opentelemetry.instrumentation.fastapi  # noqa: F401

from lite_bootstrap import import_checker
from tests.conftest import emulate_package_missing


_DOTTED_SUBMODULES = ("opentelemetry.instrumentation.fastapi", "opentelemetry.instrumentation.asgi")


def test_import_checker_survives_incomplete_opentelemetry_namespace() -> None:
    # opentelemetry-api present but opentelemetry.instrumentation absent must not
    # crash import_checker (find_spec on the dotted name imports the missing parent).
    # By the time this test runs, lite_bootstrap has already imported these dotted
    # submodules, so find_spec would take the "already in sys.modules" fast path and
    # never hit the parent-import bug; evict them so find_spec must resolve for real.
    saved_submodules = {name: sys.modules.pop(name) for name in _DOTTED_SUBMODULES if name in sys.modules}
    try:
        with emulate_package_missing("opentelemetry.instrumentation"):
            assert import_checker.is_fastapi_opentelemetry_installed is False
            assert import_checker.is_litestar_opentelemetry_installed is False
    finally:
        sys.modules.update(saved_submodules)
