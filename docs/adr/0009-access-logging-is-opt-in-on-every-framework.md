# A structured access log is opt-in on every framework

`fastapi_logging_middleware_enabled` defaults to `False`, matching
`litestar_logging_middleware_enabled`. FastMCP's `logging_turn_off_middleware` is the outlier and is
being brought into line separately (#240), so the rule is uniform: lite-bootstrap configures structlog
process-wide for every framework, and logs a line per request only when asked.

Defaulting FastAPI's on was rejected for two reasons FastMCP does not have. uvicorn already writes an
access line per request and `logging_unset_handlers` defaults to empty, so an on-by-default access log
would give every FastAPI service two lines per request, one structured and one not, until it
discovered `logging_unset_handlers=["uvicorn.access"]`. And HTTP request rates are the highest of any
supported framework, so the cost lands where it is largest: `LoggingInstrument` measures at +0.1
µs/request while nothing logs, and an always-on access log makes every request log, on a path where
Sentry's handlers alone cost ~12 µs per record when Sentry is enabled. A default that silently
multiplies log volume and per-request cost on upgrade is not one a bootstrapper should pick for its
users.

The middleware is pure ASGI rather than `BaseHTTPMiddleware`, which buffers the response body and so
breaks streaming responses and background tasks. It wraps `send` to capture the status code, reads
`path_params` from the scope after routing has populated it, and logs metadata only: `method`, `path`,
`content_type`, `path_params`, `status_code` and `duration`. Bodies are never read, which is the
defect Litestar's own middleware shipped (`54c8ad9`) and the reason that framework's binding is
hardened rather than passed through; `tests/test_fastapi_bootstrap.py` pins the claim as an invariant
rather than leaving it to prose.
