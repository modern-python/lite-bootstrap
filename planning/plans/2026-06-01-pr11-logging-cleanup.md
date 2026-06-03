# PR11: Logging Cleanup + Lifecycle Test (REF-4 + REF-2 + LOW-6 + LOW-8 + LOW-9 + TEST-8)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The biggest PR of the deferred-refactors sequence. Bundles six logging-area items:
- **REF-4**: Split `logging_instrument.py` (212 lines) into a new `logging_factory.py` (factory + serializer + protocols) plus a slimmer `logging_instrument.py` (config + instrument + tracer injection).
- **REF-2**: Delete the dead `if import_checker.is_structlog_installed and import_checker.is_litestar_installed:` defensive check in `LitestarLoggingInstrument.bootstrap()`.
- **LOW-6**: Wrap `MemoryLoggerFactory`'s 4 logging-config kwargs into an internal `_MemoryLoggerFactoryConfig` dataclass.
- **LOW-8**: Add a docstring to `LoggingInstrument._unset_handlers` documenting that the mutation is permanent.
- **LOW-9**: Add a docstring to `LoggingInstrument.teardown()` documenting that root logger level is unconditionally reset to WARNING.
- **TEST-8**: Add a bootstrap→teardown→bootstrap→teardown lifecycle replay test.

**Architecture:** One new module file, one production refactor (the split), one cross-file dead-code removal, two docstring additions, one test update, one new test. Backward compatibility is preserved by re-exporting moved symbols from `logging_instrument.py`.

**Tech Stack:** Python 3.10+ dataclasses, structlog, pytest.

**Parent spec:** `docs/superpowers/specs/2026-06-01-deferred-refactors-sequencing.md` (PR11 section).
**Parent audit:** `docs/superpowers/specs/2026-05-31-bug-refactor-audit.md` (REF-2, REF-4, LOW-6, LOW-8, LOW-9, TEST-8).

---

## File Structure

5 files touched.

- Create: `lite_bootstrap/instruments/logging_factory.py` — `MemoryLoggerFactory`, `_MemoryLoggerFactoryConfig`, `_serialize_log_with_orjson_to_string`, `AddressProtocol`, `RequestProtocol`, `ScopeType`.
- Modify: `lite_bootstrap/instruments/logging_instrument.py` — slim to `LoggingConfig`, `LoggingInstrument`, `tracer_injection`; re-import the moved symbols for backward compat; add LOW-8 / LOW-9 docstrings.
- Modify: `lite_bootstrap/bootstrappers/litestar_bootstrapper.py` — REF-2: delete the dead defensive check, unindent the body.
- Modify: `tests/instruments/test_logging_instrument.py` — update `MemoryLoggerFactory` instantiations to use `_MemoryLoggerFactoryConfig`; add `test_logging_instrument_lifecycle_replay`.

---

## Locked decisions (from sequencing spec)

- **Internal config dataclass for `MemoryLoggerFactory`:** Prefix `_MemoryLoggerFactoryConfig` (underscore = internal). Not exported from `__init__.py`. Tests import it via the underscore-prefixed name.
- **Backward compat for moved symbols:** `MemoryLoggerFactory`, `AddressProtocol`, `RequestProtocol`, `ScopeType` are re-imported into `logging_instrument.py` so existing `from lite_bootstrap.instruments.logging_instrument import MemoryLoggerFactory` imports continue to work.
- **No PLR2004 noqa for magic-value test assertions.** If ruff complains about a numeric literal in a test assertion (e.g., `assert config.x == 10`), extract the value to a named local variable. See PR10's `expected_max_age = 600` pattern.

---

## Task 1: Create branch

**Files:** (no files; git only)

- [ ] **Step 1: Branch off `main`**

```bash
git checkout main
git pull --ff-only origin main
git checkout -b refactor/ref-4-logging-cleanup
```

Expected: `Switched to a new branch 'refactor/ref-4-logging-cleanup'`.

---

## Task 2: Apply all six changes, verify, commit

The order of steps below is important — start with the file split (steps 1-3), then dead code removal (step 4), then docstrings (step 5), then test updates (steps 6-7), then verify.

### Step 1: Create `lite_bootstrap/instruments/logging_factory.py`

New file with full contents:

