"""`sentry_sdk.init()` configurations, isolating what each knob costs per request.

Every scenario runs in its own process: `init()` monkeypatches `Starlette.__call__`,
`starlette.middleware.Middleware.__init__` and `logging.Logger.callHandlers`, and none of it
can be undone.

The `*_patch` scenarios are not configurations a user can reach - they simulate an upstream
fix so its value can be measured before proposing it.
"""

import logging
import typing

import sentry_sdk
import sentry_sdk.tracing
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


SCENARIOS: dict[str, typing.Callable[[], dict[str, typing.Any]] | None] = {
    "off": None,
    # lite-bootstrap's own defaults: tracing off, all default and auto integrations on.
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
    "errors_only_txn_endpoint_style": lambda: base_kwargs(
        max_breadcrumbs=15,
        attach_stacktrace=True,
        integrations=[
            StarletteIntegration(transaction_style="endpoint"),
            FastApiIntegration(transaction_style="endpoint"),
        ],
    ),
    # --- logging integration knobs ---
    "errors_only_no_sentry_logs": lambda: base_kwargs(
        max_breadcrumbs=15,
        attach_stacktrace=True,
        integrations=[LoggingIntegration(sentry_logs_level=None)],
    ),
    "errors_only_logging_lean": lambda: base_kwargs(
        max_breadcrumbs=15,
        attach_stacktrace=True,
        integrations=[LoggingIntegration(level=None, sentry_logs_level=None)],
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
    sentry_sdk.tracing._generate_sample_rand = lambda trace_id, **kwargs: 0.5  # ty: ignore[invalid-assignment]  # noqa: ARG005


def _patch_skip_transaction() -> None:
    """Keep trace propagation, but don't build a Transaction that can never be sampled."""

    def continue_trace(
        self: Scope, environ_or_headers: dict[str, typing.Any], *_args: object, **_kwargs: object
    ) -> None:
        self.generate_propagation_context(environ_or_headers)

    Scope.continue_trace = continue_trace  # ty: ignore[invalid-assignment]


PATCHES: dict[str, list[typing.Callable[[], None]]] = {
    "errors_only_lazy_sample_rand": [_patch_lazy_sample_rand],
    "errors_only_skip_txn": [_patch_skip_transaction],
    "errors_only_skip_txn_no_sessions": [_patch_skip_transaction],
    "errors_only_logging_lean_skip_txn": [_patch_skip_transaction],
}

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
