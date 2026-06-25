---
summary: Stdlib `logging` in `bootstrappers/base.py` + public `build_summary()`.
---
# Design: Stdlib Logging in `bootstrappers/base.py` + Public `build_summary()` Method

**Date:** 2026-06-02
**Status:** Approved (design complete; implementation pending)
**Supersedes:** the `_get_logger()` fresh-per-call decision from `2026-06-01-instrument-skip-rework-design.md` (and the implementation plan at `docs/superpowers/plans/2026-06-01-instrument-skip-rework.md`). Everything else in those documents stands.

## Problem

PR #107 ("refactor: replace `InstrumentNotReadyWarning` with `is_configured` classmethod + summary log") introduces a `_get_logger()` helper in `lite_bootstrap/bootstrappers/base.py`:

```python
try:
    import structlog

    def _get_logger() -> typing.Any:  # noqa: ANN401
        """Get a fresh structlog proxy each call.

        We deliberately avoid a module-level cached logger because structlog's
        `cache_logger_on_first_use=True` (set by LoggingInstrument.bootstrap) memoizes the
        BoundLogger and its processor chain on first use — making it impossible for
        `structlog.testing.capture_logs()` to override the binding after the cache is set.
        Returning a fresh proxy per call keeps the structlog pipeline reactive to config changes.
        """
        return structlog.get_logger(__name__)

except ImportError:
    def _get_logger() -> typing.Any:  # noqa: ANN401
        return logging.getLogger(__name__)
```

Called at two log sites: the INFO summary at end of `__init__`, and the WARNING per-instrument teardown error.

Code review identified this as hacky:

1. **Production shaped by test mechanics.** The docstring justifies the design entirely by the need for `structlog.testing.capture_logs()` to work in the test suite.
2. **Defeats `cache_logger_on_first_use=True`.** A fresh `BoundLoggerLazyProxy` per call rebinds the processor chain every log line — the exact cost the cache flag exists to avoid.
3. **Does not address the root cause.** The actual problem is that `LoggingInstrument.bootstrap()` mutates global structlog state via `structlog.configure(cache_logger_on_first_use=True, ...)`. Any module-level `logger = structlog.get_logger(__name__)` anywhere in the codebase — or in user code — has the same fragility. This patch fixes two call sites; the next file added has the same trap.
4. **The test-driven case is weak.** The summary log fires inside `__init__`, **before** `LoggingInstrument.bootstrap()` runs. The cache flag isn't even set yet by this library at that moment. The problem only manifests when a previous test in the same session left structlog with `cache_logger_on_first_use=True` and a cached proxy from when the module was first imported.
5. **The type system is being silenced twice.** Two function bodies with the same name, both `typing.Any`, both `# noqa: ANN401`.

A separate gap from review: nothing in the codebase lets a user inspect "what did the bootstrapper decide" in a human-readable form after construction. `bootstrapper.instruments` and `bootstrapper.skipped_instruments` are structured but verbose to read; the INFO summary log is a string but only emitted once into the logging pipeline.

## Goal

Replace the structlog-aware `_get_logger()` indirection with a plain module-level stdlib logger, and introduce a public `build_summary()` method on `BaseBootstrapper` that returns the human-readable, multi-line summary used by the INFO log. The same method is callable post-construction for debugging.

Non-goals:
- Changing `LoggingInstrument`'s structlog configuration behavior (separate concern).
- Adding a pytest `structlog.reset_defaults()` fixture (not needed once the bootstrapper stops using structlog).
- Touching log sites outside `bootstrappers/base.py`.

## Design

### Module-level stdlib logger

`lite_bootstrap/bootstrappers/base.py`:

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

The `try: import structlog / def _get_logger(): ... / except ImportError: def _get_logger(): ...` block is deleted in full.

