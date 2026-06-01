# PR14: Configurable FastStream Broker Health-Check Timeout (REF-7)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `FastStreamHealthChecksInstrument._define_health_status` calls `broker.ping(timeout=5)` with a hardcoded 5-second timeout. For users with slow brokers (large Redis clusters, message queues with cold connections), this is a footgun. Add a `faststream_health_check_broker_timeout: float = 5.0` field on `FastStreamConfig` and wire it through.

**Architecture:** Pure additive config change. New field with backward-compatible default; existing callers see no behavior difference. One new regression test.

**Tech Stack:** Python 3.10+ dataclasses, faststream, `unittest.mock.AsyncMock`.

**Parent spec:** `docs/superpowers/specs/2026-06-01-deferred-refactors-sequencing.md` (PR14 section).
**Parent audit:** `docs/superpowers/specs/2026-05-31-bug-refactor-audit.md` (REF-7).

---

## File Structure

Two files modified.

- Modify: `lite_bootstrap/bootstrappers/faststream_bootstrapper.py` — add `faststream_health_check_broker_timeout: float = 5.0` to `FastStreamConfig`; update `FastStreamHealthChecksInstrument._define_health_status` to use it.
- Modify: `tests/test_faststream_bootstrap.py` — add `test_faststream_health_check_uses_configured_broker_timeout` exercising a non-default timeout.

---

## Locked decisions (from sequencing spec)

