"""`sentry_sdk.init()` configurations, isolating what each knob costs per request.

Every scenario runs in its own process: `init()` monkeypatches `Starlette.__call__`,
`starlette.middleware.Middleware.__init__` and `logging.Logger.callHandlers`, and none of it
can be undone.

The patched scenarios are not configurations a user can reach - they simulate an upstream
fix so its value can be measured before proposing it. They, and `errors_only_txn_endpoint_style`,
exist only on sentry-sdk 2.x: 3.x builds no transaction while tracing is off and has no
`transaction_style`.
"""

import importlib
import logging
import typing

import sentry_sdk
from driver import DSN, TRANSPORT
from fastapi import FastAPI
from sentry_sdk.integrations.dedupe import DedupeIntegration
from sentry_sdk.integrations.excepthook import ExcepthookIntegration
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.modules import ModulesIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
from sentry_sdk.integrations.stdlib import StdlibIntegration
from sentry_sdk.integrations.threading import ThreadingIntegration
from sentry_sdk.scope import Scope

from lite_bootstrap.instruments.sentry_instrument import IS_SENTRY_SDK_2


SDK2_TRACING: typing.Final = importlib.import_module("sentry_sdk.tracing") if IS_SENTRY_SDK_2 else None

logger = logging.getLogger("bench")

APPS: typing.Final = ("async", "sync", "logging")


def base_kwargs(**overrides: object) -> dict[str, typing.Any]:
    return {
        "dsn": DSN,
        "transport": TRANSPORT,
        "environment": "bench",
        "release": "bench@1",
        **overrides,
    }


# The default integrations that patch global machinery; the framework ones are not here.
def _lean_integrations() -> list[typing.Any]:
    return [
        StdlibIntegration(),
        ModulesIntegration(),
        DedupeIntegration(),
        ExcepthookIntegration(),
        ThreadingIntegration(),
    ]


def _no_transaction_integrations() -> list[typing.Any]:
    return [
        StarletteIntegration(http_methods_to_capture=()),
        FastApiIntegration(http_methods_to_capture=()),
    ]


def _errors_and_breadcrumbs_only(*, breadcrumbs: bool) -> LoggingIntegration:
    """Errors become events and nothing goes to Sentry Logs; 3.0 renamed the arguments for that."""
    breadcrumb_level = logging.INFO if breadcrumbs else None
    kwargs: dict[str, typing.Any] = (
        {"level": breadcrumb_level, "sentry_logs_level": None}
        if IS_SENTRY_SDK_2
        else {"breadcrumb_level": breadcrumb_level, "event_level": logging.ERROR, "level": None}
    )
    return LoggingIntegration(**kwargs)


SCENARIOS: dict[str, typing.Callable[[], dict[str, typing.Any]] | None] = {
    "off": None,
    # lite-bootstrap 1.x's defaults: tracing off, sessions on, all default and auto integrations on.
    "errors_only": lambda: base_kwargs(
        max_breadcrumbs=15,
        max_value_length=16384,
        attach_stacktrace=True,
    ),
    # --- knobs people reach for first ---
    "errors_only_no_stacktrace": lambda: base_kwargs(max_breadcrumbs=15, attach_stacktrace=False),
    "errors_only_no_breadcrumbs": lambda: base_kwargs(max_breadcrumbs=0, attach_stacktrace=True),
    "errors_only_lean": lambda: base_kwargs(
        max_breadcrumbs=15,
        attach_stacktrace=True,
        disabled_integrations=_lean_integrations(),
    ),
    "errors_only_no_logging_integration": lambda: base_kwargs(
        max_breadcrumbs=15,
        attach_stacktrace=True,
        disabled_integrations=[LoggingIntegration()],
    ),
    "errors_only_no_default_integrations": lambda: base_kwargs(
        default_integrations=False,
        integrations=[StarletteIntegration(), FastApiIntegration()],
    ),
    # init() called, nothing patched: the floor for "the SDK is loaded".
    "errors_only_no_integrations": lambda: base_kwargs(
        default_integrations=False,
        auto_enabling_integrations=False,
        integrations=[],
    ),
    # --- ablations of the framework integration's per-request work ---
    "errors_only_no_sessions": lambda: base_kwargs(
        max_breadcrumbs=15,
        attach_stacktrace=True,
        auto_session_tracking=False,
    ),
    "errors_only_no_txn": lambda: base_kwargs(
        max_breadcrumbs=15,
        attach_stacktrace=True,
        integrations=_no_transaction_integrations(),
    ),
    "errors_only_no_sessions_no_txn": lambda: base_kwargs(
        max_breadcrumbs=15,
        attach_stacktrace=True,
        auto_session_tracking=False,
        integrations=_no_transaction_integrations(),
    ),
    "errors_only_starlette_only": lambda: base_kwargs(
        max_breadcrumbs=15,
        attach_stacktrace=True,
        auto_enabling_integrations=False,
        integrations=[StarletteIntegration()],
    ),
    # --- logging integration knobs ---
    "errors_only_no_sentry_logs": lambda: base_kwargs(
        max_breadcrumbs=15,
        attach_stacktrace=True,
        integrations=[_errors_and_breadcrumbs_only(breadcrumbs=True)],
    ),
    "errors_only_logging_lean": lambda: base_kwargs(
        max_breadcrumbs=15,
        attach_stacktrace=True,
        integrations=[_errors_and_breadcrumbs_only(breadcrumbs=False)],
    ),
    # --- tracing on ---
    "traces_0": lambda: base_kwargs(traces_sample_rate=0.0, attach_stacktrace=True),
    "traces_01": lambda: base_kwargs(traces_sample_rate=0.1, attach_stacktrace=True),
    "traces_1": lambda: base_kwargs(traces_sample_rate=1.0, attach_stacktrace=True),
    "traces_1_lean": lambda: base_kwargs(
        traces_sample_rate=1.0,
        attach_stacktrace=True,
        disabled_integrations=_lean_integrations(),
    ),
}