**Why stdlib here:** the bootstrapper's two log sites describe its own lifecycle — instrument selection during `__init__`, teardown errors during shutdown. The summary log fires before `LoggingInstrument.bootstrap()` runs, so it predates any structlog configuration in the same process. Neither call benefits from structured-event routing (the consumers of these logs are humans reading stderr or test assertions). Using stdlib logging:
- Removes the global-structlog-state landmine.
- Integrates with pytest's `caplog` fixture instead of `structlog.testing.capture_logs()`.
- Composes with the user's existing `logging.basicConfig()` / dictConfig setup.
- Lets `LoggingInstrument` keep `cache_logger_on_first_use=True` without polluting bootstrapper log emission.

### `build_summary()` method on `BaseBootstrapper`

```python
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
```

Example output for `FreeBootstrapper(FreeConfig(sentry_dsn=..., logging_enabled=False))`:

```
FreeBootstrapper:
  configured:
    - SentryInstrument
  skipped:
    - LoggingInstrument: logging_enabled is False
    - PyroscopeInstrument: pyroscope_endpoint is empty
```

Format rules:
- First line: `BootstrapperClassName:` (the concrete subclass, via `type(self).__name__`).
- Two sections always rendered: `configured:` and `skipped:`. Predictable structure for users grepping log output or asserting on the format in tests.
- Each section: indented `- <ClassName>` per instrument; for skipped, append `: <reason>`.
- Empty section renders as `(none)`.

The method depends only on `self.instruments` and `self.skipped_instruments`, both populated by `__init__` before the call site. Calling it post-construction reflects the current value of `self.instruments` (which user code may mutate, e.g. the test suite swaps in `MagicMock` instances in teardown tests) — this is acceptable; the docstring will not promise immutability.

### `__init__` call site

End of the loop in `BaseBootstrapper.__init__`:

```python
        logger.info(self.build_summary())
```

Replaces the inline f-string + `_get_logger().info(...)`. No behavior change beyond format (multi-line vs single-line).

### Teardown error log

```python
        except Exception as e:  # noqa: BLE001, PERF203
            name = type(one_instrument).__name__
            logger.warning("Error tearing down %s: %s", name, e)
            errors.append((name, e))
```

Replaces `_get_logger().warning(f"Error tearing down {name}: {e}")`. Uses stdlib `%`-style lazy formatting — idiomatic and skips formatting work if the log level is filtered.

## Test changes

`tests/test_free_bootstrap.py` has two `capture_logs()` sites that migrate to `caplog`:

### `test_teardown_error_isolation`

```python
def test_teardown_error_isolation(
    free_bootstrapper_config: FreeConfig, caplog: pytest.LogCaptureFixture
) -> None:
    bootstrapper = FreeBootstrapper(bootstrap_config=free_bootstrapper_config)
    bootstrapper.bootstrap()

    bad = MagicMock()
    bad.teardown.side_effect = RuntimeError("boom")
    good = MagicMock()
    bootstrapper.instruments = [bad, good]

    with (
        caplog.at_level(logging.WARNING, logger="lite_bootstrap.bootstrappers.base"),
        pytest.raises(TeardownError, match="boom") as excinfo,
    ):
        bootstrapper.teardown()

    good.teardown.assert_called_once()
    bad.teardown.assert_called_once()
    assert any("boom" in r.message for r in caplog.records)
    assert excinfo.value.errors == [("MagicMock", excinfo.value.__cause__)]
```

### `test_free_bootstrap_emits_summary_log`

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

### New: silent-skip negative test

Closes the gap from the code review: lock in that config-driven skip emits **no** warning.

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

### New: `build_summary()` unit test

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

### Imports cleanup

In `tests/test_free_bootstrap.py`:
- Drop `from structlog.testing import capture_logs` (no longer used).
- Add `import logging` and `import warnings`.
- Keep `import structlog` and `logger = structlog.getLogger(__name__)` — used by `test_free_bootstrap` to emit an application-level log line through the configured `LoggingInstrument` (legitimate structlog usage; that test exercises the configured pipeline end-to-end).

## Documentation

### `CLAUDE.md`

The PR added a sentence about `_get_logger()` to the "Instrument skip ordering" bullet. Replace it:

Old:
> The bootstrappers/base.py logger is obtained fresh per call (`_get_logger()`) instead of cached at module level, so `structlog.testing.capture_logs()` can override processors at test time even after `LoggingInstrument.bootstrap()` sets `cache_logger_on_first_use=True`.

New:
> One `logger.info` summary line at the end lists configured + skipped instruments via `BaseBootstrapper.build_summary()`; that method is also publicly callable for post-construction debugging. Uses stdlib `logging` so it composes cleanly with the user's logging setup and with pytest's `caplog`.

### `docs/introduction/configuration.md`

The section the PR rewrote already mentions the summary log and `skipped_instruments`. Append one paragraph after the existing `skipped_instruments` introspection example:

> To get a human-readable view of the same information at any later point (e.g. for debugging from a REPL or a health endpoint), call `bootstrapper.build_summary()`. It returns the multi-line string that the INFO summary log emits — useful when log levels are filtered or when you want to render the bootstrapper state inline.

### `docs/superpowers/plans/2026-06-01-instrument-skip-rework.md`

The committed implementation plan documents `_get_logger()` as part of its steps. Do not retroactively edit the plan body. Add a one-line note at the top:

> **Note (2026-06-02):** the `_get_logger()` fresh-per-call decision documented below was revised by `docs/superpowers/specs/2026-06-02-stdlib-logging-and-build-summary-design.md`. The summary-log goal is unchanged; the implementation switched to stdlib `logging` with a public `build_summary()` method.

## Files touched

| File | Change |
|------|--------|
| `lite_bootstrap/bootstrappers/base.py` | Delete `_get_logger()` block. Add module-level `logger = logging.getLogger(__name__)`. Add `build_summary()` method. Replace `_get_logger().info(...)` and `_get_logger().warning(...)` calls. Teardown warning uses lazy `%`-formatting. |
| `tests/test_free_bootstrap.py` | Migrate two `capture_logs()` sites to `caplog`. Add `test_config_skip_emits_no_warning`. Add `test_build_summary_format`. Drop `capture_logs` import; add `logging` and `warnings`. |
| `CLAUDE.md` | Replace the `_get_logger()` sentence with the `build_summary()` description. |
| `docs/introduction/configuration.md` | Append one paragraph documenting `build_summary()`. |
| `docs/superpowers/plans/2026-06-01-instrument-skip-rework.md` | Add a one-line supersession note at the top. |

No changes to any instrument module, exception class, or other bootstrapper.

## Backwards compatibility

This refactor lands on the same feature branch as PR #107, before merge. The `_get_logger()` helper was introduced by PR #107 and has never appeared in `main`. No public API of `lite-bootstrap` changes incompatibly.

The new `build_summary()` is purely additive on `BaseBootstrapper`.

## Risks

- **`caplog` propagation.** `caplog` captures records that propagate to the root handler. The new tests use `caplog.at_level(logging.INFO, logger="lite_bootstrap.bootstrappers.base")` which both sets the level and registers the handler for that logger — standard pytest pattern, should work without further setup. If propagation is blocked by a user's `conftest.py` `disable_existing_loggers`, the tests will fail with an empty record list; resolution is local to test setup.
- **Default Python logging behavior.** Without `logging.basicConfig()`, stdlib's "last resort" handler emits WARNING+ to stderr and silently drops INFO. So the summary log is invisible by default — same observable behavior as the PR currently delivers via structlog when no structlog config is set. Acceptable; users who want to see it call `logging.basicConfig(level=logging.INFO)`.

## Success criteria

- `just test` passes 150/150 (plus the two new tests = 152/152).
- `just lint` clean (ruff + ty).
- `grep -rn "_get_logger" lite_bootstrap/ tests/` returns no matches.
- `grep -rn "capture_logs" tests/test_free_bootstrap.py` returns no matches.
- `grep -rn "build_summary" lite_bootstrap/ tests/` returns the new method definition, the call site in `__init__`, the unit test, and the docs reference.
