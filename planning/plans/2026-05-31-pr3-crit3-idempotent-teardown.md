# PR3: Idempotent Teardown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `BaseBootstrapper.teardown()` idempotent so a second call returns immediately without re-tearing-down instruments. Concretely fixes the Litestar and FastStream cases where the bootstrapper registers `self.teardown` on a framework shutdown hook *and* gets called manually — today, second teardown re-invokes every instrument's `teardown()`, which is unsafe because many instruments aren't idempotent themselves.

While we're touching teardown robustness, also bundle the `try/finally` follow-up that PR2's code review flagged: in both `OpenTelemetryInstrument` and `LoggingInstrument`, a raise inside the shutdown call leaves the cached reference non-None. Wrap both in `try/finally` so the cached reference is reset regardless of whether shutdown succeeded.

**Architecture:** Three small behavioral changes — one perimeter guard (the bootstrapper-level idempotency check) and two defense-in-depth changes (instrument-level cleanup robustness). Three new regression tests, one per change. No new files; no API changes.

**Tech Stack:** Python 3.10+, pytest, `unittest.mock.patch.object`, `unittest.mock.MagicMock`.

**Parent spec:** `docs/superpowers/specs/2026-05-31-audit-implementation-sequencing.md` (PR3 section).
**Parent audit:** `docs/superpowers/specs/2026-05-31-bug-refactor-audit.md` (CRIT-3, TEST-3).
**Follow-up from:** PR2 code review (https://github.com/modern-python/lite-bootstrap/pull/90 — "Known follow-up" section in the PR body).

---

## File Structure

Three production files modified; three test files modified.

- Modify: `lite_bootstrap/bootstrappers/base.py:82-93` — add idempotency guard at top of `BaseBootstrapper.teardown()`.
- Modify: `lite_bootstrap/instruments/opentelemetry_instrument.py` — wrap `self._tracer_provider.shutdown()` in `try/finally` so the field resets even on raise.
- Modify: `lite_bootstrap/instruments/logging_instrument.py` — wrap `self._logger_factory.close_handlers()` in `try/finally` so the field resets even on raise.
- Modify: `tests/test_free_bootstrap.py` — add idempotency test using mocked instruments.
- Modify: `tests/instruments/test_opentelemetry_instrument.py` — add `try/finally` regression test using `side_effect=RuntimeError`.
- Modify: `tests/instruments/test_logging_instrument.py` — add `try/finally` regression test using `side_effect=RuntimeError`.

---

## Locked decisions

- **Bundling:** All three changes ship in one commit/PR. They're all "teardown robustness" with high cohesion; PR2's reviewer explicitly suggested doing the `try/finally` work alongside CRIT-3.
- **Test placement:** Idempotency test goes in `test_free_bootstrap.py` (matches sequencing-spec decision; co-located with existing `test_teardown_error_isolation` and `test_teardown_error_aggregates_all_failures`). Instrument-level tests go in the per-instrument test files.
- **Deferred:** A Litestar-specific test exercising the manual-teardown + `on_shutdown`-fires-teardown path is *not* included. The `test_free_bootstrap.py` idempotency test pins the contract; the Litestar path is downstream of that contract.

---

## Task 1: Create branch

**Files:** (no files; git only)

- [ ] **Step 1: Branch off `main`**

```bash
git checkout main
git pull --ff-only origin main
git checkout -b fix/crit-3-idempotent-teardown
```

Expected: `Switched to a new branch 'fix/crit-3-idempotent-teardown'`.

If PR2 (`fix/crit-2-otel-shutdown`) has not yet merged into `main`, that's a real problem for this PR — Task 4 (the OTel `try/finally`) depends on the `_tracer_provider` field that PR2 introduced. **Verify before starting that `lite_bootstrap/instruments/opentelemetry_instrument.py` contains the `_tracer_provider` field declaration.** If it doesn't, stop and report — PR2 must merge first.

```bash
grep -n "_tracer_provider" lite_bootstrap/instruments/opentelemetry_instrument.py
```

Expected output: at least three matches (field declaration, `bootstrap()` setattr, `teardown()` reference). If zero matches, PR2 is not merged — stop.

---

## Task 2: Add three failing regression tests

Add all three failing tests before any production-code change, so the TDD red→green transition is visible per test.

### Test A: `BaseBootstrapper.teardown()` is idempotent

**File:** `tests/test_free_bootstrap.py`

The existing file already imports `MagicMock` from `unittest.mock`. No new imports needed.

- [ ] **Step 1: Append new test to `tests/test_free_bootstrap.py`**

Add at the end of the file (after `test_free_bootstrapper_with_missing_instrument_dependency`):

```python
def test_teardown_is_idempotent(free_bootstrapper_config: FreeBootstrapperConfig) -> None:
    bootstrapper = FreeBootstrapper(bootstrap_config=free_bootstrapper_config)
    bootstrapper.bootstrap()

    first = MagicMock()
    second = MagicMock()
    bootstrapper.instruments = [first, second]

    bootstrapper.teardown()
    bootstrapper.teardown()

    first.teardown.assert_called_once()
    second.teardown.assert_called_once()
    assert not bootstrapper.is_bootstrapped
```

The contract: after the first `teardown()`, `is_bootstrapped` is False; the second call must observe that and return immediately, so each mocked instrument's `teardown()` is called exactly once across both bootstrapper-level calls.

- [ ] **Step 2: Run the test and verify it FAILS**

```bash
just test -- tests/test_free_bootstrap.py::test_teardown_is_idempotent -v
```

Expected: **FAIL** because the current `BaseBootstrapper.teardown()` doesn't check `is_bootstrapped`. Both mocked instruments will have `teardown()` called twice. The assertion `first.teardown.assert_called_once()` raises:

```
AssertionError: Expected 'teardown' to have been called once. Called 2 times.
```

### Test B: `OpenTelemetryInstrument.teardown()` resets `_tracer_provider` when `shutdown()` raises

**File:** `tests/instruments/test_opentelemetry_instrument.py`

The file (after PR2's merge) already imports `patch` from `unittest.mock`. Need to add `pytest` import.

- [ ] **Step 3: Add `pytest` to the test file imports**

Current top of file:

```python
from unittest.mock import patch

from lite_bootstrap.instruments.opentelemetry_instrument import (
    InstrumentorWithParams,
    OpentelemetryConfig,
    OpenTelemetryInstrument,
)
from tests.conftest import CustomInstrumentor
```

Replace with:

```python
from unittest.mock import patch

import pytest

from lite_bootstrap.instruments.opentelemetry_instrument import (
    InstrumentorWithParams,
    OpentelemetryConfig,
    OpenTelemetryInstrument,
)
from tests.conftest import CustomInstrumentor
```

`pytest` goes in the third-party group, between stdlib and first-party.

- [ ] **Step 4: Append new test to the file**

Append at the end:

```python
def test_opentelemetry_instrument_teardown_resets_tracer_provider_when_shutdown_raises() -> None:
    instrument = OpenTelemetryInstrument(
        bootstrap_config=OpentelemetryConfig(opentelemetry_log_traces=True),
    )
    instrument.bootstrap()
    tracer_provider = instrument._tracer_provider  # noqa: SLF001
    assert tracer_provider is not None

    with patch.object(tracer_provider, "shutdown", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError, match="boom"):
            instrument.teardown()

    assert instrument._tracer_provider is None  # noqa: SLF001
```

Contract: even if `shutdown()` raises, the cached reference must be cleared so the instrument can be re-bootstrapped cleanly.

- [ ] **Step 5: Run the test and verify it FAILS**

```bash
just test -- tests/instruments/test_opentelemetry_instrument.py::test_opentelemetry_instrument_teardown_resets_tracer_provider_when_shutdown_raises -v
```

Expected: **FAIL** because the current `teardown()` has `shutdown()` then `setattr(None)` as two sequential statements (no `try/finally`); the RuntimeError propagates, the reset never runs, and the final `assert instrument._tracer_provider is None` fails.

### Test C: `LoggingInstrument.teardown()` resets `_logger_factory` when `close_handlers()` raises

**File:** `tests/instruments/test_logging_instrument.py`

Need to add `pytest` and `patch` imports.

- [ ] **Step 6: Add `patch` and `pytest` to the test file imports**

Current top:

```python
import logging
from io import StringIO

import structlog
from opentelemetry.trace import get_tracer

from lite_bootstrap.instruments.logging_instrument import LoggingConfig, LoggingInstrument, MemoryLoggerFactory
from lite_bootstrap.instruments.opentelemetry_instrument import OpentelemetryConfig, OpenTelemetryInstrument
from tests.conftest import LoggingMock
```

Replace with:

```python
import logging
from io import StringIO
from unittest.mock import patch

import pytest
import structlog
from opentelemetry.trace import get_tracer

from lite_bootstrap.instruments.logging_instrument import LoggingConfig, LoggingInstrument, MemoryLoggerFactory
from lite_bootstrap.instruments.opentelemetry_instrument import OpentelemetryConfig, OpenTelemetryInstrument
from tests.conftest import LoggingMock
```

- [ ] **Step 7: Append new test to the file**

Append at the end:

```python
def test_logging_instrument_teardown_resets_factory_when_close_handlers_raises() -> None:
    instrument = LoggingInstrument(
        bootstrap_config=LoggingConfig(logging_buffer_capacity=0),
    )
    instrument.bootstrap()
    factory = instrument._logger_factory  # noqa: SLF001
    assert factory is not None

    with patch.object(factory, "close_handlers", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError, match="boom"):
            instrument.teardown()

    assert instrument._logger_factory is None  # noqa: SLF001
```

Contract: same shape as Test B — the cached factory reference must be cleared even when `close_handlers()` raises.

- [ ] **Step 8: Run the test and verify it FAILS**

```bash
just test -- tests/instruments/test_logging_instrument.py::test_logging_instrument_teardown_resets_factory_when_close_handlers_raises -v
```

Expected: **FAIL** because the current `LoggingInstrument.teardown()` has `close_handlers()` then `setattr(None)` as two sequential statements; the RuntimeError propagates, the reset never runs, the final `assert instrument._logger_factory is None` fails.

---

## Task 3: Implement the three fixes

### Fix 1: Idempotency guard on `BaseBootstrapper.teardown()`

- [ ] **Step 1: Add guard at top of `BaseBootstrapper.teardown()`**

**File:** `lite_bootstrap/bootstrappers/base.py:82-93`

Current code:

```python
    def teardown(self) -> None:
        self.is_bootstrapped = False
        errors: list[tuple[str, BaseException]] = []
        for one_instrument in reversed(self.instruments):
            try:
                one_instrument.teardown()
            except Exception as e:  # noqa: BLE001, PERF203
                name = type(one_instrument).__name__
                logger.warning(f"Error tearing down {name}: {e}")
                errors.append((name, e))
        if errors:
            raise TeardownError(errors) from errors[0][1]
```

Replace with:

```python
    def teardown(self) -> None:
        if not self.is_bootstrapped:
            return
        self.is_bootstrapped = False
        errors: list[tuple[str, BaseException]] = []
        for one_instrument in reversed(self.instruments):
            try:
                one_instrument.teardown()
            except Exception as e:  # noqa: BLE001, PERF203
                name = type(one_instrument).__name__
                logger.warning(f"Error tearing down {name}: {e}")
                errors.append((name, e))
        if errors:
            raise TeardownError(errors) from errors[0][1]
```

Only the two-line guard at top is added. Everything else is byte-identical.

### Fix 2: `try/finally` in `OpenTelemetryInstrument.teardown()`

- [ ] **Step 2: Wrap `shutdown()` in `try/finally`**

**File:** `lite_bootstrap/instruments/opentelemetry_instrument.py`

Current `teardown()` (after PR2):

```python
    def teardown(self) -> None:
        for one_instrumentor in self.bootstrap_config.opentelemetry_instrumentors:
            if isinstance(one_instrumentor, InstrumentorWithParams):
                one_instrumentor.instrumentor.uninstrument(**one_instrumentor.additional_params)
            else:
                one_instrumentor.uninstrument()
        if self._tracer_provider is not None:
            self._tracer_provider.shutdown()
            object.__setattr__(self, "_tracer_provider", None)
```

Replace the last block (the `if self._tracer_provider is not None:` block) with:

```python
        if self._tracer_provider is not None:
            try:
                self._tracer_provider.shutdown()
            finally:
                object.__setattr__(self, "_tracer_provider", None)
```

### Fix 3: `try/finally` in `LoggingInstrument.teardown()`

- [ ] **Step 3: Wrap `close_handlers()` in `try/finally`**

**File:** `lite_bootstrap/instruments/logging_instrument.py:202-211`

Current code:

```python
    def teardown(self) -> None:
        structlog.reset_defaults()
        root_logger = logging.getLogger()
        for h in root_logger.handlers[:]:
            root_logger.removeHandler(h)
            h.close()
        root_logger.setLevel(logging.WARNING)
        if self._logger_factory is not None:
            self._logger_factory.close_handlers()
            object.__setattr__(self, "_logger_factory", None)
```

Replace the last block with:

```python
        if self._logger_factory is not None:
            try:
                self._logger_factory.close_handlers()
            finally:
                object.__setattr__(self, "_logger_factory", None)
```

### Verification

- [ ] **Step 4: Run the three new tests and verify each PASSES**

```bash
just test -- tests/test_free_bootstrap.py::test_teardown_is_idempotent tests/instruments/test_opentelemetry_instrument.py::test_opentelemetry_instrument_teardown_resets_tracer_provider_when_shutdown_raises tests/instruments/test_logging_instrument.py::test_logging_instrument_teardown_resets_factory_when_close_handlers_raises -v
```

Expected: all three PASS.

- [ ] **Step 5: Run the full test suite**

```bash
just test
```

Expected: all tests PASS. The idempotency guard is additive and shouldn't change any existing behavior — existing tests call `teardown()` exactly once and that path is unchanged. The two `try/finally` changes are non-observable to callers who don't trigger the exception path.

Watch carefully for failures in the existing teardown-error tests in `test_free_bootstrap.py` (`test_teardown_error_isolation`, `test_teardown_error_aggregates_all_failures`) — these tests deliberately make instruments raise during teardown and assert on the resulting `TeardownError`. The guard doesn't affect them because they only call `teardown()` once. Confirm they still pass.

- [ ] **Step 6: Run lint**

```bash
just lint
```

Expected: no errors.

- [ ] **Step 7: Commit**

Stage the six modified files explicitly:

```bash
git add \
  lite_bootstrap/bootstrappers/base.py \
  lite_bootstrap/instruments/opentelemetry_instrument.py \
  lite_bootstrap/instruments/logging_instrument.py \
  tests/test_free_bootstrap.py \
  tests/instruments/test_opentelemetry_instrument.py \
  tests/instruments/test_logging_instrument.py
git commit -m "$(cat <<'EOF'
fix: make teardown idempotent and exception-safe

BaseBootstrapper.teardown() now returns immediately when not bootstrapped.
This fixes Litestar and FastStream, both of which register self.teardown
on a framework shutdown hook while also being callable manually — a user
who explicitly calls teardown() would otherwise re-invoke every instrument's
teardown when the framework shutdown fired second. Most instruments are
not idempotent themselves.

Also wrap the shutdown calls inside OpenTelemetryInstrument and
LoggingInstrument in try/finally so the cached _tracer_provider /
_logger_factory references are reset even when shutdown raises. Without
this, a failed shutdown leaves the instrument in a state where a second
bootstrap reuses a stale reference. The bootstrapper-level guard
prevents the immediate symptom but doesn't help when instruments are
used standalone.

Regression tests:
- test_teardown_is_idempotent: bootstrap, teardown twice, assert each
  instrument's teardown was called exactly once.
- test_opentelemetry_instrument_teardown_resets_tracer_provider_when_shutdown_raises:
  patch shutdown to raise, assert field resets to None.
- test_logging_instrument_teardown_resets_factory_when_close_handlers_raises:
  patch close_handlers to raise, assert field resets to None.

Closes CRIT-3 and TEST-3 from the audit. Resolves the try/finally
follow-up flagged in PR #90's code review.
EOF
)"
```

---

## Task 4: Push and open PR

**Files:** (no files; git push + gh)

- [ ] **Step 1: Push the branch**

```bash
git push -u origin fix/crit-3-idempotent-teardown
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --title "fix: make teardown idempotent and exception-safe" --body "$(cat <<'EOF'
## Summary
- `BaseBootstrapper.teardown()` now returns immediately when `not self.is_bootstrapped`. Fixes the Litestar/FastStream case where manual teardown + framework shutdown hook both fire, double-tearing-down instruments (many of which aren't idempotent).
- `OpenTelemetryInstrument.teardown()` and `LoggingInstrument.teardown()` wrap their shutdown calls in `try/finally` so the cached internal-state references reset even when shutdown raises. Resolves the follow-up flagged in PR #90's code review.

Three regression tests added — one per fix — all fail on `main` and pass on this branch.

Closes CRIT-3 and TEST-3 from an internal audit of the codebase.

## Test plan
- [x] `just test -- tests/test_free_bootstrap.py -v` — all teardown tests pass.
- [x] `just test -- tests/instruments/test_opentelemetry_instrument.py -v` — all OTel tests pass.
- [x] `just test -- tests/instruments/test_logging_instrument.py -v` — all logging tests pass.
- [x] `just test` — full suite passes.
- [x] `just lint` — clean.
- [ ] Reviewer: confirm the bootstrapper guard placement (top of teardown, before `is_bootstrapped = False`) — order matters so the second call observes `is_bootstrapped` as `False` from the first call and returns immediately.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review

**Spec coverage check** against the sequencing spec (PR3 section), audit (CRIT-3, TEST-3), and PR #90's review follow-up:

| Spec item | Task |
|-----------|------|
| Guard at top of `BaseBootstrapper.teardown()` (`if not self.is_bootstrapped: return`) | Task 3, Step 1 |
| Test: bootstrap → teardown → teardown again, assert no double-invoke | Task 2 Test A (Steps 1-2) |
| Test placement in `test_free_bootstrap.py` | Task 2 Test A, Step 1 |
| Branch name `fix/crit-3-idempotent-teardown` | Task 1, Step 1 |
| OTel `try/finally` (follow-up from PR2 review) | Task 3, Step 2 |
| Logging `try/finally` (follow-up from PR2 review) | Task 3, Step 3 |
| OTel regression test for shutdown-raises | Task 2 Test B (Steps 3-5) |
| Logging regression test for close_handlers-raises | Task 2 Test C (Steps 6-8) |
| Verification: `just test` + `just lint` clean | Task 3, Steps 5-6 |

All spec items covered. No placeholders. Field-name consistency holds (`_tracer_provider`, `_logger_factory`, `is_bootstrapped`) across tests and implementations. Each `try/finally` uses the same shape: `try: <shutdown-call>; finally: object.__setattr__(self, "<field>", None)`.

**Deferred (not in this PR):**
- Litestar-specific test exercising the manual-teardown + `on_shutdown` path.
- FastStream-specific test of the same pattern.
- Adding a `try/finally` review across other instruments (none currently store cached internal state that needs resetting on teardown).
