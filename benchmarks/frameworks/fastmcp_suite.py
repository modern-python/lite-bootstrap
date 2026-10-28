"""FastMCP per tool call: JSON-RPC tools/call POSTed in-process to http_app(stateless_http=True, json_response=True).

Stateless JSON mode makes one tool call one HTTP request with no session handshake, so the loop measures
the HTTP app, FastMCP's dispatch and every instrument lite-bootstrap adds on either level.
"""

import json
import typing

import fastmcp.server.telemetry
from common import (
    LOG,
    OTEL,
    PROM,
    SAMPLED_SENTRY_TRACE,
    Cleanup,
    Op,
    Scenario,
    asgi_op,
    base_config,
    http_scope,
    ratio,
    sentry,
    start_lifespan,
)
from fastmcp import FastMCP
from opentelemetry.trace import NoOpTracer, Tracer
from sentry_sdk.integrations.mcp import MCPIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

from lite_bootstrap import FastMcpBootstrapper, FastMcpConfig


def _noop_tracer(version: str | None = None) -> Tracer:  # noqa: ARG001
    return NoOpTracer()


def no_fastmcp_spans() -> None:
    """Replace FastMCP's own server span per MCP operation with a no-op tracer, to see what it costs."""
    fastmcp.server.telemetry.get_tracer = _noop_tracer  # ty: ignore[invalid-assignment]


SCENARIOS: typing.Final = {
    "bare": Scenario(config=base_config()),
    "log": Scenario(config=base_config(**LOG)),
    "log_mw": Scenario(config=base_config(**LOG, logging_access_log_enabled=True)),
    "prom": Scenario(config=base_config(**PROM)),
    "otel": Scenario(config=base_config(**OTEL)),
    "otel_nofastmcp_spans": Scenario(config=base_config(**OTEL), patch=no_fastmcp_spans),
    "otel_10": Scenario(config=base_config(**OTEL, **ratio(0.1))),
    "sentry": Scenario(config=base_config(**sentry())),
    "sentry_nomcp": Scenario(config=base_config(**sentry(disabled_integrations=[MCPIntegration]))),
    "sentry_noauto": Scenario(config=base_config(**sentry(auto_enabling_integrations=False))),
    "sentry_nointegration": Scenario(
        config=base_config(**sentry(disabled_integrations=[StarletteIntegration]), sentry_lean_error_capture=False)
    ),
    "sentry_integration": Scenario(config=base_config(**sentry(), sentry_lean_error_capture=False)),
    "sentry_sampled_trace": Scenario(config=base_config(**sentry()), headers=SAMPLED_SENTRY_TRACE),
    "sentry_integration_sampled_trace": Scenario(
        config=base_config(**sentry(), sentry_lean_error_capture=False), headers=SAMPLED_SENTRY_TRACE
    ),
    "full": Scenario(config=base_config(**OTEL, **PROM, **LOG, **sentry(), health_checks_enabled=True)),
}

CALL_BODY: typing.Final = json.dumps(
    {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "add", "arguments": {"a": 1, "b": 2}}}
).encode()
HEADERS: typing.Final = (
    (b"content-type", b"application/json"),
    (b"accept", b"application/json, text/event-stream"),
    (b"mcp-protocol-version", b"2025-06-18"),
)


async def make(name: str) -> tuple[Op, Cleanup]:
    scenario = SCENARIOS[name]
    if scenario.patch is not None:
        scenario.patch()
    mcp = FastMCP("bench")

    @mcp.tool
    def add(a: int, b: int) -> int:
        return a + b

    application = FastMcpBootstrapper(FastMcpConfig(application=mcp, **scenario.config)).bootstrap()
    http_app = application.http_app(stateless_http=True, json_response=True)
    stop = await start_lifespan(http_app)
    scope = http_scope("/mcp", method="POST", extra_headers=(*HEADERS, *scenario.headers))
    return asgi_op(http_app, scope, body=CALL_BODY), stop