```python
import dataclasses
import logging
import logging.handlers
import sys
import typing

import orjson

from lite_bootstrap import import_checker


ScopeType = typing.MutableMapping[str, typing.Any]


class AddressProtocol(typing.Protocol):
    host: str
    port: int


class RequestProtocol(typing.Protocol):
    client: AddressProtocol
    scope: ScopeType
    method: str


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class _MemoryLoggerFactoryConfig:
    logging_buffer_capacity: int
    logging_flush_level: int
    logging_log_level: int
    log_stream: typing.Any = sys.stdout  # noqa: ANN401


def _serialize_log_with_orjson_to_string(value: typing.Any, **kwargs: typing.Any) -> str:  # noqa: ANN401
    return orjson.dumps(value, **kwargs).decode()


if import_checker.is_structlog_installed:
    import structlog

    class MemoryLoggerFactory(structlog.stdlib.LoggerFactory):
        def __init__(
            self,
            *args: typing.Any,  # noqa: ANN401
            config: "_MemoryLoggerFactoryConfig",
            **kwargs: typing.Any,  # noqa: ANN401
        ) -> None:
            super().__init__(*args, **kwargs)
            self.config = config
            self._created_handlers: list[tuple[logging.Logger, logging.handlers.MemoryHandler]] = []

        def __call__(self, *args: typing.Any) -> logging.Logger:  # noqa: ANN401
            logger: typing.Final = super().__call__(*args)
            stream_handler: typing.Final = logging.StreamHandler(stream=self.config.log_stream)
            handler: typing.Final = logging.handlers.MemoryHandler(
                capacity=self.config.logging_buffer_capacity,
                flushLevel=self.config.logging_flush_level,
                target=stream_handler,
            )
            logger.addHandler(handler)
            logger.setLevel(self.config.logging_log_level)
            logger.propagate = False
            self._created_handlers.append((logger, handler))
            return logger

        def close_handlers(self) -> None:
            for created_logger, handler in self._created_handlers:
                created_logger.removeHandler(handler)
                created_logger.propagate = True
                target = handler.target
                handler.close()
                if target is not None:
                    target.close()
            self._created_handlers.clear()
```

Notes on the structlog gate:
- `MemoryLoggerFactory` MUST be inside the gate because it inherits from `structlog.stdlib.LoggerFactory`.
- `_MemoryLoggerFactoryConfig` and `_serialize_log_with_orjson_to_string` are OUTSIDE the gate — they have no structlog dependency (just stdlib + orjson, both unconditional). This matters because `logging_instrument.py` imports them at module top; if they were gated, the import would fail when structlog isn't installed.
- `ScopeType`, `AddressProtocol`, `RequestProtocol` are unconditional (no structlog dependency).

### Step 2: Rewrite `lite_bootstrap/instruments/logging_instrument.py`

Replace the full file contents with:

```python
import dataclasses
import logging
import logging.handlers
import sys
import typing

from lite_bootstrap import import_checker
from lite_bootstrap.instruments.base import BaseConfig, BaseInstrument
from lite_bootstrap.instruments.logging_factory import (
    AddressProtocol,
    RequestProtocol,
    ScopeType,
    _MemoryLoggerFactoryConfig,
    _serialize_log_with_orjson_to_string,
)


if typing.TYPE_CHECKING:
    from lite_bootstrap.instruments.logging_factory import MemoryLoggerFactory
    from structlog.typing import EventDict, WrappedLogger


if import_checker.is_structlog_installed:
    import structlog

    from lite_bootstrap.instruments.logging_factory import MemoryLoggerFactory


if import_checker.is_opentelemetry_installed:
    from opentelemetry import trace

    def tracer_injection(_: "WrappedLogger", __: str, event_dict: "EventDict") -> "EventDict":
        current_span = trace.get_current_span()
        if not current_span.is_recording():
            event_dict["tracing"] = {}
            return event_dict

        current_span_context = current_span.get_span_context()
        event_dict["tracing"] = {
            "span_id": trace.format_span_id(current_span_context.span_id),
            "trace_id": trace.format_trace_id(current_span_context.trace_id),
        }
        return event_dict

else:  # pragma: no cover

    def tracer_injection(_: "WrappedLogger", __: str, event_dict: "EventDict") -> "EventDict":
        return event_dict


__all__ = [
    "AddressProtocol",
    "LoggingConfig",
    "LoggingInstrument",
    "MemoryLoggerFactory",
    "RequestProtocol",
    "ScopeType",
    "tracer_injection",
]


@dataclasses.dataclass(kw_only=True, frozen=True)
class LoggingConfig(BaseConfig):
    logging_log_level: int = logging.INFO
    logging_flush_level: int = logging.ERROR
    logging_buffer_capacity: int = 10
    logging_extra_processors: list[typing.Any] = dataclasses.field(default_factory=list)
    logging_unset_handlers: list[str] = dataclasses.field(
        default_factory=list,
    )
    logging_time_stamper: "structlog.processors.TimeStamper | None" = None
    logging_enabled: bool = True


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class LoggingInstrument(BaseInstrument[LoggingConfig]):
    not_ready_message = "logging_enabled is False"
    missing_dependency_message = "structlog is not installed"
    _logger_factory: "MemoryLoggerFactory | None" = dataclasses.field(
        default_factory=lambda: None, init=False, repr=False, compare=False
    )

    @property
    def structlog_pre_chain_processors(self) -> list[typing.Any]:
        return [
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            tracer_injection,
            structlog.stdlib.PositionalArgumentsFormatter(),
            self.bootstrap_config.logging_time_stamper or structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
        ]

    def is_ready(self) -> bool:
        return self.bootstrap_config.logging_enabled

    @staticmethod
    def check_dependencies() -> bool:
        return import_checker.is_structlog_installed

    def _unset_handlers(self) -> None:
        """Clear handlers on the named loggers. Mutation is permanent; teardown() does not restore."""
        for unset_handlers_logger in self.bootstrap_config.logging_unset_handlers:
            logging.getLogger(unset_handlers_logger).handlers = []

    @property
    def structlog_processors(self) -> list[typing.Any]:
        return [
            structlog.stdlib.filter_by_level,
            *self.structlog_pre_chain_processors,
            *self.bootstrap_config.logging_extra_processors,
            structlog.processors.JSONRenderer(serializer=_serialize_log_with_orjson_to_string),
        ]

    @property
    def memory_logger_factory(self) -> "MemoryLoggerFactory":
        cached: MemoryLoggerFactory | None = self._logger_factory
        if cached is None:
            cached = MemoryLoggerFactory(
                config=_MemoryLoggerFactoryConfig(
                    logging_buffer_capacity=self.bootstrap_config.logging_buffer_capacity,
                    logging_flush_level=self.bootstrap_config.logging_flush_level,
                    logging_log_level=self.bootstrap_config.logging_log_level,
                ),
            )
            object.__setattr__(self, "_logger_factory", cached)
        return cached

    def _configure_structlog_loggers(self) -> None:
        structlog.configure(
            processors=self.structlog_processors,
            context_class=dict,
            logger_factory=self.memory_logger_factory,
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=True,
        )

    def _configure_foreign_loggers(self) -> None:
        root_logger: typing.Final = logging.getLogger()
        stream_handler: typing.Final = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(
            structlog.stdlib.ProcessorFormatter(
                foreign_pre_chain=self.structlog_pre_chain_processors,
                processors=[
                    structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                    *self.bootstrap_config.logging_extra_processors,
                    structlog.processors.JSONRenderer(serializer=_serialize_log_with_orjson_to_string),
                ],
                logger=root_logger,
            )
        )
        root_logger.addHandler(stream_handler)
        root_logger.setLevel(self.bootstrap_config.logging_log_level)

    def bootstrap(self) -> None:
        self._unset_handlers()
        self._configure_structlog_loggers()
        self._configure_foreign_loggers()

    def teardown(self) -> None:
        """Reset structlog and root logger. Root logger level is unconditionally set to WARNING; pre-existing user configuration is overwritten."""
        structlog.reset_defaults()
        root_logger = logging.getLogger()
        for h in root_logger.handlers[:]:
            root_logger.removeHandler(h)
            h.close()
        root_logger.setLevel(logging.WARNING)
        if self._logger_factory is not None:
            try:
                self._logger_factory.close_handlers()
            finally:
                object.__setattr__(self, "_logger_factory", None)
```