def _patch_lazy_sample_rand() -> None:
    """`Transaction.__init__` derives sample_rand from the trace id even when tracing is off."""
    setattr(SDK2_TRACING, "_generate_sample_rand", lambda trace_id, **kwargs: 0.5)  # noqa: ARG005, B010


def _patch_skip_transaction() -> None:
    """Keep trace propagation, but don't build a Transaction that can never be sampled."""

    def continue_trace(
        self: Scope, environ_or_headers: dict[str, typing.Any], *_args: object, **_kwargs: object
    ) -> None:
        self.generate_propagation_context(environ_or_headers)

    setattr(Scope, "continue_trace", continue_trace)  # noqa: B010


PATCHES: dict[str, list[typing.Callable[[], None]]] = {}

if IS_SENTRY_SDK_2:
    endpoint_style: dict[str, typing.Any] = {"transaction_style": "endpoint"}
    SCENARIOS["errors_only_txn_endpoint_style"] = lambda: base_kwargs(
        max_breadcrumbs=15,
        attach_stacktrace=True,
        integrations=[StarletteIntegration(**endpoint_style), FastApiIntegration(**endpoint_style)],
    )
    PATCHES.update(
        {
            "errors_only_lazy_sample_rand": [_patch_lazy_sample_rand],
            "errors_only_skip_txn": [_patch_skip_transaction],
            "errors_only_skip_txn_no_sessions": [_patch_skip_transaction],
            "errors_only_logging_lean_skip_txn": [_patch_skip_transaction],
        }
    )
    SCENARIOS["errors_only_lazy_sample_rand"] = SCENARIOS["errors_only"]
    SCENARIOS["errors_only_skip_txn"] = SCENARIOS["errors_only"]
    SCENARIOS["errors_only_skip_txn_no_sessions"] = SCENARIOS["errors_only_no_sessions"]
    SCENARIOS["errors_only_logging_lean_skip_txn"] = SCENARIOS["errors_only_logging_lean"]


def setup(scenario: str) -> None:
    factory = SCENARIOS[scenario]
    if factory is not None:
        sentry_sdk.init(**factory())
    for patch in PATCHES.get(scenario, ()):
        patch()


def make_app(kind: str) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    if kind == "async":

        @app.get("/ping")
        async def ping() -> dict[str, bool]:
            return {"ok": True}

    elif kind == "sync":

        @app.get("/ping")
        def ping_sync() -> dict[str, bool]:
            return {"ok": True}

    elif kind == "logging":

        @app.get("/ping")
        async def ping_log() -> dict[str, bool]:
            logger.info("handling request", extra={"a": 1})
            logger.info("did a thing", extra={"b": 2})
            logger.info("done", extra={"c": 3})
            return {"ok": True}

    else:
        msg = f"unknown app kind: {kind}"
        raise ValueError(msg)

    return app


def build(scenario: str, app_kind: str) -> FastAPI:
    setup(scenario)
    return make_app(app_kind)


__all__ = ["APPS", "PATCHES", "SCENARIOS", "base_kwargs", "build", "make_app", "setup"]