- **Field placement:** `FastStreamConfig`, NOT shared `HealthChecksConfig`. The timeout is FastStream-shaped (it's specifically about a message broker ping), so it belongs on the FastStream-specific config alongside other FastStream-only fields (`faststream_log_level`, `opentelemetry_middleware_cls`, etc.). Putting it on `HealthChecksConfig` would pollute FastAPI/Litestar configs with an unused field.
- **Default `5.0`:** Preserves existing behavior. Users who don't set the field see no change.
- **Field name:** `faststream_health_check_broker_timeout`. Prefixed `faststream_` for consistency with the other FastStream-specific fields on this config.

---

## Task 1: Create branch

**Files:** (no files; git only)

- [ ] **Step 1: Branch off `main`**

```bash
git checkout main
git pull --ff-only origin main
git checkout -b fix/ref-7-faststream-timeout
```

Expected: `Switched to a new branch 'fix/ref-7-faststream-timeout'`.

---

## Task 2: Add the failing regression test

**File:** `tests/test_faststream_bootstrap.py`

The existing file uses `RedisBroker` fixtures and `TestClient` from starlette to exercise the health check. We'll spy on `broker.ping` to capture the timeout argument.

### Step 1: Update imports

Current top of file:

```python
import logging
import typing

import faststream.asgi
import pytest
import structlog
from faststream._internal.broker import BrokerUsecase
from faststream._internal.logger.params_storage import ManualLoggerStorage
from faststream.redis import RedisBroker, TestRedisBroker
...
```

Add `dataclasses` (stdlib) and `from unittest.mock import AsyncMock, patch` (stdlib). After:

```python
import dataclasses
import logging
import typing
from unittest.mock import AsyncMock, patch

import faststream.asgi
import pytest
import structlog
from faststream._internal.broker import BrokerUsecase
from faststream._internal.logger.params_storage import ManualLoggerStorage
from faststream.redis import RedisBroker, TestRedisBroker
...
```

(Preserve any existing imports between these — only adding the three new lines in the right import groups.)

### Step 2: Append the new test

At the end of the file, add:

```python
async def test_faststream_health_check_uses_configured_broker_timeout(broker: RedisBroker) -> None:
    expected_timeout = 12.5
    config = dataclasses.replace(
        build_faststream_config(broker=broker),
        faststream_health_check_broker_timeout=expected_timeout,
    )
    bootstrapper = FastStreamBootstrapper(bootstrap_config=config)
    application = bootstrapper.bootstrap()
    try:
        with (
            patch.object(broker, "ping", new=AsyncMock(return_value=True)) as mock_ping,
            TestClient(app=application) as test_client,
        ):
            response = test_client.get(config.health_checks_path)
            assert response.status_code == status.HTTP_200_OK
        mock_ping.assert_called_once_with(timeout=expected_timeout)
    finally:
        bootstrapper.teardown()
```

Contract:
- `dataclasses.replace` on a `FastStreamConfig` (still `frozen=True` post-PR13) creates a new instance overriding only the timeout.
- `patch.object(broker, "ping", new=AsyncMock(return_value=True))` replaces `broker.ping` with an async mock that returns `True` (healthy).
- `TestClient(app=application).get(config.health_checks_path)` triggers the health check, which calls `await broker.ping(timeout=...)`.
- `mock_ping.assert_called_once_with(timeout=expected_timeout)` asserts the configured value reached the broker.

Note: `expected_timeout = 12.5` extracts the magic value into a named local — per the no-`PLR2004`-noqa policy established in PR10.

### Step 3: Run the test and verify it FAILS

```bash
just test -- 'tests/test_faststream_bootstrap.py::test_faststream_health_check_uses_configured_broker_timeout' -v
```

Expected: **FAIL** in one of two ways:
- `AttributeError: 'FastStreamConfig' object has no attribute 'faststream_health_check_broker_timeout'` (the field doesn't exist yet on the config).
- Or: `AssertionError: expected call: ping(timeout=12.5)\nactual call: ping(timeout=5)` (if the field is somehow on the config but the instrument still hardcodes `5`).

Either way, the test should NOT pass before the fix. If it does, stop and investigate.

---

## Task 3: Implement the fix

**File:** `lite_bootstrap/bootstrappers/faststream_bootstrapper.py`

### Step 1: Add field to `FastStreamConfig`

Locate `FastStreamConfig`. Current:

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class FastStreamConfig(
    HealthChecksConfig, LoggingConfig, OpentelemetryConfig, PrometheusConfig, PyroscopeConfig, SentryConfig
):
    application: "AsgiFastStream" = dataclasses.field(default_factory=_make_asgi_faststream)
    opentelemetry_middleware_cls: type[FastStreamTelemetryMiddlewareProtocol] | None = None
    prometheus_middleware_cls: type[FastStreamPrometheusMiddlewareProtocol] | None = None
    faststream_log_level: int = logging.WARNING
```

Add the new field at the end of the body:

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class FastStreamConfig(
    HealthChecksConfig, LoggingConfig, OpentelemetryConfig, PrometheusConfig, PyroscopeConfig, SentryConfig
):
    application: "AsgiFastStream" = dataclasses.field(default_factory=_make_asgi_faststream)
    opentelemetry_middleware_cls: type[FastStreamTelemetryMiddlewareProtocol] | None = None
    prometheus_middleware_cls: type[FastStreamPrometheusMiddlewareProtocol] | None = None
    faststream_log_level: int = logging.WARNING
    faststream_health_check_broker_timeout: float = 5.0
```

Single additive change.

### Step 2: Use the field in `FastStreamHealthChecksInstrument._define_health_status`

Locate `_define_health_status`. Current:

```python
    async def _define_health_status(self) -> bool:
        if not self.bootstrap_config.application or not self.bootstrap_config.application.broker:
            return False

        return await self.bootstrap_config.application.broker.ping(timeout=5)
```

Replace the hardcoded `timeout=5` with `timeout=self.bootstrap_config.faststream_health_check_broker_timeout`:

```python
    async def _define_health_status(self) -> bool:
        if not self.bootstrap_config.application or not self.bootstrap_config.application.broker:
            return False

        return await self.bootstrap_config.application.broker.ping(
            timeout=self.bootstrap_config.faststream_health_check_broker_timeout,
        )
```

The expression is long enough that ruff will likely format it as multi-line (as shown). If ruff formats differently, accept its choice.

### Step 3: Run the new test, verify PASS

```bash
just test -- 'tests/test_faststream_bootstrap.py::test_faststream_health_check_uses_configured_broker_timeout' -v
```

Expected: PASS.

### Step 4: Run the full FastStream test file

```bash
just test -- tests/test_faststream_bootstrap.py -v
```

Expected: all tests PASS. Watch the existing `test_faststream_bootstrap` (which exercises the health check via a real broker connection) — the default `5.0` is identical to the prior hardcoded `5`, so behavior should be unchanged.

### Step 5: Run the full test suite

```bash
just test
```

Expected: 129/129 (128 prior + 1 new).

### Step 6: Run lint

```bash
just lint
```

Expected: clean. The new field's `: float = 5.0` annotation should not trigger any ruff complaints; the test's `expected_timeout = 12.5` named-local pattern avoids PLR2004.

### Step 7: Commit

Stage the two modified files explicitly:

```bash
git add \
  lite_bootstrap/bootstrappers/faststream_bootstrapper.py \
  tests/test_faststream_bootstrap.py
git commit -m "$(cat <<'EOF'
feat: configurable broker ping timeout for FastStream health check

FastStreamHealthChecksInstrument._define_health_status called
broker.ping(timeout=5) with a hardcoded 5-second timeout. For users
with slow brokers (large Redis clusters under load, message queues
with cold connections), this is a footgun.

Add faststream_health_check_broker_timeout: float = 5.0 to
FastStreamConfig. Default preserves the existing behavior; users can
now override.

The field lives on FastStreamConfig (not the shared HealthChecksConfig)
because the timeout is FastStream-shaped — it's specifically about a
message broker ping, not a generic concern that FastAPI/Litestar
health checks would share.

Regression test patches broker.ping to assert the configured timeout
value reaches it.

Closes REF-7 from the audit.
EOF
)"
```

---

## Task 4: Push and open PR

- [ ] **Step 1: Push the branch**

```bash
git push -u origin fix/ref-7-faststream-timeout
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --title "feat: configurable broker ping timeout for FastStream health check" --body "$(cat <<'EOF'
## Summary
- Added `faststream_health_check_broker_timeout: float = 5.0` to `FastStreamConfig`.
- `FastStreamHealthChecksInstrument._define_health_status` now reads from the config instead of the previously hardcoded `timeout=5`.
- New regression test patches `broker.ping` and asserts the configured value reaches it.

Default preserves existing behavior — pure-additive config option. Users with slow brokers can now bump the timeout without forking the library.

Closes REF-7 from an internal audit.

## Test plan
- [x] `just test -- 'tests/test_faststream_bootstrap.py::test_faststream_health_check_uses_configured_broker_timeout' -v` — pass.
- [x] `just test` — 129/129.
- [x] `just lint` — clean.
- [ ] Reviewer: confirm the field lives on `FastStreamConfig` (not `HealthChecksConfig`) — this was the locked decision in the sequencing spec because the timeout is FastStream-shaped.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review

**Spec coverage check** against the sequencing spec (PR14 section) and audit (REF-7):

| Spec item | Task |
|-----------|------|
| Add `faststream_health_check_broker_timeout: float = 5.0` to `FastStreamConfig` | Task 3, Step 1 |
| Update `_define_health_status` to use the field instead of hardcoded `5` | Task 3, Step 2 |
| Add a regression test asserting the configured timeout reaches `broker.ping` | Task 2, Step 2 |
| Field on `FastStreamConfig`, NOT `HealthChecksConfig` (locked decision Q5) | Task 3, Step 1 |
| Branch name `fix/ref-7-faststream-timeout` | Task 1, Step 1 |
| Verification: `just test` + `just lint` clean | Task 3, Steps 5-6 |
| `expected_timeout = 12.5` named local (no PLR2004 noqa) | Task 2, Step 2 |

All spec items covered. No placeholders. Risk: low — additive change with a backward-compatible default.