Key differences from the original:
- Module-top imports from `logging_factory`: `AddressProtocol`, `RequestProtocol`, `ScopeType`, `_MemoryLoggerFactoryConfig`, `_serialize_log_with_orjson_to_string` (all unconditional, no structlog dependency).
- `MemoryLoggerFactory` import is gated — at module top in `TYPE_CHECKING` block (for annotations) and inside `if import_checker.is_structlog_installed:` (for runtime use). This mirrors the original module's lazy-resolution pattern: `MemoryLoggerFactory` is only referenced at runtime when structlog is installed.
- `__all__` explicitly re-exports the moved public symbols (`AddressProtocol`, `MemoryLoggerFactory`, `RequestProtocol`, `ScopeType`) for backward compatibility. Consumers who try to access `MemoryLoggerFactory` without structlog will get `AttributeError` — same behavior as the original module.
- `_unset_handlers` and `teardown` now have one-line docstrings (LOW-8, LOW-9).
- `memory_logger_factory` property constructs `MemoryLoggerFactory` with a `_MemoryLoggerFactoryConfig` (LOW-6).
- All `MemoryLoggerFactory`/factory-internal code is gone — sourced from the new module.

### Step 3: Verify the split with a quick smoke test

```bash
just test -- tests/instruments/test_logging_instrument.py -v
```

Expected: existing tests may fail because they construct `MemoryLoggerFactory(logging_buffer_capacity=..., ...)` with the old signature. We'll fix those in Step 6 below. For now, just verify that imports resolve cleanly (no `ImportError`).

If you see `ImportError`, the file split is broken — investigate before proceeding.

### Step 4: REF-2 — delete dead defensive check in `LitestarLoggingInstrument.bootstrap`

**File:** `lite_bootstrap/bootstrappers/litestar_bootstrapper.py`

Locate `LitestarLoggingInstrument.bootstrap`. Current:

```python
    def bootstrap(self) -> None:
        self._unset_handlers()
        if import_checker.is_structlog_installed and import_checker.is_litestar_installed:
            self.bootstrap_config.application_config.plugins.append(
                StructlogPlugin(
                    config=StructlogConfig(
                        structlog_logging_config=StructLoggingConfig(
                            processors=self.structlog_processors,
                            logger_factory=self.memory_logger_factory,
                            wrapper_class=structlog.stdlib.BoundLogger,
                            cache_logger_on_first_use=True,
                            pretty_print_tty=False,
                            standard_lib_logging_config=None,
                        ),
                    ),
                )
            )
            self._configure_foreign_loggers()
```

Replace with (delete the `if` line and the matching dedent — the body unindents one level):

```python
    def bootstrap(self) -> None:
        self._unset_handlers()
        self.bootstrap_config.application_config.plugins.append(
            StructlogPlugin(
                config=StructlogConfig(
                    structlog_logging_config=StructLoggingConfig(
                        processors=self.structlog_processors,
                        logger_factory=self.memory_logger_factory,
                        wrapper_class=structlog.stdlib.BoundLogger,
                        cache_logger_on_first_use=True,
                        pretty_print_tty=False,
                        standard_lib_logging_config=None,
                    ),
                ),
            )
        )
        self._configure_foreign_loggers()
```

The `if import_checker.is_structlog_installed and import_checker.is_litestar_installed:` check is dead — the instrument couldn't have been registered without both packages installed.

### Step 5: Update tests to use `_MemoryLoggerFactoryConfig`

**File:** `tests/instruments/test_logging_instrument.py`

There are two tests (`test_memory_logger_factory_info`, `test_memory_logger_factory_error`) that instantiate `MemoryLoggerFactory` directly. Both need to be updated to use the new config-based API.

Locate the top-of-file imports. The current imports look like:

```python
import logging
from io import StringIO

import structlog
from opentelemetry.trace import get_tracer

from lite_bootstrap.instruments.logging_instrument import LoggingConfig, LoggingInstrument, MemoryLoggerFactory
from lite_bootstrap.instruments.opentelemetry_instrument import OpentelemetryConfig, OpenTelemetryInstrument
from tests.conftest import LoggingMock
```

(After PR3 the file also has `from unittest.mock import patch` and `import pytest`; preserve those.)

Add `_MemoryLoggerFactoryConfig` to the imports. Either import from `logging_factory` directly (more explicit) or from `logging_instrument` (which already re-imports it). Use the direct path for clarity:

```python
from lite_bootstrap.instruments.logging_factory import _MemoryLoggerFactoryConfig
```

Place this after the `from lite_bootstrap.instruments.logging_instrument import ...` line.

Locate `test_memory_logger_factory_info`. Current:

```python
def test_memory_logger_factory_info() -> None:
    test_capacity = 10
    test_flush_level = logging.ERROR
    test_stream = StringIO()

    logger_factory = MemoryLoggerFactory(
        logging_buffer_capacity=test_capacity,
        logging_flush_level=test_flush_level,
        logging_log_level=logging.INFO,
        log_stream=test_stream,
    )
    ...
```

