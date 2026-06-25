# Stdlib Logging + `build_summary()` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `_get_logger()` structlog indirection in `lite_bootstrap/bootstrappers/base.py` with a module-level stdlib `logging` logger, and add a public `build_summary()` method on `BaseBootstrapper` that returns a multi-line human-readable description of configured + skipped instruments. The same string the INFO summary log emits is available for post-construction debugging.

**Architecture:** One prod-side change (`bootstrappers/base.py`): delete the `try: import structlog / _get_logger / except` block, add `logger = logging.getLogger(__name__)` at module scope, add `build_summary()` method, and route both the `__init__` summary log and the teardown error log through the stdlib logger. Two test sites migrate from `structlog.testing.capture_logs()` to pytest's `caplog`. Two new tests added: a `build_summary()` format test, and a silent-skip regression test that locks in the contract that config-driven skips emit no warnings. Docs follow.

**Tech Stack:** Python 3.10+, stdlib `logging`, pytest (`caplog`), ruff, `ty`.

**Parent spec:** `./design.md`

---

## File Structure

| File | Change |
|------|--------|
| `lite_bootstrap/bootstrappers/base.py` | Delete `_get_logger()` block. Add `logger = logging.getLogger(__name__)` at module scope. Add `build_summary()` method on `BaseBootstrapper`. Replace `_get_logger().info(...)` and `_get_logger().warning(...)` calls. |
| `tests/test_free_bootstrap.py` | Migrate `test_teardown_error_isolation` and `test_free_bootstrap_emits_summary_log` from `capture_logs` to `caplog`. Add `test_config_skip_emits_no_warning`. Add `test_build_summary_format`. Drop `capture_logs` import; add `logging` and `warnings` imports. |
| `CLAUDE.md` | Replace the `_get_logger()` sentence with the `build_summary()` description. |
| `docs/introduction/configuration.md` | Append one paragraph documenting `build_summary()`. |
| `docs/superpowers/plans/2026-06-01-instrument-skip-rework.md` | One-line supersession note at the top. |

No new files. No instrument or exception class touched.

---

## Pre-flight grep verification

Before starting, confirm the scope matches reality:

```bash
grep -rn "_get_logger\|capture_logs" lite_bootstrap/ tests/ --include="*.py"
```

Expected:
- `lite_bootstrap/bootstrappers/base.py`: 4 matches (definition in try/except + 2 call sites: `__init__` summary log, teardown warning).
- `tests/test_free_bootstrap.py`: 3 matches (import + 2 `with capture_logs()` blocks).
- No matches anywhere else.

```bash
grep -n "logger = " lite_bootstrap/bootstrappers/base.py
```

Expected: 0 matches today (the file uses `_get_logger()`, not a module-level `logger`).

```bash
grep -rn "build_summary" lite_bootstrap/ tests/ --include="*.py"
```

Expected: 0 matches today.

---

## Task 1: Add `build_summary()` + module-level stdlib logger + migrate impacted tests

**Files:**
- Modify: `lite_bootstrap/bootstrappers/base.py`
- Modify: `tests/test_free_bootstrap.py`

This task lands the prod change and the test migration in one commit because the two `capture_logs()` test sites break the moment the logging backend switches — they must move together.

- [ ] **Step 1.1: Write the failing `build_summary()` format test**

Open `tests/test_free_bootstrap.py`. Append at the end of the file:

```python
def test_build_summary_format() -> None:
    bootstrapper = FreeBootstrapper(
        bootstrap_config=FreeConfig(
            sentry_dsn="https://testdsn@localhost/1",
            sentry_additional_params={"transport": SentryTestTransport()},
            logging_enabled=False,
            logging_buffer_capacity=0,
        ),
    )
    summary = bootstrapper.build_summary()
    assert summary.startswith("FreeBootstrapper:")
    assert "  configured:" in summary
    assert "  skipped:" in summary
    assert "    - SentryInstrument" in summary
    assert "    - LoggingInstrument: logging_enabled is False" in summary
```

- [ ] **Step 1.2: Run the new test to confirm it fails**

Run: `uv run pytest tests/test_free_bootstrap.py::test_build_summary_format -v`

Expected: `AttributeError: 'FreeBootstrapper' object has no attribute 'build_summary'`.

- [ ] **Step 1.3: Replace `_get_logger()` block with module-level stdlib logger**

Open `lite_bootstrap/bootstrappers/base.py`. Replace lines 15–32 (the entire `try: import structlog / def _get_logger(): ... / except ImportError: def _get_logger(): ...` block) with:

```python
logger = logging.getLogger(__name__)
```

After this edit, the top of the file reads:

```python
import abc
import logging
import typing
import warnings

from lite_bootstrap.exceptions import (
    BootstrapperNotReadyError,
    InstrumentDependencyMissingWarning,
    TeardownError,
)
from lite_bootstrap.instruments.base import BaseConfig, BaseInstrument
from lite_bootstrap.types import ApplicationT


logger = logging.getLogger(__name__)


InstrumentT = typing.TypeVar("InstrumentT", bound=BaseInstrument)
```

- [ ] **Step 1.4: Add `build_summary()` method**

In the same file, inside `class BaseBootstrapper`, add `build_summary()` immediately after the `bootstrap_config: BaseConfig` field declaration and before `def __init__`. Result:

```python
    skipped_instruments: list[tuple[type[BaseInstrument], str]]
    bootstrap_config: BaseConfig

    def build_summary(self) -> str:
        """Return a multi-line human-readable summary of configured + skipped instruments.

        Useful for INFO-level diagnostic logging (called once by ``__init__``) and for
        post-construction debugging (e.g. from a REPL or a health endpoint).
        """
        lines = [f"{type(self).__name__}:", "  configured:"]
        if self.instruments:
            lines.extend(f"    - {type(i).__name__}" for i in self.instruments)
        else:
            lines.append("    (none)")
        lines.append("  skipped:")
        if self.skipped_instruments:
            lines.extend(f"    - {cls.__name__}: {reason}" for cls, reason in self.skipped_instruments)
        else:
            lines.append("    (none)")
        return "\n".join(lines)

    def __init__(self, bootstrap_config: BaseConfig) -> None:
```

- [ ] **Step 1.5: Replace the `__init__` summary log call**

In the same file, find the `__init__` summary log at the end of the loop (currently lines 70–74):

```python
        _get_logger().info(
            f"{type(self).__name__}: "
            f"configured={[type(i).__name__ for i in self.instruments]}, "
            f"skipped={[(cls.__name__, reason) for cls, reason in self.skipped_instruments]}"
        )
```

Replace with:

```python
        logger.info(self.build_summary())
```

- [ ] **Step 1.6: Replace the teardown error log call**

In the same file, find the teardown error log (currently line 104):

```python
                _get_logger().warning(f"Error tearing down {name}: {e}")
```

Replace with:

```python
                logger.warning("Error tearing down %s: %s", name, e)
```

- [ ] **Step 1.7: Run the format test to confirm it passes**

Run: `uv run pytest tests/test_free_bootstrap.py::test_build_summary_format -v`

Expected: PASS.

- [ ] **Step 1.8: Migrate `test_teardown_error_isolation` from `capture_logs` to `caplog`**

Open `tests/test_free_bootstrap.py`. Replace the existing `test_teardown_error_isolation` function (currently lines 56–73) with:

```python
def test_teardown_error_isolation(
    free_bootstrapper_config: FreeConfig, caplog: pytest.LogCaptureFixture
) -> None:
    bootstrapper = FreeBootstrapper(bootstrap_config=free_bootstrapper_config)
    bootstrapper.bootstrap()

    # Replace instruments with mocks: first raises, second succeeds.
    bad = MagicMock()
    bad.teardown.side_effect = RuntimeError("boom")
    good = MagicMock()
    bootstrapper.instruments = [bad, good]

    with (
        caplog.at_level(logging.WARNING, logger="lite_bootstrap.bootstrappers.base"),
        pytest.raises(TeardownError, match="boom") as excinfo,
    ):
        bootstrapper.teardown()

    # Both instruments attempted teardown despite the error (LIFO: good first, bad second).
    good.teardown.assert_called_once()
    bad.teardown.assert_called_once()
    assert any("boom" in r.message for r in caplog.records)
    assert excinfo.value.errors == [("MagicMock", excinfo.value.__cause__)]
```

- [ ] **Step 1.9: Migrate `test_free_bootstrap_emits_summary_log` from `capture_logs` to `caplog`**

Replace the existing `test_free_bootstrap_emits_summary_log` (currently lines 144–156) with:

```python
def test_free_bootstrap_emits_summary_log(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="lite_bootstrap.bootstrappers.base"):
        FreeBootstrapper(
            bootstrap_config=FreeConfig(
                sentry_dsn="https://testdsn@localhost/1",
                sentry_additional_params={"transport": SentryTestTransport()},
            ),
        )
    summary_records = [r for r in caplog.records if "FreeBootstrapper" in r.message]
    assert summary_records, "expected a summary log entry mentioning FreeBootstrapper"
    summary = summary_records[-1].message
    assert "configured:" in summary
    assert "skipped:" in summary
```

- [ ] **Step 1.10: Update test-file imports**

In `tests/test_free_bootstrap.py`, change the top-of-file imports. Currently:

