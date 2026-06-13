# PR2: OpenTelemetry Tracer Provider Shutdown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `OpenTelemetryInstrument.teardown()` shut down the `TracerProvider` that `bootstrap()` created. Today the provider goes out of scope and any spans buffered in `BatchSpanProcessor` are not flushed — trace data loss on graceful shutdown. Add a regression test that fails on `main` and passes after the fix.

**Architecture:** `OpenTelemetryInstrument` is a frozen, slots-enabled dataclass. The existing codebase pattern for stashing mutable runtime state on a frozen dataclass uses an init-false private field plus `object.__setattr__` (see `LoggingInstrument._logger_factory`). Mirror that: add `_tracer_provider`, store the provider via `object.__setattr__` at the end of `bootstrap()`, call `self._tracer_provider.shutdown()` after the existing `uninstrument()` loop in `teardown()`, reset to `None`.

**Tech Stack:** Python 3.10+, OpenTelemetry SDK (`opentelemetry-sdk`, `opentelemetry-api`), pytest, `unittest.mock.patch.object`.

**Parent spec:** `docs/superpowers/specs/2026-05-31-audit-implementation-sequencing.md` (PR2 section).
**Parent audit:** `docs/superpowers/specs/2026-05-31-bug-refactor-audit.md` (CRIT-2, TEST-2).

---

## File Structure

Two existing files modified. No new files.

- Modify: `lite_bootstrap/instruments/opentelemetry_instrument.py:76-135` — add `_tracer_provider` field on the dataclass, store the provider in `bootstrap()`, shut it down in `teardown()`.
- Modify: `tests/instruments/test_opentelemetry_instrument.py` — add a new test asserting `shutdown` is invoked.

---

## Locked decisions (from sequencing spec)

- **Storage pattern:** `object.__setattr__` (preserves `frozen=True`; matches `LoggingInstrument._logger_factory`).
- **Field name:** `_tracer_provider` (underscore = internal state, mirrors `_logger_factory`).
- **Test access:** read the private `_tracer_provider` attribute directly with `# noqa: SLF001`. Other tests in the file already use patch-based introspection (`patch("lite_bootstrap.instruments.opentelemetry_instrument.set_tracer_provider")`), so private-attribute access for verification is consistent with the existing test style.

---

## Task 1: Create branch

**Files:** (no files; git only)

- [ ] **Step 1: Branch off `main`**

```bash
git checkout main
git pull --ff-only origin main
git checkout -b fix/crit-2-otel-shutdown
```

Expected: `Switched to a new branch 'fix/crit-2-otel-shutdown'`.

If PR1 (`fix/crit-1-redoc-root-path`) has not yet merged into `main`, that's fine — PR2's changes touch a different file and there will be no conflict. Branch from current `main` regardless.

---

## Task 2: Add the failing regression test

**Files:**
- Modify: `tests/instruments/test_opentelemetry_instrument.py`

The current test file has two tests that bootstrap + teardown but assert nothing about shutdown behavior. Add a third test that bootstraps the instrument, captures the stored `TracerProvider`, patches its `shutdown` method, runs teardown, and asserts the patch was invoked exactly once.

- [ ] **Step 1: Add imports and the new test**

The existing imports are:

```python
from lite_bootstrap.instruments.opentelemetry_instrument import (
    InstrumentorWithParams,
    OpentelemetryConfig,
    OpenTelemetryInstrument,
)
from tests.conftest import CustomInstrumentor
```

Add `from unittest.mock import patch` at the top (after any stdlib imports, before the project imports — ruff isort will handle ordering on save, but write it correctly the first time):

```python
from unittest.mock import patch

from lite_bootstrap.instruments.opentelemetry_instrument import (
    InstrumentorWithParams,
    OpentelemetryConfig,
    OpenTelemetryInstrument,
)
from tests.conftest import CustomInstrumentor
```

Append this new test to the end of the file (after `test_opentelemetry_instrument_empty_instruments`):

```python
def test_opentelemetry_instrument_teardown_shuts_down_tracer_provider() -> None:
    instrument = OpenTelemetryInstrument(
        bootstrap_config=OpentelemetryConfig(opentelemetry_log_traces=True),
    )
    instrument.bootstrap()
    tracer_provider = instrument._tracer_provider  # noqa: SLF001
    assert tracer_provider is not None

    with patch.object(tracer_provider, "shutdown") as mock_shutdown:
        instrument.teardown()

    mock_shutdown.assert_called_once_with()
    assert instrument._tracer_provider is None  # noqa: SLF001
```

