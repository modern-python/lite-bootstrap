# PR2 — Config UX & Security Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land six config-layer fixes from the 2026-06-05 audit (UX-1, UX-2, UX-3, SEC-1, SEC-2, SEC-3 + folded TEST-NEW-1 and TEST-NEW-6) in one PR.

**Architecture:** Each fix is a small TDD cycle. The work all happens at config-construction time or at the user-facing helper layer — no instrument lifecycle changes. Tasks are ordered to land additive UX improvements first (UX-1, UX-2, UX-3), then the security validators (SEC-1, SEC-2, SEC-3) which are slightly more cross-cutting (SEC-2 introduces an `OpenTelemetryConfig.__post_init__` that interacts with the FastAPIConfig override touched in Task 1).

**Tech Stack:** Python 3.10+, `uv` workspace, `pytest` (with `pytest-asyncio`), `ty` type checker, `ruff` formatter, `structlog`, `prometheus_client`, `opentelemetry-sdk`, `fastapi`, `litestar`, `faststream`, `fastmcp`.

**Branch:** `fix/bug-audit-v2-pr2-config-security` (branch off `main` after PR1 merges, or off PR1's branch if parallel work is desired).

**Sequencing prerequisite:** PR1 should merge first. PR2 doesn't structurally depend on PR1, but Task 5 introduces `OpenTelemetryConfig.__post_init__` which interacts with the `_prior_logger_disabled` field added in PR1 Task 4 (both touch `OpenTelemetryConfig`/`OpenTelemetryInstrument`). Rebasing PR2 onto a merged PR1 keeps the conflict resolution trivial.

---

## File Structure

Modifications to existing files only — no new files.

| File | What changes |
|------|-------------|
| `lite_bootstrap/bootstrappers/fastapi_bootstrapper.py` | Move user-app field overrides into UnsetType branch (Task 1); add `super().__post_init__()` for Task 5 cascade |
| `lite_bootstrap/bootstrappers/faststream_bootstrapper.py` | Add `prometheus_collector_registry` field + thread to instrument (Task 2); add `opentelemetry_excluded_urls` field (Task 3) |
| `lite_bootstrap/helpers/fastapi_helpers.py` | Validate `root_path` via `is_valid_path` + fall back on warning (Task 4) |
| `lite_bootstrap/instruments/cors_instrument.py` | Add `__post_init__` to `CorsConfig` rejecting wildcard + credentials combo (Task 6) |
| `lite_bootstrap/instruments/opentelemetry_instrument.py` | Add `__post_init__` to `OpenTelemetryConfig` warning on insecure non-local endpoint (Task 5) |
| `tests/test_fastapi_bootstrap.py` | Test for Task 1 |
| `tests/test_fastapi_offline_docs.py` | Test for Task 4 |
| `tests/test_faststream_bootstrap.py` | Tests for Tasks 2, 3 |
| `tests/instruments/test_cors_instrument.py` | Test for Task 6 |
| `tests/instruments/test_opentelemetry_instrument.py` | Test for Task 5 |

---

## Task 1: UX-1 — `FastAPIConfig` respects user app's title/debug/version

**Files:**
- Modify: `lite_bootstrap/bootstrappers/fastapi_bootstrapper.py:58-75`
- Test: `tests/test_fastapi_bootstrap.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_fastapi_bootstrap.py` (at the bottom, after existing tests):

```python
def test_user_supplied_app_keeps_title_version_debug() -> None:
    user_app = fastapi.FastAPI(title="user-title", version="9.9.9", debug=False)
    config = FastAPIConfig(
        application=user_app,
        service_name="lite-name",
        service_version="1.0.0",
        service_debug=True,
    )
    assert config.application is user_app
    assert user_app.title == "user-title"
    assert user_app.version == "9.9.9"
    assert user_app.debug is False
```

`fastapi`, `FastAPIConfig` are already imported in this file.

- [ ] **Step 2: Run test to verify it fails**

```bash
just test -- tests/test_fastapi_bootstrap.py::test_user_supplied_app_keeps_title_version_debug
```

Expected: FAIL — current `__post_init__` overwrites `application.title/.debug/.version` with the config defaults even when the user supplies a pre-configured app.

- [ ] **Step 3: Move the field overrides into the UnsetType branch**

In `lite_bootstrap/bootstrappers/fastapi_bootstrapper.py`, the current `__post_init__` (lines 58-75) reads:

```python
def __post_init__(self) -> None:
    if not import_checker.is_fastapi_installed:
        msg = "fastapi is not installed"
        raise ConfigurationError(msg)

    if isinstance(self.application, UnsetType):
        application = fastapi.FastAPI(docs_url=self.swagger_path, **self.application_kwargs)
        # FastAPIConfig stays frozen for user-facing immutability; __post_init__ needs
        # to set application after construction, so we bypass the freeze here.
        object.__setattr__(self, "application", application)
    else:
        application = self.application
        if self.application_kwargs:
            warnings.warn("application_kwargs must be used without application", stacklevel=2)

    application.title = self.service_name
    application.debug = self.service_debug
    application.version = self.service_version
```

Replace with:

```python
def __post_init__(self) -> None:
    if not import_checker.is_fastapi_installed:
        msg = "fastapi is not installed"
        raise ConfigurationError(msg)

    if isinstance(self.application, UnsetType):
        application = fastapi.FastAPI(docs_url=self.swagger_path, **self.application_kwargs)
        # FastAPIConfig stays frozen for user-facing immutability; __post_init__ needs
        # to set application after construction, so we bypass the freeze here.
        object.__setattr__(self, "application", application)
        application.title = self.service_name
        application.debug = self.service_debug
        application.version = self.service_version
    elif self.application_kwargs:
        warnings.warn("application_kwargs must be used without application", stacklevel=2)
```

Key changes:
- Three `application.X = ...` lines moved inside the `if isinstance(...)` branch
- The `else: application = self.application` line is gone (no longer needed since we don't reference `application` after the branch)
- `else: if self.application_kwargs:` collapsed to `elif self.application_kwargs:`

- [ ] **Step 4: Run the new test to verify it passes**

```bash
just test -- tests/test_fastapi_bootstrap.py::test_user_supplied_app_keeps_title_version_debug
```

Expected: PASS.

- [ ] **Step 5: Verify nothing else broke**

```bash
just test -- tests/test_fastapi_bootstrap.py tests/test_fastapi_offline_docs.py
```

Expected: all green. In particular `test_fastapi_bootstrapper_apps_and_kwargs_warning` still triggers when both `application` and `application_kwargs` are passed.

- [ ] **Step 6: Run full suite + lint**

```bash
just test
just lint-ci
```

Expected: 165 passed (164 + 1 new), 100% coverage, lint clean.

- [ ] **Step 7: Commit**

```bash
git add lite_bootstrap/bootstrappers/fastapi_bootstrapper.py tests/test_fastapi_bootstrap.py
git commit -m "$(cat <<'EOF'
fix: FastAPIConfig respects user-supplied app title/version/debug (UX-1)

Move the application.title/.debug/.version assignments inside the UnsetType
branch so they only apply when lite-bootstrap built the FastAPI() instance.
Pre-configured user apps now keep their construction-time values.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: UX-2 — Injectable `prometheus_collector_registry` on FastStream

**Files:**
- Modify: `lite_bootstrap/bootstrappers/faststream_bootstrapper.py:63-72` (add config field), `:143-167` (thread to instrument)
- Test: `tests/test_faststream_bootstrap.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_faststream_bootstrap.py`:

```python
import uuid


async def test_faststream_prometheus_uses_injected_registry(broker: RedisBroker) -> None:
    custom_registry = prometheus_client.CollectorRegistry()
    counter_name = f"injected_counter_{uuid.uuid4().hex}_total"
    counter = prometheus_client.Counter(counter_name, "Injected registry counter", registry=custom_registry)
    counter.inc()

    bootstrap_config = dataclasses.replace(
        build_faststream_config(broker=broker),
        prometheus_collector_registry=custom_registry,
    )
    bootstrapper = FastStreamBootstrapper(bootstrap_config=bootstrap_config)
    application = bootstrapper.bootstrap()
    try:
        with TestClient(app=application) as test_client, TestRedisBroker(broker):
            response = test_client.get(bootstrap_config.prometheus_metrics_path)
            assert response.status_code == status.HTTP_200_OK
            assert counter_name.encode() in response.content
    finally:
        bootstrapper.teardown()
```

Imports — verify `prometheus_client` is imported at module level (it isn't yet in this test file). Add:

```python
import prometheus_client
```

Near the existing `import` block at the top of `tests/test_faststream_bootstrap.py`. `dataclasses`, `uuid`, `status`, `TestClient`, `TestRedisBroker`, `RedisBroker` are already imported or will be from new imports.

- [ ] **Step 2: Run test to verify it fails**

```bash
just test -- tests/test_faststream_bootstrap.py::test_faststream_prometheus_uses_injected_registry
```

Expected: FAIL — `FastStreamConfig` doesn't have `prometheus_collector_registry` field; `dataclasses.replace(...)` raises `TypeError: __init__() got an unexpected keyword argument 'prometheus_collector_registry'`.

- [ ] **Step 3: Add the config field**

In `lite_bootstrap/bootstrappers/faststream_bootstrapper.py`, the current `FastStreamConfig` (lines 63-72) reads:

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class FastStreamConfig(
    HealthChecksConfig, LoggingConfig, OpenTelemetryConfig, PrometheusConfig, PyroscopeConfig, SentryConfig
):
    application: "AsgiFastStream" = dataclasses.field(default_factory=_make_asgi_faststream)
    opentelemetry_middleware_cls: type[FastStreamTelemetryMiddlewareProtocol] | None = None
    prometheus_middleware_cls: type[FastStreamPrometheusMiddlewareProtocol] | None = None
    faststream_log_level: int = logging.WARNING
    faststream_health_check_broker_timeout: float = 5.0
```

Add a `prometheus_collector_registry` field after `prometheus_middleware_cls`:

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class FastStreamConfig(
    HealthChecksConfig, LoggingConfig, OpenTelemetryConfig, PrometheusConfig, PyroscopeConfig, SentryConfig
):
    application: "AsgiFastStream" = dataclasses.field(default_factory=_make_asgi_faststream)
    opentelemetry_middleware_cls: type[FastStreamTelemetryMiddlewareProtocol] | None = None
    prometheus_middleware_cls: type[FastStreamPrometheusMiddlewareProtocol] | None = None
    prometheus_collector_registry: "prometheus_client.CollectorRegistry | None" = None
    faststream_log_level: int = logging.WARNING
    faststream_health_check_broker_timeout: float = 5.0
```

The string-annotation form `"prometheus_client.CollectorRegistry | None"` works because `prometheus_client` is imported conditionally at module scope (`if import_checker.is_prometheus_client_installed: import prometheus_client`). Dataclass field type annotations are not resolved at runtime by default, so the conditional import is fine.

- [ ] **Step 4: Thread the field into `FastStreamPrometheusInstrument`**

Currently (lines 143-167):

```python
@dataclasses.dataclass(kw_only=True)
class FastStreamPrometheusInstrument(PrometheusInstrument):
    bootstrap_config: FastStreamConfig
    collector_registry: "prometheus_client.CollectorRegistry" = dataclasses.field(
        default_factory=_make_collector_registry, init=False
    )
    not_ready_message = PrometheusInstrument.not_ready_message + " or prometheus_middleware_cls is missing"
    missing_dependency_message = "prometheus_client is not installed"
    ...
```

Replace the `collector_registry` field declaration with an `init=False` field set in `__post_init__`:

```python
@dataclasses.dataclass(kw_only=True)
class FastStreamPrometheusInstrument(PrometheusInstrument):
    bootstrap_config: FastStreamConfig
    collector_registry: "prometheus_client.CollectorRegistry" = dataclasses.field(init=False)
    not_ready_message = PrometheusInstrument.not_ready_message + " or prometheus_middleware_cls is missing"
    missing_dependency_message = "prometheus_client is not installed"

    def __post_init__(self) -> None:
        injected = self.bootstrap_config.prometheus_collector_registry
        self.collector_registry = injected if injected is not None else _make_collector_registry()

    @classmethod
    def is_configured(cls, bootstrap_config: "FastStreamConfig") -> bool:  # ty: ignore[invalid-method-override]
        return super().is_configured(bootstrap_config) and bool(bootstrap_config.prometheus_middleware_cls)
    ...
```

`__post_init__` runs after dataclass `__init__`; assignment via `self.collector_registry = ...` works because the instrument is non-frozen.

Keep the rest of the class unchanged (the `is_configured`, `check_dependencies`, `bootstrap` methods).

- [ ] **Step 5: Run the new test to verify it passes**

```bash
just test -- tests/test_faststream_bootstrap.py::test_faststream_prometheus_uses_injected_registry
```

Expected: PASS.

- [ ] **Step 6: Verify default-path still works**

```bash
just test -- tests/test_faststream_bootstrap.py
```

Expected: all green. Existing `test_faststream_bootstrap` (which doesn't supply `prometheus_collector_registry`) continues to use the per-instance default.

- [ ] **Step 7: Full suite + lint**

```bash
just test
just lint-ci
```

Expected: 166 passed (165 + 1 new), 100% coverage, lint clean.

- [ ] **Step 8: Commit**

```bash
git add lite_bootstrap/bootstrappers/faststream_bootstrapper.py tests/test_faststream_bootstrap.py
git commit -m "$(cat <<'EOF'
feat: support injectable Prometheus CollectorRegistry on FastStream (UX-2)

Add prometheus_collector_registry: CollectorRegistry | None config field on
FastStreamConfig. When non-None, FastStreamPrometheusInstrument uses the
injected registry; otherwise the existing per-instance default is preserved.
Lets users expose metrics that were registered on a shared registry.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: UX-3 — Add `opentelemetry_excluded_urls` to FastStreamConfig

**Files:**
- Modify: `lite_bootstrap/bootstrappers/faststream_bootstrapper.py:63-72`
- Test: `tests/test_faststream_bootstrap.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_faststream_bootstrap.py`:

```python
def test_faststream_opentelemetry_excluded_urls_in_built_set(broker: RedisBroker) -> None:
    from lite_bootstrap.bootstrappers.faststream_bootstrapper import (
        FastStreamOpenTelemetryInstrument,
    )

    bootstrap_config = dataclasses.replace(
        build_faststream_config(broker=broker),
        opentelemetry_excluded_urls=["/foo", "/bar"],
    )
    instrument = FastStreamOpenTelemetryInstrument(bootstrap_config=bootstrap_config)
    excluded = instrument._build_excluded_urls()  # noqa: SLF001
    assert "/foo" in excluded
    assert "/bar" in excluded
```

- [ ] **Step 2: Run test to verify it fails**

```bash
just test -- tests/test_faststream_bootstrap.py::test_faststream_opentelemetry_excluded_urls_in_built_set
```

Expected: FAIL — `dataclasses.replace(...)` raises because `FastStreamConfig` has no `opentelemetry_excluded_urls` field.

- [ ] **Step 3: Add the field**

In `lite_bootstrap/bootstrappers/faststream_bootstrapper.py`, the current `FastStreamConfig` (after Task 2's edit) reads approximately:

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class FastStreamConfig(
    HealthChecksConfig, LoggingConfig, OpenTelemetryConfig, PrometheusConfig, PyroscopeConfig, SentryConfig
):
    application: "AsgiFastStream" = dataclasses.field(default_factory=_make_asgi_faststream)
    opentelemetry_middleware_cls: type[FastStreamTelemetryMiddlewareProtocol] | None = None
    prometheus_middleware_cls: type[FastStreamPrometheusMiddlewareProtocol] | None = None
    prometheus_collector_registry: "prometheus_client.CollectorRegistry | None" = None
    faststream_log_level: int = logging.WARNING
    faststream_health_check_broker_timeout: float = 5.0
```

Add `opentelemetry_excluded_urls` after `opentelemetry_middleware_cls`:

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class FastStreamConfig(
    HealthChecksConfig, LoggingConfig, OpenTelemetryConfig, PrometheusConfig, PyroscopeConfig, SentryConfig
):
    application: "AsgiFastStream" = dataclasses.field(default_factory=_make_asgi_faststream)
    opentelemetry_middleware_cls: type[FastStreamTelemetryMiddlewareProtocol] | None = None
    opentelemetry_excluded_urls: list[str] = dataclasses.field(default_factory=list)
    prometheus_middleware_cls: type[FastStreamPrometheusMiddlewareProtocol] | None = None
    prometheus_collector_registry: "prometheus_client.CollectorRegistry | None" = None
    faststream_log_level: int = logging.WARNING
    faststream_health_check_broker_timeout: float = 5.0
```

The behavior of `_build_excluded_urls` (in `opentelemetry_instrument.py`) is unchanged — it already reads via `getattr(self.bootstrap_config, "opentelemetry_excluded_urls", [])`. The new field is just for discoverability (IDE help, tab completion).

- [ ] **Step 4: Run the new test to verify it passes**

```bash
just test -- tests/test_faststream_bootstrap.py::test_faststream_opentelemetry_excluded_urls_in_built_set
```

Expected: PASS.

- [ ] **Step 5: Full suite + lint**

```bash
just test
just lint-ci
```

Expected: 167 passed (166 + 1 new), 100% coverage, lint clean.

- [ ] **Step 6: Commit**

```bash
git add lite_bootstrap/bootstrappers/faststream_bootstrapper.py tests/test_faststream_bootstrap.py
git commit -m "$(cat <<'EOF'
feat: add opentelemetry_excluded_urls to FastStreamConfig (UX-3)

FastAPIConfig and LitestarConfig already expose opentelemetry_excluded_urls;
FastStream relied on getattr fallback with no discoverable field. Add the field
to FastStreamConfig matching the FastAPI/Litestar pattern. _build_excluded_urls
behavior is unchanged — the getattr access still works the same way.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: SEC-1 — Validate `root_path` in offline-docs HTML

**Files:**
- Modify: `lite_bootstrap/helpers/fastapi_helpers.py`
- Test: `tests/test_fastapi_offline_docs.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_fastapi_offline_docs.py`:

```python
def test_offline_docs_rejects_unsafe_root_path() -> None:
    malicious_root = "/foo</script><script>alert(1)</script>"
    app = FastAPI(title="Tests", root_path=malicious_root, docs_url="/custom_docs")
    enable_offline_docs(app, static_path="/static")

    with TestClient(app, root_path=malicious_root) as client, pytest.warns(UserWarning, match="root_path"):
        response = client.get("/custom_docs")
    assert response.status_code == HTTPStatus.OK
    assert "<script>alert(1)</script>" not in response.text
    assert "/static/swagger-ui.css" in response.text  # falls back to empty root_path
```

`FastAPI`, `TestClient`, `HTTPStatus`, `pytest`, `enable_offline_docs` are already imported in this file.

- [ ] **Step 2: Run test to verify it fails**

```bash
just test -- tests/test_fastapi_offline_docs.py::test_offline_docs_rejects_unsafe_root_path
```

Expected: FAIL — current handler reflects `root_path` verbatim into the swagger HTML, so the `<script>` tag from `root_path` lands in the response.

- [ ] **Step 3: Add the validation helper and use it in both handlers**

In `lite_bootstrap/helpers/fastapi_helpers.py`, add `warnings` and `is_valid_path` imports near the top:

```python
import pathlib
import typing
import warnings

from lite_bootstrap import import_checker
from lite_bootstrap.exceptions import ConfigurationError
from lite_bootstrap.helpers.path import is_valid_path
```

Then add a module-level helper just above `enable_offline_docs`:

```python
def _safe_root_path(scope_root_path: str) -> str:
    """Strip trailing slash and validate against the project's path allowlist.

    An empty `root_path` is the normal case (no proxy prefix) and is allowed without warning.
    Any other path that fails the `is_valid_path` regex is rejected (falls back to empty) so
    that proxy-header-derived root paths can't inject HTML into the offline-docs response.
    """
    candidate = scope_root_path.rstrip("/")
    if not candidate:
        return ""
    if not is_valid_path(candidate):
        warnings.warn(
            f"root_path {candidate!r} contains characters outside the valid-path allowlist; "
            "falling back to empty root_path to prevent HTML injection in offline docs.",
            stacklevel=3,
        )
        return ""
    return candidate
```

In `custom_swagger_ui_html` (currently around line 38-46), replace:

```python
async def custom_swagger_ui_html(request: Request) -> HTMLResponse:
    root_path = request.scope.get("root_path", "").rstrip("/")
    ...
```

with:

```python
async def custom_swagger_ui_html(request: Request) -> HTMLResponse:
    root_path = _safe_root_path(request.scope.get("root_path", ""))
    ...
```

Same change in `redoc_html` (currently around line 53-58): replace the `root_path = request.scope.get("root_path", "").rstrip("/")` line with `root_path = _safe_root_path(request.scope.get("root_path", ""))`.

- [ ] **Step 4: Run the new test to verify it passes**

```bash
just test -- tests/test_fastapi_offline_docs.py::test_offline_docs_rejects_unsafe_root_path
```

Expected: PASS — the malicious `root_path` is rejected, falls back to empty, no `<script>` injection in the response, and the warning fires.

- [ ] **Step 5: Verify existing tests still pass**

```bash
just test -- tests/test_fastapi_offline_docs.py
```

Expected: all green. `test_fastapi_offline_docs_root_path` (which uses the valid `/some-root-path`) still validates the safe case.

- [ ] **Step 6: Full suite + lint**

```bash
just test
just lint-ci
```

Expected: 168 passed (167 + 1 new), 100% coverage, lint clean.

- [ ] **Step 7: Commit**

```bash
git add lite_bootstrap/helpers/fastapi_helpers.py tests/test_fastapi_offline_docs.py
git commit -m "$(cat <<'EOF'
fix: validate root_path in offline-docs HTML to prevent injection (SEC-1)

The swagger/redoc handlers reflected request.scope["root_path"] verbatim into
HTML script/link tags. In default ASGI deployments root_path comes from server
config (uvicorn --root-path), but if a user enables ProxyHeadersMiddleware with
trusted X-Forwarded-Prefix, a malicious proxy could inject script content.
Validate via the project's existing is_valid_path allowlist and fall back to
empty (with a warning) on invalid input.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: SEC-2 — Warn on insecure non-local OTLP endpoint

**Files:**
- Modify: `lite_bootstrap/instruments/opentelemetry_instrument.py` (add `__post_init__` on `OpenTelemetryConfig`)
- Modify: `lite_bootstrap/bootstrappers/fastapi_bootstrapper.py` (cascade `super().__post_init__()` so FastAPIConfig users also get the warning)
- Test: `tests/instruments/test_opentelemetry_instrument.py`

**Context:** Only `FastAPIConfig` defines its own `__post_init__` among the framework configs. `FreeConfig`, `FastStreamConfig`, `LitestarConfig` inherit `OpenTelemetryConfig.__post_init__` (the one we're adding here) automatically via the dataclass MRO. `FastMcpConfig` doesn't inherit `OpenTelemetryConfig`, so the warning doesn't fire for it — that's correct since FastMCP doesn't bootstrap OTel today.

- [ ] **Step 1: Write the failing tests**

Add to `tests/instruments/test_opentelemetry_instrument.py`:

```python
import warnings


def test_opentelemetry_config_warns_on_insecure_non_local_endpoint() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        OpenTelemetryConfig(
            opentelemetry_endpoint="http://collector.example.com:4317",
            opentelemetry_insecure=True,
        )
    matching = [w for w in caught if "unencrypted" in str(w.message)]
    assert matching, [str(w.message) for w in caught]


def test_opentelemetry_config_no_warning_for_localhost_endpoint() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        # Should not raise — no warning emitted for localhost.
        OpenTelemetryConfig(
            opentelemetry_endpoint="http://localhost:4317",
            opentelemetry_insecure=True,
        )


def test_opentelemetry_config_no_warning_when_insecure_false() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        OpenTelemetryConfig(
            opentelemetry_endpoint="https://collector.example.com:4317",
            opentelemetry_insecure=False,
        )


def test_opentelemetry_config_no_warning_when_endpoint_unset() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        OpenTelemetryConfig(opentelemetry_log_traces=True)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
just test -- tests/instruments/test_opentelemetry_instrument.py::test_opentelemetry_config_warns_on_insecure_non_local_endpoint
```

Expected: FAIL — `OpenTelemetryConfig` has no `__post_init__`, so no warning is emitted.

The three "no warning" tests would pass even on the unmodified code (vacuously), but they pin the contract once the warning logic is added.

- [ ] **Step 3: Add `__post_init__` on `OpenTelemetryConfig`**

In `lite_bootstrap/instruments/opentelemetry_instrument.py`, add `urllib.parse` and `warnings` to the imports near the top (alongside the existing `import dataclasses`, `import logging`, `import os`, `import typing`):

```python
import dataclasses
import logging
import os
import typing
import urllib.parse
import warnings
```

Then modify `OpenTelemetryConfig` (currently lines 41-53) to add `__post_init__`. Current code:

```python
@dataclasses.dataclass(kw_only=True, frozen=True)
class OpenTelemetryConfig(OpenTelemetryServiceFieldsConfig):
    opentelemetry_container_name: str | None = dataclasses.field(
        default_factory=lambda: os.environ.get("HOSTNAME") or None
    )
    opentelemetry_endpoint: str | None = None
    opentelemetry_insecure: bool = True
    opentelemetry_instrumentors: list[typing.Union[InstrumentorWithParams, "BaseInstrumentor"]] = dataclasses.field(
        default_factory=list
    )
    opentelemetry_log_traces: bool = False
    opentelemetry_generate_health_check_spans: bool = True
```

Replace with:

```python
_LOCAL_HOSTS: typing.Final[frozenset[str]] = frozenset({"localhost", "127.0.0.1", "::1", ""})


@dataclasses.dataclass(kw_only=True, frozen=True)
class OpenTelemetryConfig(OpenTelemetryServiceFieldsConfig):
    opentelemetry_container_name: str | None = dataclasses.field(
        default_factory=lambda: os.environ.get("HOSTNAME") or None
    )
    opentelemetry_endpoint: str | None = None
    opentelemetry_insecure: bool = True
    opentelemetry_instrumentors: list[typing.Union[InstrumentorWithParams, "BaseInstrumentor"]] = dataclasses.field(
        default_factory=list
    )
    opentelemetry_log_traces: bool = False
    opentelemetry_generate_health_check_spans: bool = True

    def __post_init__(self) -> None:
        if not self.opentelemetry_endpoint or not self.opentelemetry_insecure:
            return
        if self.opentelemetry_endpoint.startswith("unix://"):
            return
        parsed = urllib.parse.urlparse(self.opentelemetry_endpoint)
        host = (parsed.hostname or parsed.path.split(":")[0]).lower()
        if host in _LOCAL_HOSTS:
            return
        warnings.warn(
            f"OTLP exporter sending traces unencrypted to non-local host {host!r}; "
            "set opentelemetry_insecure=False or use a localhost/unix endpoint.",
            stacklevel=3,
        )
```

The `_LOCAL_HOSTS` frozenset is module-private and reusable for any future host-locality checks. `urllib.parse.urlparse` handles both `host:port` and `scheme://host:port` (falls back to splitting `:` if `urlparse` can't extract a host).

- [ ] **Step 4: Cascade `super().__post_init__()` in FastAPIConfig**

After Task 1 lands, `FastAPIConfig.__post_init__` (in `lite_bootstrap/bootstrappers/fastapi_bootstrapper.py`) looks like:

```python
def __post_init__(self) -> None:
    if not import_checker.is_fastapi_installed:
        msg = "fastapi is not installed"
        raise ConfigurationError(msg)

    if isinstance(self.application, UnsetType):
        application = fastapi.FastAPI(docs_url=self.swagger_path, **self.application_kwargs)
        object.__setattr__(self, "application", application)
        application.title = self.service_name
        application.debug = self.service_debug
        application.version = self.service_version
    elif self.application_kwargs:
        warnings.warn("application_kwargs must be used without application", stacklevel=2)
```

Add `super().__post_init__()` as the first line of the body so the OpenTelemetryConfig warning fires for FastAPIConfig too:

```python
def __post_init__(self) -> None:
    super().__post_init__()
    if not import_checker.is_fastapi_installed:
        msg = "fastapi is not installed"
        raise ConfigurationError(msg)

    if isinstance(self.application, UnsetType):
        application = fastapi.FastAPI(docs_url=self.swagger_path, **self.application_kwargs)
        object.__setattr__(self, "application", application)
        application.title = self.service_name
        application.debug = self.service_debug
        application.version = self.service_version
    elif self.application_kwargs:
        warnings.warn("application_kwargs must be used without application", stacklevel=2)
```

The MRO chain for `FastAPIConfig` resolves `super().__post_init__()` to `OpenTelemetryConfig.__post_init__` (via CorsConfig → HealthChecksConfig → LoggingConfig → OpenTelemetryConfig).

- [ ] **Step 5: Add a FastAPIConfig-specific cascade test**

Add to `tests/test_fastapi_bootstrap.py`:

```python
def test_fastapi_config_inherits_otel_insecure_warning() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        FastAPIConfig(
            opentelemetry_endpoint="http://collector.example.com:4317",
            opentelemetry_insecure=True,
        )
    matching = [w for w in caught if "unencrypted" in str(w.message)]
    assert matching, [str(w.message) for w in caught]
```

Verify `warnings` is imported at the top of `tests/test_fastapi_bootstrap.py` — it was added in PR1 Task 10.

- [ ] **Step 6: Run all new tests**

```bash
just test -- tests/instruments/test_opentelemetry_instrument.py tests/test_fastapi_bootstrap.py
```

Expected: all green, including the new SEC-2 tests and the FastAPIConfig cascade test.

- [ ] **Step 7: Full suite + lint**

```bash
just test
just lint-ci
```

Expected: 173 passed (168 + 5 new), 100% coverage, lint clean.

- [ ] **Step 8: Commit**

```bash
git add lite_bootstrap/instruments/opentelemetry_instrument.py lite_bootstrap/bootstrappers/fastapi_bootstrapper.py tests/instruments/test_opentelemetry_instrument.py tests/test_fastapi_bootstrap.py
git commit -m "$(cat <<'EOF'
fix: warn on insecure non-local OTLP endpoint (SEC-2)

Add OpenTelemetryConfig.__post_init__ that emits a warning when
opentelemetry_endpoint points to a non-local host AND opentelemetry_insecure is
True (the unfortunate default). Localhost, 127.0.0.1, ::1, and unix:// endpoints
are silent. FastAPIConfig.__post_init__ now calls super().__post_init__() so
FastAPI users see the warning too; other framework configs (FreeConfig,
FastStreamConfig, LitestarConfig) don't have their own __post_init__ and
inherit the new behavior automatically.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: SEC-3 — Reject unsafe CORS configurations at construction

**Files:**
- Modify: `lite_bootstrap/instruments/cors_instrument.py` (add `__post_init__` on `CorsConfig`)
- Test: `tests/instruments/test_cors_instrument.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/instruments/test_cors_instrument.py`:

```python
import pytest

from lite_bootstrap.exceptions import ConfigurationError


@pytest.mark.parametrize(
    ("origins", "regex"),
    [
        (["*"], None),
        ([], ".*"),
        ([], r".+"),
        (["*", "http://safe.example.com"], None),
    ],
)
def test_cors_config_rejects_wildcard_with_credentials(
    origins: list[str], regex: str | None
) -> None:
    with pytest.raises(ConfigurationError, match="Unsafe CORS"):
        CorsConfig(
            cors_allowed_origins=origins,
            cors_allowed_origin_regex=regex,
            cors_allowed_credentials=True,
        )


def test_cors_config_accepts_credentials_with_explicit_origins() -> None:
    config = CorsConfig(
        cors_allowed_origins=["http://example.com"],
        cors_allowed_credentials=True,
    )
    assert config.cors_allowed_credentials is True


def test_cors_config_accepts_wildcard_without_credentials() -> None:
    config = CorsConfig(
        cors_allowed_origins=["*"],
        cors_allowed_credentials=False,
    )
    assert config.cors_allowed_origins == ["*"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
just test -- tests/instruments/test_cors_instrument.py::test_cors_config_rejects_wildcard_with_credentials
```

Expected: FAIL — `CorsConfig` accepts the unsafe combination today.

- [ ] **Step 3: Add `__post_init__` to `CorsConfig`**

In `lite_bootstrap/instruments/cors_instrument.py`, the current `CorsConfig` (lines 6-15) reads:

```python
@dataclasses.dataclass(kw_only=True, frozen=True)
class CorsConfig(BaseConfig):
    cors_allowed_origins: list[str] = dataclasses.field(default_factory=list)
    cors_allowed_methods: list[str] = dataclasses.field(default_factory=list)
    cors_allowed_headers: list[str] = dataclasses.field(default_factory=list)
    cors_exposed_headers: list[str] = dataclasses.field(default_factory=list)
    cors_allowed_credentials: bool = False
    cors_allowed_origin_regex: str | None = None
    cors_max_age: int = 600
```

Add an import for `ConfigurationError` at the top:

```python
import dataclasses

from lite_bootstrap.exceptions import ConfigurationError
from lite_bootstrap.instruments.base import BaseConfig, BaseInstrument
```

And add `__post_init__`:

```python
_PERMISSIVE_ORIGIN_REGEX: typing.Final[frozenset[str]] = frozenset({".*", r".+"})


@dataclasses.dataclass(kw_only=True, frozen=True)
class CorsConfig(BaseConfig):
    cors_allowed_origins: list[str] = dataclasses.field(default_factory=list)
    cors_allowed_methods: list[str] = dataclasses.field(default_factory=list)
    cors_allowed_headers: list[str] = dataclasses.field(default_factory=list)
    cors_exposed_headers: list[str] = dataclasses.field(default_factory=list)
    cors_allowed_credentials: bool = False
    cors_allowed_origin_regex: str | None = None
    cors_max_age: int = 600

    def __post_init__(self) -> None:
        if not self.cors_allowed_credentials:
            return
        wildcard_in_origins = "*" in self.cors_allowed_origins
        permissive_regex = self.cors_allowed_origin_regex in _PERMISSIVE_ORIGIN_REGEX
        if wildcard_in_origins or permissive_regex:
            msg = (
                "Unsafe CORS configuration: cors_allowed_credentials=True combined with a "
                "wildcard origin is rejected by browsers and is a security misconfiguration. "
                "Use an explicit list of allowed origins (or a narrow regex)."
            )
            raise ConfigurationError(msg)
```

Add `import typing` if not already imported.

- [ ] **Step 4: Run the new tests to verify they pass**

```bash
just test -- tests/instruments/test_cors_instrument.py
```

Expected: all green (new tests + existing tests like `test_cors_instrument_configured_with_origins`).

- [ ] **Step 5: Run downstream tests that build FastAPI/Litestar configs with CORS**

```bash
just test -- tests/test_fastapi_bootstrap.py tests/test_litestar_bootstrap.py
```

Expected: green. None of the existing fixtures use the wildcard + credentials combo.

- [ ] **Step 6: Full suite + lint**

```bash
just test
just lint-ci
```

Expected: 176 passed (173 + 3 new), 100% coverage, lint clean.

- [ ] **Step 7: Commit**

```bash
git add lite_bootstrap/instruments/cors_instrument.py tests/instruments/test_cors_instrument.py
git commit -m "$(cat <<'EOF'
fix: reject unsafe CORS wildcard + credentials combo at construction (SEC-3)

cors_allowed_credentials=True with cors_allowed_origins=["*"] (or a permissive
regex like ".*"/".+") is the canonical CORS misconfiguration. FastAPI's
CORSMiddleware refuses to set the credentials header in that combo but
Litestar's behavior differs and may silently accept it. Add a CorsConfig
__post_init__ that raises ConfigurationError on the unsafe combination
at config-construction time, before any framework sees the values.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Final verification

- [ ] **Step 1: Full test suite**

```bash
just test
```

Expected: 176 passed (164 baseline + 12 new across the 6 tasks), 100% coverage.

- [ ] **Step 2: Lint + type check**

```bash
just lint-ci
```

Expected: green.

- [ ] **Step 3: Confirm commit log shape**

```bash
git log --oneline origin/main..HEAD
```

Expected: 6 task commits, each titled with a `fix:` or `feat:` prefix and tagged with the audit ID(s) it closes:

- Task 1 (UX-1) — `fix:`
- Task 2 (UX-2) — `feat:`
- Task 3 (UX-3) — `feat:`
- Task 4 (SEC-1) — `fix:`
- Task 5 (SEC-2) — `fix:`
- Task 6 (SEC-3) — `fix:`

---

## Self-Review

1. **Spec coverage:** UX-1 (Task 1) · UX-2 (Task 2) · UX-3 (Task 3) · SEC-1 (Task 4) · SEC-2 (Task 5) · SEC-3 (Task 6). TEST-NEW-1 folds into Task 1; TEST-NEW-6 folds into Task 6. All 6 PR2 findings + 2 paired test items mapped.
2. **Placeholder scan:** every step has full code blocks, exact commands, and expected outcomes.
3. **Type consistency:** `FastStreamConfig.prometheus_collector_registry: prometheus_client.CollectorRegistry | None` (Task 2), `FastStreamConfig.opentelemetry_excluded_urls: list[str]` (Task 3), `OpenTelemetryConfig` adds no fields (Task 5), `CorsConfig` adds no fields (Task 6). All consistent between definition and usage.
4. **Commit isolation:** each task ends with a single commit scoped to its finding ID.
5. **Cross-task interaction:** Task 5 modifies the `FastAPIConfig.__post_init__` that Task 1 already restructured. The plan orders Task 5 after Task 1 so the `super().__post_init__()` insertion lands cleanly. No other cross-task structural conflicts.