Replace the `MemoryLoggerFactory(...)` call with:

```python
    logger_factory = MemoryLoggerFactory(
        config=_MemoryLoggerFactoryConfig(
            logging_buffer_capacity=test_capacity,
            logging_flush_level=test_flush_level,
            logging_log_level=logging.INFO,
            log_stream=test_stream,
        ),
    )
```

Do the same in `test_memory_logger_factory_error`.

### Step 6: Add lifecycle replay test (TEST-8)

In the same file, append a new test:

```python
def test_logging_instrument_lifecycle_replay(logging_mock: LoggingMock) -> None:
    instrument = LoggingInstrument(
        bootstrap_config=LoggingConfig(
            logging_buffer_capacity=0,
            logging_extra_processors=[logging_mock],
        ),
    )
    try:
        instrument.bootstrap()
        instrument.teardown()
        instrument.bootstrap()
        logger = structlog.getLogger(__name__)
        logger.info("after replay")
        assert any(e.get("event") == "after replay" for e in logging_mock.entries)
    finally:
        instrument.teardown()
```

Contract: bootstrap → teardown → bootstrap must succeed without raising. After the second bootstrap, the instrument is functional (new logger entries flow through `logging_mock`). The final `teardown()` in `finally` ensures global state is cleaned up regardless of test outcome.

### Step 7: Run the full logging test file

```bash
just test -- tests/instruments/test_logging_instrument.py -v
```

Expected: all tests PASS, including the two updated factory tests and the new lifecycle replay test.

If any test fails, investigate. The most likely cause is a typo in the `_MemoryLoggerFactoryConfig` construction.

### Step 8: Run the full test suite

```bash
just test
```

Expected: 127/127 PASS (after PR10 brought the total to 127, this PR adds 1 test → 128). Watch for failures in the framework integration tests — particularly `test_fastapi_bootstrap`, `test_litestar_bootstrap`, `test_faststream_bootstrap` — which exercise the full logging instrument lifecycle.

### Step 9: Run lint

```bash
just lint
```

Expected: clean. The file split and dataclass-config refactor shouldn't introduce lint issues.

**Important — PLR2004 policy:** If ruff flags any numeric literal in test assertions with PLR2004 (magic value), DO NOT add `# noqa: PLR2004`. Extract the value to a named local variable. Example: `expected_capacity = 10; assert factory.config.logging_buffer_capacity == expected_capacity`.

### Step 10: Commit

Stage all five touched files:

```bash
git add \
  lite_bootstrap/instruments/logging_factory.py \
  lite_bootstrap/instruments/logging_instrument.py \
  lite_bootstrap/bootstrappers/litestar_bootstrapper.py \
  tests/instruments/test_logging_instrument.py
git commit -m "$(cat <<'EOF'
refactor: split logging module + cleanup + lifecycle test

REF-4: Split lite_bootstrap/instruments/logging_instrument.py (212
lines, four concerns) into:
- logging_factory.py: MemoryLoggerFactory, _MemoryLoggerFactoryConfig,
  _serialize_log_with_orjson_to_string, AddressProtocol,
  RequestProtocol, ScopeType. Single structlog-conditional gate at
  module top.
- logging_instrument.py: LoggingConfig, LoggingInstrument,
  tracer_injection. Re-imports the moved public symbols
  (MemoryLoggerFactory, AddressProtocol, RequestProtocol, ScopeType)
  for backward compatibility — existing imports from
  lite_bootstrap.instruments.logging_instrument continue to work.

LOW-6: MemoryLoggerFactory.__init__ now takes a single
_MemoryLoggerFactoryConfig dataclass instead of four logging-config
kwargs. The dataclass is underscore-prefixed (internal); tests import
it explicitly when constructing the factory directly.

REF-2: Delete the dead `if import_checker.is_structlog_installed and
import_checker.is_litestar_installed:` defensive check in
LitestarLoggingInstrument.bootstrap. The check is unreachable —
the instrument couldn't have been registered without both packages
installed.

LOW-8: Add a docstring to LoggingInstrument._unset_handlers documenting
that the mutation is permanent (teardown does not restore handlers).

LOW-9: Add a docstring to LoggingInstrument.teardown documenting that
root logger level is unconditionally reset to WARNING.

TEST-8: Add test_logging_instrument_lifecycle_replay exercising
bootstrap → teardown → bootstrap → teardown and verifying the
instrument is functional after the second bootstrap.

No external behavior change. Updated factory tests to use the new
config-based constructor.

Closes REF-2, REF-4, LOW-6, LOW-8, LOW-9, TEST-8 from the audit.
EOF
)"
```