This test asserts three things:
1. The instrument exposes its tracer provider as `_tracer_provider` after bootstrap.
2. Teardown calls `shutdown()` on that provider exactly once.
3. Teardown resets `_tracer_provider` to `None` so a subsequent bootstrap starts clean.

- [ ] **Step 2: Run the new test and verify it FAILS**

```bash
just test -- tests/instruments/test_opentelemetry_instrument.py::test_opentelemetry_instrument_teardown_shuts_down_tracer_provider -v
```

Expected: **FAIL** with `AttributeError: 'OpenTelemetryInstrument' object has no attribute '_tracer_provider'` (or similar — the attribute doesn't exist yet on the dataclass).

If the test passes, stop and investigate — either the attribute already exists (which would mean someone else implemented the fix already) or the assertion is wrong.

---

## Task 3: Implement the shutdown fix

**Files:**
- Modify: `lite_bootstrap/instruments/opentelemetry_instrument.py`

The current `OpenTelemetryInstrument` dataclass (lines 76-80) has no init-false field for the provider. Add one. Then update `bootstrap()` to stash the locally-created provider on the instance, and update `teardown()` to shut it down and clear the field.

- [ ] **Step 1: Add `_tracer_provider` field to the dataclass**

Current dataclass body (lines 76-80):

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class OpenTelemetryInstrument(BaseInstrument):
    bootstrap_config: OpentelemetryConfig
    not_ready_message = "opentelemetry_endpoint is empty and opentelemetry_log_traces is False"
    missing_dependency_message = "opentelemetry is not installed"
```

Replace with:

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class OpenTelemetryInstrument(BaseInstrument):
    bootstrap_config: OpentelemetryConfig
    not_ready_message = "opentelemetry_endpoint is empty and opentelemetry_log_traces is False"
    missing_dependency_message = "opentelemetry is not installed"
    _tracer_provider: "TracerProvider | None" = dataclasses.field(
        default_factory=lambda: None, init=False, repr=False, compare=False
    )
```

Notes:
- The string annotation `"TracerProvider | None"` is a forward reference. `TracerProvider` is imported conditionally inside `if import_checker.is_opentelemetry_installed:` at module top (line 17), so the string form avoids NameError if opentelemetry isn't installed.
- `default_factory=lambda: None` matches the `LoggingInstrument._logger_factory` precedent. Do not use `default=None` — the existing codebase normalized on `default_factory=lambda: None` for these fields (see commit `8db9be3`).
- `init=False, repr=False, compare=False` matches the precedent: this is internal runtime state, not part of the instrument's identity.

- [ ] **Step 2: Stash the provider in `bootstrap()`**

Current `bootstrap()` ends at line 128 with the instrumentor loop. Just before that loop, after `set_tracer_provider(tracer_provider)` (line 107) and the span-processor setup (lines 108-120), add the stash. The simplest placement: right after `set_tracer_provider(tracer_provider)`.

Current code around line 106-107:

```python
        tracer_provider = TracerProvider(resource=resource)
        set_tracer_provider(tracer_provider)
```

Replace with:

```python
        tracer_provider = TracerProvider(resource=resource)
        set_tracer_provider(tracer_provider)
        object.__setattr__(self, "_tracer_provider", tracer_provider)
```

This makes the locally-constructed provider reachable from `teardown()`.

- [ ] **Step 3: Shut down the provider in `teardown()`**

Current `teardown()` (lines 130-135):

```python
    def teardown(self) -> None:
        for one_instrumentor in self.bootstrap_config.opentelemetry_instrumentors:
            if isinstance(one_instrumentor, InstrumentorWithParams):
                one_instrumentor.instrumentor.uninstrument(**one_instrumentor.additional_params)
            else:
                one_instrumentor.uninstrument()
```

Replace with:

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

Order matters: uninstrument first (so instrumentors release any references to the provider), then shutdown (so the provider flushes buffered spans and disposes of processors).

- [ ] **Step 4: Run the previously-failing test and verify it PASSES**

```bash
just test -- tests/instruments/test_opentelemetry_instrument.py::test_opentelemetry_instrument_teardown_shuts_down_tracer_provider -v
```

Expected: **PASS**.

- [ ] **Step 5: Run the full OTel test file**

```bash
just test -- tests/instruments/test_opentelemetry_instrument.py -v
```

Expected: all three tests PASS — the two existing tests should be unaffected by the change.

- [ ] **Step 6: Run the full test suite**

```bash
just test
```

Expected: all tests PASS. The change touches a hot code path used by every framework bootstrapper's OTel integration (FastAPI, Litestar, FastStream, Free) — the bootstrapper-level tests will all exercise the new shutdown call. Watch for any unexpected failures in `test_fastapi_bootstrap.py`, `test_litestar_bootstrap.py`, `test_faststream_bootstrap.py`, `test_free_bootstrap.py`.

If any pre-existing test fails because of double-shutdown (a teardown getting called twice somewhere — Litestar registers `self.teardown` on `on_shutdown`), that's CRIT-3 territory and will be handled in PR3. Note the failure in your report but do not attempt to fix CRIT-3 in this PR. If you see a `RuntimeError: TracerProvider has already been shut down` (or similar) in a test that wasn't failing before, that's the signal — flag it and continue.

- [ ] **Step 7: Run lint**

```bash
just lint
```

Expected: no errors. The `# noqa: SLF001` in the test handles private-member-access; everything else follows existing patterns.

- [ ] **Step 8: Commit**

Stage both modified files explicitly:

```bash
git add lite_bootstrap/instruments/opentelemetry_instrument.py tests/instruments/test_opentelemetry_instrument.py
git commit -m "$(cat <<'EOF'
fix: shut down TracerProvider in OpenTelemetryInstrument.teardown

The instrument's bootstrap() created a TracerProvider, registered span
processors against it, and called set_tracer_provider — but never stored
a reference. teardown() only uninstrumented the instrumentors; the
provider was never shut down. Spans buffered in BatchSpanProcessor were
lost on graceful shutdown.

Stash the provider on the instrument via object.__setattr__ (mirroring
the LoggingInstrument._logger_factory pattern for runtime state on a
frozen dataclass), shut it down after the uninstrument loop, reset the
field to None so a subsequent bootstrap starts clean.

Regression test asserts shutdown is called exactly once on the stored
provider and the field is reset.

Closes CRIT-2, TEST-2 from the audit.
EOF
)"
```

Expected: commit succeeds.

---

## Task 4: Push and open PR

**Files:** (no files; git push + gh)

- [ ] **Step 1: Push the branch**

```bash
git push -u origin fix/crit-2-otel-shutdown
```

Expected: branch published.

- [ ] **Step 2: Open the PR**

```bash
gh pr create --title "fix: shut down TracerProvider in OpenTelemetryInstrument.teardown" --body "$(cat <<'EOF'
## Summary
- `OpenTelemetryInstrument.bootstrap()` now stashes the `TracerProvider` it created on the instance (via `object.__setattr__`, matching `LoggingInstrument._logger_factory`).
- `teardown()` calls `self._tracer_provider.shutdown()` after the existing instrumentor uninstrument loop, then resets the field to `None`. Buffered spans in `BatchSpanProcessor` are now flushed on graceful shutdown.
- New regression test `test_opentelemetry_instrument_teardown_shuts_down_tracer_provider` patches `shutdown` on the stored provider and asserts it's invoked exactly once. Test fails on `main`, passes on this branch.

Closes CRIT-2 and TEST-2 from an internal audit of the codebase.

## Test plan
- [x] `just test -- tests/instruments/test_opentelemetry_instrument.py -v` — three tests pass.
- [x] `just test` — full suite passes.
- [x] `just lint` — clean.
- [ ] Reviewer: confirm the field placement and `object.__setattr__` usage match the `LoggingInstrument._logger_factory` precedent.
EOF
)"
```

Expected: PR created; URL printed.

---

## Self-Review

**Spec coverage check** against the sequencing spec (PR2 section) and audit (CRIT-2, TEST-2):

| Spec item | Task |
|-----------|------|
| Store `TracerProvider` on instance via `object.__setattr__` | Task 3, Step 2 |
| Declare `_tracer_provider: "TracerProvider \| None"` init-false field | Task 3, Step 1 |
| Call `shutdown()` in `teardown()` after `uninstrument()` loop | Task 3, Step 3 |
| Reset field to `None` after shutdown | Task 3, Step 3 |
| Add test asserting `shutdown` is invoked | Task 2, Step 1 |
| Test uses `patch.object` (mock approach, not real BatchSpanProcessor) | Task 2, Step 1 |
| Branch name `fix/crit-2-otel-shutdown` | Task 1, Step 1 |
| Verification: `just test` + `just lint` pass | Task 3, Steps 6-7 |

All spec items covered. No placeholders. Field-name (`_tracer_provider`) and assertion-text consistency holds across Task 2 (test expectations) and Task 3 (implementation).

**Cross-PR awareness:** Task 3 Step 6 notes that pre-existing tests could surface CRIT-3 (double-teardown) once the shutdown call exists. That failure mode is explicitly out of scope for this PR — flag and continue, do not attempt to fix it here.