```python
from unittest.mock import MagicMock

import pytest
import structlog
from structlog.testing import capture_logs

from lite_bootstrap import (
    FreeBootstrapper,
    FreeConfig,
    TeardownError,
)
```

Change to:

```python
import logging
from unittest.mock import MagicMock

import pytest
import structlog

from lite_bootstrap import (
    FreeBootstrapper,
    FreeConfig,
    TeardownError,
)
```

(`capture_logs` import dropped; `logging` added. The module-level `import structlog` and `logger = structlog.getLogger(__name__)` on the line that follows the import block stay — they're used by `test_free_bootstrap` to emit an application-level log line through the configured `LoggingInstrument`.)

- [ ] **Step 1.11: Run the full `test_free_bootstrap.py` suite**

Run: `uv run pytest tests/test_free_bootstrap.py -v`

Expected: all tests pass, including the migrated `test_teardown_error_isolation`, the migrated `test_free_bootstrap_emits_summary_log`, and the new `test_build_summary_format`.

- [ ] **Step 1.12: Run lint**

Run: `just lint`

Expected: clean (ruff format, ruff check, ty check).

If lint complains about an unused `typing` import on `bootstrappers/base.py`, leave the import — `typing.ClassVar`, `typing.Generic`, `typing.TypeVar` are still used in the file body.

- [ ] **Step 1.13: Commit**

```bash
git add lite_bootstrap/bootstrappers/base.py tests/test_free_bootstrap.py
git commit -m "$(cat <<'EOF'
refactor: use stdlib logging in BaseBootstrapper; add build_summary()

Replace the _get_logger() structlog indirection with a module-level
logging.getLogger(__name__). The two log sites (INFO summary in __init__,
WARNING teardown error) describe bootstrapper lifecycle, not application
events, so stdlib logging is appropriate. Removes a global-structlog-state
landmine introduced by the previous fresh-per-call workaround.

Add BaseBootstrapper.build_summary() returning a multi-line human-readable
description of configured + skipped instruments. __init__ uses it for the
INFO summary; users can call it post-construction for debugging.

Migrate the two test sites that used structlog.testing.capture_logs() to
pytest's caplog fixture.
EOF
)"
```

---

## Task 2: Add silent-skip regression test

**Files:**
- Modify: `tests/test_free_bootstrap.py`

Locks in the contract this PR was designed to deliver: config-driven skip emits NO warning. Without this test, a future regression that re-adds `warnings.warn` to the `is_configured` False branch would pass CI.

- [ ] **Step 2.1: Add the silent-skip test**

Append to `tests/test_free_bootstrap.py` (after `test_build_summary_format`):

```python
def test_config_skip_emits_no_warning() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # any UserWarning becomes a test failure
        bootstrapper = FreeBootstrapper(
            bootstrap_config=FreeConfig(
                logging_enabled=False,
                logging_buffer_capacity=0,
            ),
        )
    assert LoggingInstrument in {cls for cls, _ in bootstrapper.skipped_instruments}
```

- [ ] **Step 2.2: Add the `warnings` import**

In `tests/test_free_bootstrap.py`, add `import warnings` to the stdlib import block at the top of the file:

```python
import logging
import warnings
from unittest.mock import MagicMock
```

- [ ] **Step 2.3: Run the new test**

Run: `uv run pytest tests/test_free_bootstrap.py::test_config_skip_emits_no_warning -v`

Expected: PASS. (Config-driven skip is already silent under the current `is_configured` flow; this test locks it in.)

- [ ] **Step 2.4: Run lint**

Run: `just lint`

Expected: clean.

- [ ] **Step 2.5: Commit**

```bash
git add tests/test_free_bootstrap.py
git commit -m "$(cat <<'EOF'
test: lock in silent-skip contract for config-driven instrument skip

Asserts that constructing a bootstrapper with instruments whose config
indicates they should not run emits zero UserWarnings. Without this
regression test, a future change that re-introduces warnings.warn to the
is_configured=False branch would pass CI.
EOF
)"
```

---

## Task 3: Documentation updates

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/introduction/configuration.md`
- Modify: `docs/superpowers/plans/2026-06-01-instrument-skip-rework.md`

- [ ] **Step 3.1: Update `CLAUDE.md`**

In `CLAUDE.md`, find the "Instrument skip ordering" bullet. It currently ends with:

> The bootstrappers/base.py logger is obtained fresh per call (`_get_logger()`) instead of cached at module level, so `structlog.testing.capture_logs()` can override processors at test time even after `LoggingInstrument.bootstrap()` sets `cache_logger_on_first_use=True`.

Replace that sentence (keep the surrounding bullet content untouched) with:

> One `logger.info` summary line at the end lists configured + skipped instruments via `BaseBootstrapper.build_summary()`; that method is also publicly callable for post-construction debugging. Uses stdlib `logging` so it composes cleanly with the user's logging setup and with pytest's `caplog`.

- [ ] **Step 3.2: Append `build_summary()` paragraph to `configuration.md`**

In `docs/introduction/configuration.md`, find the "Skipped instruments" section that ends with the `for cls, reason in bootstrapper.skipped_instruments` example. After that code block, append:

```markdown
To get a human-readable view of the same information at any later point (e.g. for debugging from a REPL or a health endpoint), call `bootstrapper.build_summary()`. It returns the multi-line string that the INFO summary log emits — useful when log levels are filtered or when you want to render the bootstrapper state inline.
```

- [ ] **Step 3.3: Add supersession note to the previous plan**

Open `docs/superpowers/plans/2026-06-01-instrument-skip-rework.md`. Immediately after the H1 title line (`# Instrument Skip Rework Implementation Plan`), insert a blockquote:

```markdown
> **Note (2026-06-02):** the `_get_logger()` fresh-per-call decision documented below was revised by `docs/superpowers/specs/2026-06-02-stdlib-logging-and-build-summary-design.md`. The summary-log goal is unchanged; the implementation switched to stdlib `logging` with a public `build_summary()` method.
```

- [ ] **Step 3.4: Commit**

```bash
git add CLAUDE.md docs/introduction/configuration.md docs/superpowers/plans/2026-06-01-instrument-skip-rework.md
git commit -m "$(cat <<'EOF'
docs: document build_summary() and remove _get_logger() rationale

CLAUDE.md and configuration.md now describe the build_summary() method and
the stdlib logging backend. The previous instrument-skip-rework plan gets a
supersession note pointing at the new design.
EOF
)"
```

---

## Task 4: Full verification

**Files:** (no edits; verification only)

- [ ] **Step 4.1: Run full test suite**

Run: `just test`

Expected: 152 tests pass (the existing 150 from PR #107 plus the two new tests added in Tasks 1 and 2).

- [ ] **Step 4.2: Run lint in CI mode**

Run: `just lint-ci`

Expected: clean.

- [ ] **Step 4.3: Confirm grep success criteria**

```bash
grep -rn "_get_logger" lite_bootstrap/ tests/ --include="*.py"
```

Expected: 0 matches.

```bash
grep -rn "capture_logs" tests/test_free_bootstrap.py
```

Expected: 0 matches.

```bash
grep -rn "build_summary" lite_bootstrap/ tests/ --include="*.py"
```

Expected: 4 matches — (1) method `def build_summary` in `lite_bootstrap/bootstrappers/base.py`, (2) call site `logger.info(self.build_summary())` in the same file, (3) test function name `def test_build_summary_format` in `tests/test_free_bootstrap.py`, (4) call `bootstrapper.build_summary()` inside that test.

If counts diverge, investigate before proceeding.

- [ ] **Step 4.4: No commit needed**

Task 4 is verification only. If something failed, address it as a fix-up commit, not a force-push.

---

## Self-Review

**Spec coverage check** (against `docs/superpowers/specs/2026-06-02-stdlib-logging-and-build-summary-design.md`):

| Spec item | Plan task |
|-----------|-----------|
| Delete `_get_logger()` block | Task 1, Step 1.3 |
| Module-level `logger = logging.getLogger(__name__)` | Task 1, Step 1.3 |
| `build_summary()` method | Task 1, Step 1.4 (test 1.1) |
| `__init__` calls `logger.info(self.build_summary())` | Task 1, Step 1.5 |
| Teardown uses `logger.warning("...", name, e)` (lazy `%`-format) | Task 1, Step 1.6 |
| Migrate `test_teardown_error_isolation` to `caplog` | Task 1, Step 1.8 |
| Migrate `test_free_bootstrap_emits_summary_log` to `caplog` | Task 1, Step 1.9 |
| Drop `capture_logs` import; add `logging`, `warnings` | Task 1 Step 1.10 + Task 2 Step 2.2 |
| New `test_build_summary_format` | Task 1, Step 1.1 |
| New `test_config_skip_emits_no_warning` | Task 2, Step 2.1 |
| `CLAUDE.md` update | Task 3, Step 3.1 |
| `configuration.md` paragraph | Task 3, Step 3.2 |
| Supersession note on prior plan | Task 3, Step 3.3 |

All spec items covered.

**Placeholder scan:** None of the disallowed phrases (TBD, TODO, "implement later", "similar to Task N") appear; every code step shows the exact code. Verified.

**Type / name consistency:** `build_summary` used as method name throughout. `logger` (lowercase) used at module scope in every call site. Test fixtures use `caplog: pytest.LogCaptureFixture` consistently. Logger name string `"lite_bootstrap.bootstrappers.base"` used identically in both migrated tests.
