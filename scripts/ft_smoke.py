"""Free-threaded (nogil) smoke test.

Run under a free-threaded interpreter with the ft-ready extras installed (no
orjson). Exits non-zero on failure. Proves: the interpreter is free-threaded,
orjson is absent, the logging serializer's stdlib-json fallback produces
parseable output, and a FastAPI bootstrap runs bootstrap()/teardown() clean.
Not a pytest test (conftest.py hard-imports opentelemetry, which the ft leg
does not install). See architecture/free-threading.md.
"""

import sys

from lite_bootstrap import FastAPIBootstrapper, FastAPIConfig, import_checker
from lite_bootstrap.instruments.logging_factory import StructuredLogPayload, _serialize_log_to_string


def main() -> None:
    assert sys._is_gil_enabled() is False, "expected a free-threaded interpreter"  # noqa: SLF001  # ty: ignore[unresolved-attribute]
    assert import_checker.is_orjson_installed is False, "orjson must be absent on the ft leg"

    formatted = _serialize_log_to_string({"event": "ft ok", "level": "info", "n": 1})
    payload = StructuredLogPayload.parse(formatted)
    assert payload is not None
    assert payload.message == "ft ok"
    assert payload.extra == {"n": 1}

    bootstrapper = FastAPIBootstrapper(
        bootstrap_config=FastAPIConfig(
            service_name="ft-smoke",
            service_debug=False,
            logging_buffer_capacity=0,
            health_checks_path="/health/",
        )
    )
    application = bootstrapper.bootstrap()
    assert bootstrapper.is_bootstrapped
    # FastAPI >=0.137 wraps include_router()'d routes in an internal _IncludedRouter node, so
    # application.routes no longer exposes a flat .path per route; url_path_for is the public,
    # version-stable way to confirm the health route was registered.
    assert application.url_path_for("health_check_handler") == "/health/"

    bootstrapper.teardown()
    assert not bootstrapper.is_bootstrapped

    print("ft smoke OK:", sys.version)  # noqa: T201


if __name__ == "__main__":
    main()