---

## Task 3: Push and open PR

- [ ] **Step 1: Push the branch**

```bash
git push -u origin refactor/ref-4-logging-cleanup
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --title "refactor: split logging module + cleanup + lifecycle test" --body "$(cat <<'EOF'
## Summary
The biggest PR of the deferred-refactors sequence — six logging-area items bundled:

- **REF-4:** Split `logging_instrument.py` (212 lines, four concerns) into a new `logging_factory.py` (MemoryLoggerFactory + serializer + protocols + the new internal `_MemoryLoggerFactoryConfig`) and a slimmer `logging_instrument.py` (config + instrument + tracer injection). Single structlog-conditional gate at the new module's top, vs three separate gates in the old layout. Backward compatibility: the moved public symbols are re-imported into `logging_instrument.py`, so existing `from lite_bootstrap.instruments.logging_instrument import MemoryLoggerFactory` continues to work.
- **REF-2:** Deleted the dead `if import_checker.is_structlog_installed and import_checker.is_litestar_installed:` check in `LitestarLoggingInstrument.bootstrap()`. Unreachable code (the instrument couldn't have been registered without both packages installed).
- **LOW-6:** `MemoryLoggerFactory.__init__` now takes a single `_MemoryLoggerFactoryConfig` dataclass instead of four logging-config kwargs. Underscore-prefixed because it's internal; tests import it directly.
- **LOW-8:** Added a docstring to `LoggingInstrument._unset_handlers` documenting that the mutation is permanent — teardown does NOT restore handlers.
- **LOW-9:** Added a docstring to `LoggingInstrument.teardown()` documenting that root logger level is unconditionally reset to `WARNING`.
- **TEST-8:** New `test_logging_instrument_lifecycle_replay` exercises bootstrap → teardown → bootstrap → teardown and verifies the instrument is functional after the second bootstrap.

No external behavior change. Two existing factory tests updated to use the new config-based constructor.

Closes REF-2, REF-4, LOW-6, LOW-8, LOW-9, TEST-8 from an internal audit.

## Test plan
- [x] `just test -- tests/instruments/test_logging_instrument.py -v` — pass (including updated factory tests + new lifecycle replay).
- [x] `just test` — 128/128 (127 prior + 1 new).
- [x] `just lint` — clean.
- [ ] Reviewer: confirm the backward-compat re-imports in `logging_instrument.py` cover all the public symbols (MemoryLoggerFactory, AddressProtocol, RequestProtocol, ScopeType).
- [ ] Reviewer: confirm the test update for the new config-based `MemoryLoggerFactory` constructor is correct.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review

**Spec coverage check** against the sequencing spec (PR11 section) and audit:

| Spec item | Task |
|-----------|------|
| REF-4: Split `logging_instrument.py` into `logging_factory.py` + slimmer `logging_instrument.py` | Task 2, Steps 1-2 |
| REF-2: Delete dead defensive check in `LitestarLoggingInstrument.bootstrap` | Task 2, Step 4 |
| LOW-6: `MemoryLoggerFactory` takes `_MemoryLoggerFactoryConfig` | Task 2, Steps 1, 2, 5 |
| LOW-8: docstring on `_unset_handlers` | Task 2, Step 2 |
| LOW-9: docstring on `teardown` | Task 2, Step 2 |
| TEST-8: lifecycle replay test | Task 2, Step 6 |
| Branch name `refactor/ref-4-logging-cleanup` | Task 1, Step 1 |
| Verification: `just test` + `just lint` clean | Task 2, Steps 8-9 |
| PLR2004 noqa NOT used; extract constants instead | Task 2, Step 9 (callout) |

All spec items covered. No placeholders. Backward compatibility for moved public symbols is explicitly handled via re-imports in `logging_instrument.py` with `__all__` listing them.

**Risk notes:**
- The file split is the highest-risk change. If imports break anywhere in the codebase or tests, this PR's full suite run catches it.
- The MemoryLoggerFactory constructor change is API-breaking for direct users of `MemoryLoggerFactory(logging_buffer_capacity=..., ...)`. Since `MemoryLoggerFactory` is publicly exported but its internals are framework-level (users rarely construct it directly outside tests), the impact is small. Documented in the commit message.
