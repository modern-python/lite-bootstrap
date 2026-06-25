# 31.01-audit-implementation — implementation plan

> Multi-PR plan: this change shipped as a sequence of PRs. Each section below was an independent per-PR plan; they are preserved verbatim here as the bundle's single `plan.md` (the spec is [`design.md`](./design.md)).


---

# PR1: Redoc `root_path` Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the offline-docs `redoc_html` handler honor `root_path`, so redoc loads its JS and OpenAPI spec correctly when the FastAPI app is mounted behind a reverse proxy. Add a regression test that fails on `main` and passes after the fix.

**Architecture:** The `enable_offline_docs` helper installs three handlers — one for swagger, one for swagger oauth2 redirect, one for redoc. The swagger handler already reads `request.scope["root_path"]` and prefixes asset/OpenAPI URLs. The redoc handler does not. Make the redoc handler match the swagger pattern. No public API change.

**Tech Stack:** FastAPI, Starlette, pytest, fastapi.testclient.

**Parent spec:** `docs/superpowers/specs/2026-05-31-audit-implementation-sequencing.md` (PR1 section).
**Parent audit:** `docs/superpowers/specs/2026-05-31-bug-refactor-audit.md` (CRIT-1, TEST-1).

---

## File Structure

Two existing files modified. No new files.

- Modify: `lite_bootstrap/helpers/fastapi_helpers.py:52-58` — change `redoc_html` signature and URL construction.
- Modify: `tests/test_fastapi_offline_docs.py:32-43` — extend `test_fastapi_offline_docs_root_path` to fetch redoc and assert prefixing.

---

## Task 1: Create branch

**Files:**
- (no files; git branch only)

- [ ] **Step 1: Create the feature branch**

From `main` (clean working tree expected):

```bash
git checkout main
git pull --ff-only origin main
git checkout -b fix/crit-1-redoc-root-path
```

Expected: `Switched to a new branch 'fix/crit-1-redoc-root-path'`.

---

## Task 2: Add the failing regression test

**Files:**
- Modify: `tests/test_fastapi_offline_docs.py:32-43`

The existing `test_fastapi_offline_docs_root_path` exercises swagger under `root_path` but never fetches redoc. Extend it to fetch redoc and assert that both the redoc JS URL and the OpenAPI URL in the rendered HTML carry the `/some-root-path` prefix. The default `redoc_url` for a FastAPI app is `/redoc` (no override in the test setup), and the default `openapi_url` is `/openapi.json`.

- [ ] **Step 1: Modify `test_fastapi_offline_docs_root_path`**

Replace the existing function body (lines 33-43) with:

```python
def test_fastapi_offline_docs_root_path() -> None:
    app: FastAPI = FastAPI(title="Tests", root_path="/some-root-path", docs_url="/custom_docs")
    enable_offline_docs(app, static_path="/static")

    with TestClient(app, root_path="/some-root-path") as client:
        response = client.get("/custom_docs")
        assert response.status_code == HTTPStatus.OK
        assert "/some-root-path/static/swagger-ui.css" in response.text
        assert "/some-root-path/static/swagger-ui-bundle.js" in response.text

        response = client.get("/some-root-path/static/swagger-ui.css")
        assert response.status_code == HTTPStatus.OK

        response = client.get("/redoc")
        assert response.status_code == HTTPStatus.OK
        assert "/some-root-path/static/redoc.standalone.js" in response.text
        assert "/some-root-path/openapi.json" in response.text
```

The four added lines: the redoc GET, the status assertion, the redoc JS URL assertion, the OpenAPI URL assertion.

- [ ] **Step 2: Run the test and verify it FAILS**

Run:

```bash
just test -- tests/test_fastapi_offline_docs.py::test_fastapi_offline_docs_root_path -v
```

Expected: **FAIL** with an assertion error on one of the two new asserts — most likely
`assert "/some-root-path/static/redoc.standalone.js" in response.text` fails because the
rendered HTML contains `/static/redoc.standalone.js` (no `/some-root-path/` prefix).

If the test does not fail, stop and investigate — either the assertion is wrong, or the bug
isn't present (which would mean the audit is stale).

---

## Task 3: Implement the redoc fix

**Files:**
- Modify: `lite_bootstrap/helpers/fastapi_helpers.py:52-58`

The swagger handler at lines 37-46 is the pattern to mirror: it takes `request: Request`,
reads `root_path` from the ASGI scope, and prefixes asset URLs and the OpenAPI URL.

- [ ] **Step 1: Replace the `redoc_html` handler**

Replace lines 52-58 of `lite_bootstrap/helpers/fastapi_helpers.py` with:

```python
    @app.get(redoc_url, include_in_schema=False)
    async def redoc_html(request: Request) -> HTMLResponse:
        root_path = request.scope.get("root_path", "").rstrip("/")
        return get_redoc_html(
            openapi_url=f"{root_path}{app_openapi_url}",
            title=f"{app.title} - ReDoc",
            redoc_js_url=f"{root_path}{static_path}/redoc.standalone.js",
        )
```

Notes:
- `Request` is already imported at line 9.
- `root_path` handling matches the swagger handler exactly (`request.scope.get("root_path", "").rstrip("/")`).
- Both `openapi_url` and `redoc_js_url` get the prefix. The audit (CRIT-1) flagged the JS URL; the OpenAPI URL has the same bug — the test in Task 2 catches both.

- [ ] **Step 2: Run the previously-failing test and verify it PASSES**

Run:

```bash
just test -- tests/test_fastapi_offline_docs.py::test_fastapi_offline_docs_root_path -v
```

Expected: **PASS**.

- [ ] **Step 3: Run the full offline-docs test file**

Run:

```bash
just test -- tests/test_fastapi_offline_docs.py -v
```

Expected: all three tests PASS — `test_fastapi_offline_docs`,
`test_fastapi_offline_docs_root_path`, `test_fastapi_offline_docs_raises_without_openapi_url`.

This confirms the change didn't break the no-`root_path` path or the error path.

- [ ] **Step 4: Run the full test suite**

Run:

```bash
just test
```

Expected: all tests PASS with no new failures.

- [ ] **Step 5: Run lint**

Run:

```bash
just lint
```

Expected: no errors. The change is small and follows existing patterns, so ruff, eof-fixer,
and `ty check` should all pass.

- [ ] **Step 6: Commit**

Stage both modified files explicitly:

```bash
git add lite_bootstrap/helpers/fastapi_helpers.py tests/test_fastapi_offline_docs.py
git commit -m "$(cat <<'EOF'
fix: honor root_path in offline-docs redoc handler

The swagger handler in enable_offline_docs already reads root_path from
the ASGI scope and prefixes asset/OpenAPI URLs. The redoc handler did
not, so redoc 404'd on its JS and OpenAPI spec when the FastAPI app
ran behind a reverse proxy. Mirror the swagger pattern: take Request,
read root_path, prefix both redoc_js_url and openapi_url.

Extends test_fastapi_offline_docs_root_path to fetch redoc and assert
both URLs carry the prefix — the test fails on the prior code.

Closes CRIT-1, TEST-1 from the audit.
EOF
)"
```

Expected: commit succeeds. (No pre-commit hooks are configured in this repo — see `.pre-commit-config.yaml` absence in repo root.)

---

## Task 4: Push and open PR

**Files:**
- (no files; git push + gh)

- [ ] **Step 1: Push the branch**

```bash
git push -u origin fix/crit-1-redoc-root-path
```

Expected: branch published; gh CLI may print a PR-creation URL.

- [ ] **Step 2: Open the PR**

```bash
gh pr create --title "fix: honor root_path in offline-docs redoc handler" --body "$(cat <<'EOF'
## Summary
- Redoc handler in `enable_offline_docs` now reads `root_path` from the ASGI scope and prefixes both `redoc_js_url` and `openapi_url`, matching the existing swagger handler pattern.
- Existing `test_fastapi_offline_docs_root_path` extended to fetch redoc and assert both URLs carry the `root_path` prefix. Test fails on `main`, passes on this branch.

Closes CRIT-1 and TEST-1 from `docs/superpowers/specs/2026-05-31-bug-refactor-audit.md`.

## Test plan
- [x] `just test -- tests/test_fastapi_offline_docs.py -v` — three tests pass.
- [x] `just test` — full suite passes.
- [x] `just lint` — clean.
- [ ] Reviewer: confirm the diff matches the swagger handler's `root_path` pattern.
EOF
)"
```

Expected: PR created; PR URL printed.

---

## Self-Review

Spec coverage check against `2026-05-31-audit-implementation-sequencing.md`, PR1 section:

| Spec item | Task |
|-----------|------|
| Refactor `redoc_html` to accept `Request` | Task 3, Step 1 |
| Read `root_path` from `request.scope` and rstrip | Task 3, Step 1 |
| Prepend prefix to `redoc_js_url` | Task 3, Step 1 |
| Prepend prefix to `openapi_url` (also missing it) | Task 3, Step 1 |
| Extend `test_fastapi_offline_docs_root_path` to fetch redoc and assert prefix | Task 2, Step 1 |
| Verification: `just test` passes | Task 3, Steps 3-4 |
| Branch name `fix/crit-1-redoc-root-path` | Task 1, Step 1 |

All spec items covered. No placeholders. Method signatures (`redoc_html(request: Request)`,
`request.scope.get("root_path", "")`) are consistent across Task 2's test expectations
and Task 3's implementation. The test asserts on `/some-root-path/static/redoc.standalone.js`
and `/some-root-path/openapi.json`; the implementation produces those exact strings.


---

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


---

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


---

# PR4: Sentry `skip_sentry` Leak Fix + Dead `is_X_installed` Conjuncts Cleanup

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship two small audit cleanups in one PR:

- **DES-4:** Add `"skip_sentry"` to `IGNORED_STRUCTLOG_ATTRIBUTES` so the flag stops leaking into Sentry's `contexts.structlog` when set to falsy (the function already suppresses the event for truthy values, but doesn't strip the field for falsy ones).
- **DES-5:** Delete the dead `and import_checker.is_X_installed` conjuncts from four instruments' `is_ready()` methods. They're provably unreachable: `_register_or_skip` runs `check_dependencies()` before instantiating the instrument; if `check_dependencies()` returns False, `is_ready()` is never called.

**Architecture:** Five files modified — four production deletions/additions and one test case. No new abstractions. No API changes.

**Tech Stack:** Python 3.10+, pytest parametrized tests, sentry_sdk types.

**Parent spec:** `docs/superpowers/specs/2026-05-31-audit-implementation-sequencing.md` (PR4 section).
**Parent audit:** `docs/superpowers/specs/2026-05-31-bug-refactor-audit.md` (DES-4, DES-5).

---

## File Structure

Four production files modified; one test file modified.

- Modify: `lite_bootstrap/instruments/sentry_instrument.py` — add `"skip_sentry"` to `IGNORED_STRUCTLOG_ATTRIBUTES` (DES-4); drop dead conjunct from `SentryInstrument.is_ready()` (DES-5).
- Modify: `lite_bootstrap/instruments/logging_instrument.py:139-140` — drop dead conjunct from `LoggingInstrument.is_ready()` (DES-5).
- Modify: `lite_bootstrap/instruments/opentelemetry_instrument.py:82-86` — drop dead conjunct from `OpenTelemetryInstrument.is_ready()` (DES-5).
- Modify: `lite_bootstrap/instruments/pyroscope_instrument.py:28-29` — drop dead conjunct from `PyroscopeInstrument.is_ready()` (DES-5).
- Modify: `tests/instruments/test_sentry_instrument.py` — add parametrize case to `TestSentryEnrichEventFromStructlog::test_modify` covering the `skip_sentry=False` case.

---

## Locked decisions

- **Bundling DES-4 + DES-5:** They're independent in scope but both trivial and both touch instrument files. Reviewing them together is cheaper than two PRs.
- **DES-4 test placement:** Extend the existing `test_modify` parametrize block in `TestSentryEnrichEventFromStructlog`. Same shape as adjacent cases; no new test method.
- **DES-5 testing:** No new tests. Pure dead-code deletion. The existing test suite already exercises the `is_ready()` paths via the framework integration tests; any breakage shows up there.

---

## Task 1: Create branch

**Files:** (no files; git only)

- [ ] **Step 1: Branch off `main`**

```bash
git checkout main
git pull --ff-only origin main
git checkout -b fix/des-4-5-small-cleanups
```

Expected: `Switched to a new branch 'fix/des-4-5-small-cleanups'`.

If PR3 (`fix/crit-3-idempotent-teardown`) has not yet merged, that's fine — PR4 touches different files. Branch from current `main` regardless.

---

## Task 2: Add the failing regression test (DES-4)

**File:** `tests/instruments/test_sentry_instrument.py`

The file already has a class `TestSentryEnrichEventFromStructlog` with a parametrized `test_modify` method. Add a third case to its parametrize list that covers the `skip_sentry=False` scenario.

- [ ] **Step 1: Add the new parametrize case**

Current `test_modify` (around line 92 of the file) has two cases in its parametrize list. The list looks like:

```python
    @pytest.mark.parametrize(
        ("event_before", "event_after"),
        [
            (
                {"logentry": {"formatted": '{"event": "event name"}'}, "contexts": {}},
                {"logentry": {"formatted": "event name"}, "contexts": {}},
            ),
            (
                {
                    "logentry": {
                        "formatted": '{"event": "event name", "timestamp": 1, "level": "error", "logger": "event.logger", "tracing": {}, "foo": "bar"}'  # noqa: E501
                    },
                    "contexts": {},
                },
                {
                    "logentry": {"formatted": "event name"},
                    "contexts": {"structlog": {"foo": "bar"}},
                },
            ),
        ],
    )
    def test_modify(self, event_before: "sentry_types.Event", event_after: "sentry_types.Event") -> None:
        assert enrich_sentry_event_from_structlog_log(event_before, {}) == event_after
```

Add a third tuple to the parametrize list, after the existing two cases (preserving trailing comma in the list):

```python
            (
                {
                    "logentry": {
                        "formatted": '{"event": "event name", "skip_sentry": false, "foo": "bar"}'
                    },
                    "contexts": {},
                },
                {
                    "logentry": {"formatted": "event name"},
                    "contexts": {"structlog": {"foo": "bar"}},
                },
            ),
```

The contract: when a structlog payload contains `skip_sentry=false` (a falsy value that doesn't trigger event suppression), the resulting `contexts.structlog` should contain `{"foo": "bar"}` only — `skip_sentry` should be stripped.

- [ ] **Step 2: Run the test and verify it FAILS**

```bash
just test -- 'tests/instruments/test_sentry_instrument.py::TestSentryEnrichEventFromStructlog::test_modify' -v
```

Expected: one of the three parametrize cases (the new one) **FAILS** because the current `IGNORED_STRUCTLOG_ATTRIBUTES` set doesn't include `"skip_sentry"`. The actual `contexts.structlog` will be `{"skip_sentry": False, "foo": "bar"}`, which doesn't equal the expected `{"foo": "bar"}`. The other two cases should still PASS.

If the new case passes, stop and investigate — either the assertion is wrong, or the bug isn't present.

---

## Task 3: Implement all changes

Five small edits across four production files. Apply them all, run tests, lint, commit.

### Fix 1 (DES-4): Strip `skip_sentry` from Sentry context

- [ ] **Step 1: Add `"skip_sentry"` to `IGNORED_STRUCTLOG_ATTRIBUTES`**

**File:** `lite_bootstrap/instruments/sentry_instrument.py:19-21`

Current:

```python
IGNORED_STRUCTLOG_ATTRIBUTES: typing.Final = frozenset(
    {"event", "level", "logger", "tracing", "timestamp", "exception"}
)
```

Replace with:

```python
IGNORED_STRUCTLOG_ATTRIBUTES: typing.Final = frozenset(
    {"event", "level", "logger", "tracing", "timestamp", "exception", "skip_sentry"}
)
```

### Fix 2 (DES-5): Drop dead conjunct from `SentryInstrument.is_ready()`

- [ ] **Step 2: Simplify `SentryInstrument.is_ready()`**

**File:** `lite_bootstrap/instruments/sentry_instrument.py:100-101`

Current:

```python
    def is_ready(self) -> bool:
        return bool(self.bootstrap_config.sentry_dsn) and import_checker.is_sentry_installed
```

Replace with:

```python
    def is_ready(self) -> bool:
        return bool(self.bootstrap_config.sentry_dsn)
```

### Fix 3 (DES-5): Drop dead conjunct from `LoggingInstrument.is_ready()`

- [ ] **Step 3: Simplify `LoggingInstrument.is_ready()`**

**File:** `lite_bootstrap/instruments/logging_instrument.py:139-140`

Current:

```python
    def is_ready(self) -> bool:
        return self.bootstrap_config.logging_enabled and import_checker.is_structlog_installed
```

Replace with:

```python
    def is_ready(self) -> bool:
        return self.bootstrap_config.logging_enabled
```

### Fix 4 (DES-5): Drop dead conjunct from `OpenTelemetryInstrument.is_ready()`

- [ ] **Step 4: Simplify `OpenTelemetryInstrument.is_ready()`**

**File:** `lite_bootstrap/instruments/opentelemetry_instrument.py:82-86`

Current:

```python
    def is_ready(self) -> bool:
        return (
            bool(self.bootstrap_config.opentelemetry_endpoint or self.bootstrap_config.opentelemetry_log_traces)
            and import_checker.is_opentelemetry_installed
        )
```

Replace with:

```python
    def is_ready(self) -> bool:
        return bool(self.bootstrap_config.opentelemetry_endpoint or self.bootstrap_config.opentelemetry_log_traces)
```

### Fix 5 (DES-5): Drop dead conjunct from `PyroscopeInstrument.is_ready()`

- [ ] **Step 5: Simplify `PyroscopeInstrument.is_ready()`**

**File:** `lite_bootstrap/instruments/pyroscope_instrument.py:28-29`

Current:

```python
    def is_ready(self) -> bool:
        return bool(self.bootstrap_config.pyroscope_endpoint) and import_checker.is_pyroscope_installed
```

Replace with:

```python
    def is_ready(self) -> bool:
        return bool(self.bootstrap_config.pyroscope_endpoint)
```

### Verify and commit

- [ ] **Step 6: Run the previously-failing test, verify PASS**

```bash
just test -- 'tests/instruments/test_sentry_instrument.py::TestSentryEnrichEventFromStructlog' -v
```

Expected: all three `test_modify` cases PASS.

- [ ] **Step 7: Run the full test suite**

```bash
just test
```

Expected: all tests PASS. The dead-conjunct deletions are provably no-ops at runtime (the `_register_or_skip` flow in `bootstrappers/base.py` checks `check_dependencies()` before any `is_ready()` call), so existing tests that exercise the missing-dependency path — e.g., `test_fastapi_bootstrapper_with_missing_instrument_dependency`, `test_litestar_bootstrapper_with_missing_instrument_dependency`, `test_free_bootstrapper_with_missing_instrument_dependency` — should still pass unchanged. If any of those fail, stop and investigate: the invariant we're relying on may not hold somewhere.

- [ ] **Step 8: Run lint**

```bash
just lint
```

Expected: no errors. The four `import_checker` references being removed leave the import statement still used elsewhere in each file (e.g., `bootstrap()` methods), so no unused-import warnings should fire. Confirm.

If a file ends up with `from lite_bootstrap import import_checker` no longer referenced anywhere, ruff `F401` will flag it. In that case, also remove the import. Most likely candidate is `pyroscope_instrument.py` (verify by reading the file).

Actually, all four instrument files use `import_checker` in their `check_dependencies()` method as well, so the import will remain needed. Just confirm with `just lint`.

- [ ] **Step 9: Commit (stage exactly 5 files)**

```bash
git add \
  lite_bootstrap/instruments/sentry_instrument.py \
  lite_bootstrap/instruments/logging_instrument.py \
  lite_bootstrap/instruments/opentelemetry_instrument.py \
  lite_bootstrap/instruments/pyroscope_instrument.py \
  tests/instruments/test_sentry_instrument.py
git commit -m "$(cat <<'EOF'
fix: strip skip_sentry from Sentry context; drop dead is_X_installed conjuncts

DES-4: enrich_sentry_event_from_structlog_log was already returning None
(suppressing the event) when skip_sentry was truthy, but for falsy values
(False, missing, "") the flag itself was not stripped from the structlog
payload before it was attached to event["contexts"]["structlog"]. Add
"skip_sentry" to IGNORED_STRUCTLOG_ATTRIBUTES so the field never leaks
into Sentry context noise. Regression test added as a parametrize case
on the existing test_modify.

DES-5: each affected instrument's is_ready() returned `<config check> and
import_checker.is_X_installed`. The conjunct is provably dead: BaseBootstrapper
calls check_dependencies() in _register_or_skip before instantiating the
instrument, and only invokes is_ready() if check_dependencies() returned True.
Drop the redundant conjunct from SentryInstrument, LoggingInstrument,
OpenTelemetryInstrument, and PyroscopeInstrument. Behavior is unchanged.

Closes DES-4 and DES-5 from the audit.
EOF
)"
```

---

## Task 4: Push and open PR

**Files:** (no files; git push + gh)

- [ ] **Step 1: Push the branch**

```bash
git push -u origin fix/des-4-5-small-cleanups
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --title "fix: strip skip_sentry from Sentry context; drop dead is_X_installed conjuncts" --body "$(cat <<'EOF'
## Summary
Two small audit cleanups bundled:

- **DES-4 (Sentry):** \`skip_sentry\` was already triggering event suppression when truthy, but for falsy values (False/missing/"") the flag itself wasn't stripped from the structlog payload and ended up as noise in \`event["contexts"]["structlog"]\`. Add \`"skip_sentry"\` to \`IGNORED_STRUCTLOG_ATTRIBUTES\`. Regression test added as a parametrize case on the existing \`test_modify\`.
- **DES-5 (dead conjuncts):** Four instruments' \`is_ready()\` methods ended with \`and import_checker.is_X_installed\`. That conjunct is provably unreachable — \`BaseBootstrapper._register_or_skip\` calls \`check_dependencies()\` first and only invokes \`is_ready()\` if it returned True. Behavior is unchanged. Cleanup makes the lifecycle easier to reason about.

Closes DES-4 and DES-5 from an internal audit.

## Test plan
- [x] \`just test -- tests/instruments/test_sentry_instrument.py -v\` — pass.
- [x] \`just test\` — full suite passes.
- [x] \`just lint\` — clean (no unused-import warnings from the conjunct removals).
- [ ] Reviewer: confirm the invariant claim — that \`is_ready()\` is only called after \`check_dependencies()\` has returned True — by reading \`bootstrappers/base.py:44-64\`.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review

**Spec coverage check** against the sequencing spec (PR4 section) and audit (DES-4, DES-5):

| Spec item | Task |
|-----------|------|
| Add `"skip_sentry"` to `IGNORED_STRUCTLOG_ATTRIBUTES` | Task 3, Step 1 |
| Regression test asserting `skip_sentry` doesn't appear in context | Task 2, Step 1 |
| Delete dead conjunct from `SentryInstrument.is_ready()` | Task 3, Step 2 |
| Delete dead conjunct from `LoggingInstrument.is_ready()` | Task 3, Step 3 |
| Delete dead conjunct from `OpenTelemetryInstrument.is_ready()` | Task 3, Step 4 |
| Delete dead conjunct from `PyroscopeInstrument.is_ready()` | Task 3, Step 5 |
| Branch name `fix/des-4-5-small-cleanups` | Task 1, Step 1 |
| Verification: `just test` + `just lint` pass | Task 3, Steps 7-8 |

All spec items covered. No placeholders. Parametrize-case shape matches adjacent cases byte-for-byte except for the payload values.

**Deferred:**
- Documenting the lifecycle invariant on `BaseInstrument` (mentioned as "optional" in the sequencing spec) — skip for now to keep the PR focused. Worth noting somewhere later (a `CONTRIBUTING.md`, or class docstrings as part of REF-3).


---

# PR5: Document and Pin `BaseConfig.from_dict` / `from_object` Semantics

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Document the intentional asymmetry between `BaseConfig.from_dict` and `BaseConfig.from_object` (the audit's DES-3 finding) and pin it with regression tests. No behavior change. The current "skip None" behavior in `from_object` is preserved (locked decision from the sequencing spec).

**Architecture:** Pure documentation + test PR. Add one-line docstrings to the two classmethods explaining their semantics; add four pinning tests in `tests/test_config.py` that lock in the current contract. No TDD red→green here — the tests pass today; their value is preventing future regressions that "unify" the methods without realizing the asymmetry is intentional.

**Tech Stack:** Python 3.10+ dataclasses, pytest.

**Parent spec:** `docs/superpowers/specs/2026-05-31-audit-implementation-sequencing.md` (PR5 section).
**Parent audit:** `docs/superpowers/specs/2026-05-31-bug-refactor-audit.md` (DES-3, TEST-5, TEST-6).

---

## File Structure

Two files modified.

- Modify: `lite_bootstrap/instruments/base.py:16-29` — add one-line docstrings to `from_dict` and `from_object`.
- Modify: `tests/test_config.py` — add four pinning tests.

---

## Locked decisions (from sequencing spec)

- **`from_object` semantics:** Keep current "skip None" behavior. Document it. Pin with tests. Minimal change; preserves any user code that depends on it.
- **No TDD:** This PR documents and pins existing behavior. The new tests are pinning tests, not TDD red→green tests. They will pass before and after the docstring additions. Their value is preventing future regressions, not driving a bug fix.
- **Docstring length:** One short line each. Project style is terse (no docstrings on most code; one-line docstrings on the exception classes). Multi-paragraph docstrings would be inconsistent.

---

## Task 1: Create branch

**Files:** (no files; git only)

- [ ] **Step 1: Branch off `main`**

```bash
git checkout main
git pull --ff-only origin main
git checkout -b fix/des-3-config-method-semantics
```

Expected: `Switched to a new branch 'fix/des-3-config-method-semantics'`.

If PR4 has not yet merged, that's fine — PR5 touches different files.

---

## Task 2: Add docstrings and pinning tests, verify, commit

### Step 1: Add docstrings to `BaseConfig.from_dict` and `from_object`

**File:** `lite_bootstrap/instruments/base.py:16-29`

Current code:

```python
    @classmethod
    def from_dict(cls, data: dict[str, typing.Any]) -> typing_extensions.Self:
        field_names = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in field_names})

    @classmethod
    def from_object(cls, obj: object) -> typing_extensions.Self:
        prepared_data = {}
        field_names = {f.name for f in dataclasses.fields(cls)}

        for field in field_names:
            if (value := getattr(obj, field, None)) is not None:
                prepared_data[field] = value
        return cls(**prepared_data)
```

Replace with:

```python
    @classmethod
    def from_dict(cls, data: dict[str, typing.Any]) -> typing_extensions.Self:
        """Build a config from a dict; unknown keys are silently dropped, explicit None overrides defaults."""
        field_names = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in field_names})

    @classmethod
    def from_object(cls, obj: object) -> typing_extensions.Self:
        """Build a config by merging non-None attributes from obj; None or missing attributes fall back to defaults."""
        field_names = {f.name for f in dataclasses.fields(cls)}
        prepared_data = {field: value for field in field_names if (value := getattr(obj, field, None)) is not None}
        return cls(**prepared_data)
```

Notes:
- Two docstring additions.
- The body of `from_object` is also condensed from a 5-line imperative form to a single comprehension. **Functionally identical.** The walrus-operator-inside-comprehension form is a more idiomatic match for the "filter non-None" intent and matches the dict-comprehension already used by `from_dict`. The condensation is a quality cleanup; verify behavior with the new pinning tests.

If the reviewer pushes back on the body condensation, the alternative is to leave the body as-is and only add the docstring. The docstring is the spec-required change; the body cleanup is opportunistic.

### Step 2: Add four pinning tests to `tests/test_config.py`

**File:** `tests/test_config.py`

The file currently has two tests (`test_config_from_dict`, `test_config_from_object`). Append the four new tests at the end of the file.

Current top of file:

```python
import dataclasses

from lite_bootstrap import FastAPIConfig
from lite_bootstrap.instruments.base import BaseConfig
from tests.conftest import CustomInstrumentor
```

No new imports needed.

Append at the end of the file:

```python
def test_from_object_skips_none_attribute() -> None:
    @dataclasses.dataclass
    class Source:
        service_name: str | None = None
        service_version: str = "2.0.0"

    config = BaseConfig.from_object(Source())
    assert config.service_name == "micro-service"
    assert config.service_version == "2.0.0"


def test_from_object_skips_missing_attribute() -> None:
    class Source:
        pass

    config = BaseConfig.from_object(Source())
    assert config.service_name == "micro-service"
    assert config.service_version == "1.0.0"
    assert config.service_debug is True


def test_from_object_preserves_falsy_values() -> None:
    @dataclasses.dataclass
    class Source:
        service_name: str = ""
        service_debug: bool = False

    config = BaseConfig.from_object(Source())
    assert config.service_name == ""
    assert config.service_debug is False


def test_from_dict_drops_unknown_keys_silently() -> None:
    config = BaseConfig.from_dict({"service_name": "test", "unknown_key": "value"})
    assert config.service_name == "test"
    assert config.service_version == "1.0.0"
```

Contracts pinned:
- `test_from_object_skips_none_attribute` — explicit `None` attribute on source falls back to dataclass default.
- `test_from_object_skips_missing_attribute` — missing attribute on source falls back to dataclass default.
- `test_from_object_preserves_falsy_values` — empty string and `False` are not stripped (they're not `None`).
- `test_from_dict_drops_unknown_keys_silently` — unknown keys don't raise; known keys are honored.

### Step 3: Run the new tests, verify PASS

These tests pin existing behavior; they should pass before and after the docstring additions.

```bash
just test -- tests/test_config.py -v
```

Expected: all six tests in `tests/test_config.py` PASS (two pre-existing + four new).

If any of the four new tests fails, stop and investigate — the audit's claim about `from_object` behavior may be inaccurate, or the docstring body condensation may have introduced a regression.

### Step 4: Run the full test suite

```bash
just test
```

Expected: all tests PASS. Total should be 88 (84 prior + 4 new).

### Step 5: Run lint

```bash
just lint
```

Expected: no errors. The dict-comprehension form may trigger ruff's preference for one style or another — confirm. If ruff auto-formats the comprehension, accept the formatting and re-stage.

### Step 6: Commit

Stage both modified files explicitly:

```bash
git add lite_bootstrap/instruments/base.py tests/test_config.py
git commit -m "$(cat <<'EOF'
docs: document and pin BaseConfig.from_dict / from_object semantics

The two builder classmethods on BaseConfig have intentionally asymmetric
semantics that aren't obvious from reading the code:

- from_dict includes any key present in the dict (explicit None overrides
  the default); unknown keys are silently dropped.
- from_object includes only attributes whose value is not None; attributes
  set to None or missing entirely fall back to the dataclass default.
  Falsy non-None values (False, "", []) are preserved.

Add one-line docstrings capturing each method's contract. Condense the
from_object body to a single dict-comprehension matching from_dict's style;
behavior is identical (verified by the new pinning tests).

Add four pinning tests on top of the two pre-existing tests:
- test_from_object_skips_none_attribute
- test_from_object_skips_missing_attribute
- test_from_object_preserves_falsy_values
- test_from_dict_drops_unknown_keys_silently

Closes DES-3, TEST-5, TEST-6 from the audit.
EOF
)"
```

Expected: commit succeeds.

---

## Task 3: Push and open PR

**Files:** (no files; git push + gh)

- [ ] **Step 1: Push the branch**

```bash
git push -u origin fix/des-3-config-method-semantics
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --title "docs: document and pin BaseConfig.from_dict / from_object semantics" --body "$(cat <<'EOF'
## Summary
Document the intentional asymmetry between \`BaseConfig.from_dict\` and \`BaseConfig.from_object\` (DES-3 from an internal audit):

- \`from_dict\` includes any key present in the dict (explicit \`None\` overrides defaults); unknown keys are silently dropped.
- \`from_object\` includes only non-\`None\` attributes (\`None\` or missing falls back to dataclass defaults); falsy non-\`None\` values are preserved.

Each method gains a one-line docstring capturing its contract. The \`from_object\` body is condensed to a single dict-comprehension matching \`from_dict\`'s style; behavior is identical and locked in by the new pinning tests.

Four pinning tests added (TEST-5, TEST-6 from the audit):
- \`test_from_object_skips_none_attribute\`
- \`test_from_object_skips_missing_attribute\`
- \`test_from_object_preserves_falsy_values\`
- \`test_from_dict_drops_unknown_keys_silently\`

These pass before and after the docstring additions — they pin existing behavior to prevent future regressions where someone "unifies" the two methods without realizing the asymmetry is intentional.

Closes DES-3, TEST-5, TEST-6 from an internal audit.

## Test plan
- [x] \`just test -- tests/test_config.py -v\` — six tests pass.
- [x] \`just test\` — full suite passes (88 expected).
- [x] \`just lint\` — clean.
- [ ] Reviewer: confirm the \`from_object\` body condensation (5 lines → 1 dict-comprehension) is functionally identical. If you'd rather see the docstring change land without the body cleanup, request a revert.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review

**Spec coverage check** against the sequencing spec (PR5 section) and audit (DES-3, TEST-5, TEST-6):

| Spec item | Task |
|-----------|------|
| Docstring on `from_dict` describing semantics | Task 2, Step 1 |
| Docstring on `from_object` describing semantics | Task 2, Step 1 |
| Test: `from_object` with `None` attribute falls back to default | Task 2, Step 2 (test_from_object_skips_none_attribute) |
| Test: `from_object` with missing attribute falls back to default | Task 2, Step 2 (test_from_object_skips_missing_attribute) |
| Test: `from_object` preserves falsy non-None | Task 2, Step 2 (test_from_object_preserves_falsy_values) |
| Test: `from_dict` drops unknown keys silently | Task 2, Step 2 (test_from_dict_drops_unknown_keys_silently) |
| Branch name `fix/des-3-config-method-semantics` | Task 1, Step 1 |
| Verification: `just test` + `just lint` clean | Task 2, Steps 4-5 |

All spec items covered. No placeholders. Test names and contracts are consistent with the audit's TEST-5 and TEST-6 descriptions.

**Caveats noted in PR description:**
- Body condensation in `from_object` is an opportunistic cleanup, not spec-required. If the reviewer prefers a docstring-only change, the body cleanup can be reverted with a one-character edit.


---

# PR6: Extract OpenTelemetry Service Fields Mixin

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract `opentelemetry_service_name` and `opentelemetry_namespace` into a shared mixin dataclass so both `OpentelemetryConfig` and `PyroscopeConfig` inherit from it instead of duplicating the field declarations (the audit's DES-2 finding). Today the two configs declare these fields identically; in the framework configs they survive only because Python's MRO picks one and the defaults happen to match. The mixin makes the shared identity explicit.

**Architecture:** Pure refactor PR. New tiny dataclass `OpenTelemetryServiceFieldsConfig(BaseConfig)` in `opentelemetry_instrument.py`. Both `OpentelemetryConfig` and `PyroscopeConfig` inherit from it instead of `BaseConfig`. The two duplicate field declarations are removed. No behavior change; existing tests verify MRO continues to resolve correctly across the four framework configs (`FreeBootstrapperConfig`, `FastAPIConfig`, `LitestarConfig`, `FastStreamConfig`) that inherit from both.

**Tech Stack:** Python 3.10+ dataclasses with `kw_only=True, frozen=True`.

**Parent spec:** `docs/superpowers/specs/2026-05-31-audit-implementation-sequencing.md` (PR6 section).
**Parent audit:** `docs/superpowers/specs/2026-05-31-bug-refactor-audit.md` (DES-2).

---

## File Structure

Two files modified. No new files.

- Modify: `lite_bootstrap/instruments/opentelemetry_instrument.py` — declare `OpenTelemetryServiceFieldsConfig` mixin before `OpentelemetryConfig`; change `OpentelemetryConfig` to inherit from the mixin; remove the two duplicate field declarations.
- Modify: `lite_bootstrap/instruments/pyroscope_instrument.py` — add an import for `OpenTelemetryServiceFieldsConfig`; change `PyroscopeConfig` to inherit from the mixin; remove the two duplicate field declarations.

---

## Locked decisions (from sequencing spec)

- **Mixin location:** Inline in `opentelemetry_instrument.py`. Fewer files; the mixin is small; `pyroscope_instrument` already imports otel-adjacent symbols (via the SpanProcessor integration in the OTel module).
- **Mixin name:** `OpenTelemetryServiceFieldsConfig`.
- **No new tests:** This is a pure refactor. Existing tests — particularly `test_pyroscope_standalone_config_accepts_otel_fields` in `tests/instruments/test_pyroscope_instrument.py` — already exercise the inheritance path. If those pass, MRO is still working.

---

## Cross-module dependency note

After this PR, `pyroscope_instrument.py` will import `OpenTelemetryServiceFieldsConfig` from `opentelemetry_instrument.py`. This is a new module-level dependency direction (pyroscope → opentelemetry). Verify there's no circular import:

- `opentelemetry_instrument.py` imports the `pyroscope` *package* (external) inside an `if import_checker.is_pyroscope_installed:` guard. It does NOT import `lite_bootstrap.instruments.pyroscope_instrument`.
- After PR6, `pyroscope_instrument.py` will import from `lite_bootstrap.instruments.opentelemetry_instrument`. No cycle.

---

## Task 1: Create branch

**Files:** (no files; git only)

- [ ] **Step 1: Branch off `main`**

```bash
git checkout main
git pull --ff-only origin main
git checkout -b fix/des-2-otel-fields-mixin
```

Expected: `Switched to a new branch 'fix/des-2-otel-fields-mixin'`.

---

## Task 2: Apply the refactor, verify, commit

### Step 1: Add the mixin to `opentelemetry_instrument.py` and update `OpentelemetryConfig`

**File:** `lite_bootstrap/instruments/opentelemetry_instrument.py`

Current `OpentelemetryConfig` (around lines 35-49):

```python
@dataclasses.dataclass(kw_only=True, frozen=True)
class OpentelemetryConfig(BaseConfig):
    opentelemetry_service_name: str | None = None
    opentelemetry_container_name: str | None = dataclasses.field(
        default_factory=lambda: os.environ.get("HOSTNAME") or None
    )
    opentelemetry_endpoint: str | None = None
    opentelemetry_namespace: str | None = None
    opentelemetry_insecure: bool = True
    opentelemetry_instrumentors: list[typing.Union[InstrumentorWithParams, "BaseInstrumentor"]] = dataclasses.field(
        default_factory=list
    )
    opentelemetry_log_traces: bool = False
    opentelemetry_generate_health_check_spans: bool = True
```

Replace with (add the mixin class **before** `OpentelemetryConfig`, then change `OpentelemetryConfig` to inherit from it and remove the two duplicate field declarations):

```python
@dataclasses.dataclass(kw_only=True, frozen=True)
class OpenTelemetryServiceFieldsConfig(BaseConfig):
    opentelemetry_service_name: str | None = None
    opentelemetry_namespace: str | None = None


@dataclasses.dataclass(kw_only=True, frozen=True)
class OpentelemetryConfig(OpenTelemetryServiceFieldsConfig):
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

Two changes:
1. New `OpenTelemetryServiceFieldsConfig` dataclass declared above `OpentelemetryConfig` with `opentelemetry_service_name` and `opentelemetry_namespace`.
2. `OpentelemetryConfig` parent changed from `BaseConfig` to `OpenTelemetryServiceFieldsConfig`; the two fields it used to declare are removed.

### Step 2: Update `PyroscopeConfig` in `pyroscope_instrument.py`

**File:** `lite_bootstrap/instruments/pyroscope_instrument.py`

Current top of file:

```python
import dataclasses
import typing

from lite_bootstrap import import_checker
from lite_bootstrap.instruments.base import BaseConfig, BaseInstrument


if import_checker.is_pyroscope_installed:
    import pyroscope
```

Replace with (add `OpenTelemetryServiceFieldsConfig` import; drop the now-unused `BaseConfig` import):

```python
import dataclasses
import typing

from lite_bootstrap import import_checker
from lite_bootstrap.instruments.base import BaseInstrument
from lite_bootstrap.instruments.opentelemetry_instrument import OpenTelemetryServiceFieldsConfig


if import_checker.is_pyroscope_installed:
    import pyroscope
```

**Verify before staging:** is `BaseConfig` still used elsewhere in this file? Search with `grep "BaseConfig" lite_bootstrap/instruments/pyroscope_instrument.py`. If the only use was in the `PyroscopeConfig` parent (which is being changed to `OpenTelemetryServiceFieldsConfig`), drop the import. If it's used elsewhere, keep it.

Based on the current file structure, `BaseConfig` is only used as the `PyroscopeConfig` parent — drop the import. `just lint` will catch any mistake (F401 unused import or F821 undefined name).

Current `PyroscopeConfig` (around lines 12-19):

```python
@dataclasses.dataclass(kw_only=True, frozen=True)
class PyroscopeConfig(BaseConfig):
    pyroscope_endpoint: str | None = None
    pyroscope_sample_rate: int = 100
    pyroscope_tags: dict[str, str] = dataclasses.field(default_factory=dict)
    pyroscope_additional_params: dict[str, typing.Any] = dataclasses.field(default_factory=dict)
    opentelemetry_service_name: str | None = None
    opentelemetry_namespace: str | None = None
```

Replace with:

```python
@dataclasses.dataclass(kw_only=True, frozen=True)
class PyroscopeConfig(OpenTelemetryServiceFieldsConfig):
    pyroscope_endpoint: str | None = None
    pyroscope_sample_rate: int = 100
    pyroscope_tags: dict[str, str] = dataclasses.field(default_factory=dict)
    pyroscope_additional_params: dict[str, typing.Any] = dataclasses.field(default_factory=dict)
```

Two changes:
1. Parent changed from `BaseConfig` to `OpenTelemetryServiceFieldsConfig`.
2. The two duplicate field declarations (`opentelemetry_service_name`, `opentelemetry_namespace`) removed.

### Step 3: Run the OTel + Pyroscope test files

```bash
just test -- tests/instruments/test_opentelemetry_instrument.py tests/instruments/test_pyroscope_instrument.py -v
```

Expected: all tests PASS. Watch specifically for:

- `test_pyroscope_standalone_config_accepts_otel_fields` — this is THE key test for the mixin's correctness. It constructs `PyroscopeConfig(service_name="fallback", pyroscope_endpoint=..., opentelemetry_service_name="otel-name", opentelemetry_namespace="my-ns")`. If MRO breaks, this test fails first.
- `test_pyroscope_bootstrap_uses_opentelemetry_service_name` and `test_pyroscope_bootstrap_merges_namespace_tag` — these exercise the shared fields via `FreeBootstrapperConfig`.

### Step 4: Run the full test suite

```bash
just test
```

Expected: all tests PASS (89 total). The framework configs all inherit from both `OpentelemetryConfig` and `PyroscopeConfig`; with the mixin, Python's MRO resolves the shared fields once via diamond inheritance. If any framework config test fails (e.g., `test_fastapi_bootstrap`, `test_litestar_bootstrap`, `test_faststream_bootstrap`, `test_free_bootstrap`), STOP and investigate — MRO interaction is the most likely cause.

### Step 5: Run lint

```bash
just lint
```

Expected: no errors. Watch for:

- F401 unused import warnings on the `BaseConfig` import in `pyroscope_instrument.py` (should be already removed per Step 2).
- F401 unused import warnings on the `OpenTelemetryServiceFieldsConfig` import (should be referenced in `class PyroscopeConfig(...)`).
- `ty check` should be clean — the inheritance change is type-correct.

### Step 6: Commit

Stage both modified files:

```bash
git add lite_bootstrap/instruments/opentelemetry_instrument.py lite_bootstrap/instruments/pyroscope_instrument.py
git commit -m "$(cat <<'EOF'
refactor: extract OpenTelemetryServiceFieldsConfig mixin

opentelemetry_service_name and opentelemetry_namespace were declared
identically on both OpentelemetryConfig and PyroscopeConfig. In the four
framework configs (Free, FastAPI, Litestar, FastStream) that inherit
from both parents, Python's MRO happened to pick one declaration; the
fact that defaults matched is what kept behavior consistent. Without
the mixin, drifting defaults on one side would silently misbehave on
the framework configs.

Extract OpenTelemetryServiceFieldsConfig(BaseConfig) — a tiny mixin
declaring just those two fields. Both OpentelemetryConfig and
PyroscopeConfig now inherit from it (no longer from BaseConfig
directly). The duplicate declarations are removed.

PyroscopeConfig's standalone use case (without OpentelemetryConfig in
the MRO) is preserved — exercised by
test_pyroscope_standalone_config_accepts_otel_fields.

Closes DES-2 from the audit.
EOF
)"
```

Expected: commit succeeds.

---

## Task 3: Push and open PR

**Files:** (no files; git push + gh)

- [ ] **Step 1: Push the branch**

```bash
git push -u origin fix/des-2-otel-fields-mixin
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --title "refactor: extract OpenTelemetryServiceFieldsConfig mixin" --body "$(cat <<'EOF'
## Summary
\`opentelemetry_service_name\` and \`opentelemetry_namespace\` were declared identically on both \`OpentelemetryConfig\` and \`PyroscopeConfig\`. In the four framework configs (Free, FastAPI, Litestar, FastStream) that inherit from both parents, Python's MRO happened to pick one declaration; the fact that defaults matched is what kept behavior consistent. Without the mixin, drifting defaults on one side would silently misbehave on the framework configs.

Extract \`OpenTelemetryServiceFieldsConfig(BaseConfig)\` — a tiny mixin declaring just those two fields. Both \`OpentelemetryConfig\` and \`PyroscopeConfig\` now inherit from it (no longer from \`BaseConfig\` directly). The duplicate declarations are removed.

No behavior change. Existing tests verify MRO continues to resolve correctly, especially \`test_pyroscope_standalone_config_accepts_otel_fields\` (the key test for the mixin's correctness) and the framework-level integration tests.

Closes DES-2 from an internal audit.

## Test plan
- [x] \`just test -- tests/instruments/test_opentelemetry_instrument.py tests/instruments/test_pyroscope_instrument.py -v\` — pass.
- [x] \`just test\` — full suite 89/89.
- [x] \`just lint\` — clean.
- [ ] Reviewer: confirm the new dependency direction (\`pyroscope_instrument\` → \`opentelemetry_instrument\`) is acceptable and doesn't introduce a circular import (it doesn't — \`opentelemetry_instrument\` imports the \`pyroscope\` package, not \`pyroscope_instrument\`).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review

**Spec coverage check** against the sequencing spec (PR6 section) and audit (DES-2):

| Spec item | Task |
|-----------|------|
| Declare `OpenTelemetryServiceFieldsConfig(BaseConfig)` mixin with the two fields | Task 2, Step 1 |
| Mixin inlined in `opentelemetry_instrument.py` | Task 2, Step 1 |
| `OpentelemetryConfig` inherits from mixin; duplicate fields removed | Task 2, Step 1 |
| `PyroscopeConfig` inherits from mixin (via import); duplicate fields removed | Task 2, Step 2 |
| Verify MRO still works via existing tests (especially `test_pyroscope_standalone_config_accepts_otel_fields`) | Task 2, Steps 3-4 |
| Branch name `fix/des-2-otel-fields-mixin` | Task 1, Step 1 |
| Verification: `just test` + `just lint` clean | Task 2, Steps 4-5 |

All spec items covered. No placeholders. The mixin's name and the import path in `pyroscope_instrument.py` are consistent.

**Deferred:**
- Renaming `OpentelemetryConfig` to `OpenTelemetryConfig` (capital `T`) for capitalization consistency with the new mixin name — out of scope; would be a separate naming-cleanup PR with deprecation aliases.


---

# PR7: Make `BaseInstrument` Generic; Delete Pure-Annotation Subclasses

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the audit's DES-1 finding by deleting the four pure type-annotation framework subclasses that exist solely to narrow `bootstrap_config`. Make `BaseInstrument` generic in its config type so the base instruments can be parameterized (`LoggingInstrument(BaseInstrument[LoggingConfig])`); framework subclasses with real behavior keep their existing structure.

**Architecture revision from the sequencing spec:** The locked decision in the sequencing spec called for "dropping redundant `bootstrap_config:` annotations on kept subclasses." Working through the Python typing implications, this would require a **two-level generic** pattern (each base instrument carries its own bounded `TypeVar` so framework subclasses can re-parameterize). The complexity isn't worth it — the annotations on framework subclasses with real `bootstrap()` overrides are **not** redundant under a single-level-generic design; they provide essential type narrowing for framework-specific field access (e.g., `self.bootstrap_config.application` inside `FastAPICorsInstrument.bootstrap()`).

This plan implements the **simpler single-level-generic approach**: `BaseInstrument` is generic; each base instrument is concretely parameterized; framework subclasses with real bootstrap code keep their `bootstrap_config: FrameworkConfig` annotations. The deletion target remains the same — only the four pure-annotation subclasses go. This delivers the audit's stated goal (eliminating boilerplate) without the two-level-generic complexity.

**Tech Stack:** Python 3.10+ generics (`typing.TypeVar`, `typing.Generic`), frozen dataclasses with `slots=True`.

**Parent spec:** `docs/superpowers/specs/2026-05-31-audit-implementation-sequencing.md` (PR7 section).
**Parent audit:** `docs/superpowers/specs/2026-05-31-bug-refactor-audit.md` (DES-1).

---

## File Structure

12 files modified.

**Instruments (9 files — make each base instrument concretely parameterize the new generic `BaseInstrument`):**
- Modify: `lite_bootstrap/instruments/base.py` — `BaseInstrument` becomes generic `[ConfigT]`.
- Modify: `lite_bootstrap/instruments/cors_instrument.py` — `CorsInstrument(BaseInstrument[CorsConfig])`.
- Modify: `lite_bootstrap/instruments/healthchecks_instrument.py` — `HealthChecksInstrument(BaseInstrument[HealthChecksConfig])`.
- Modify: `lite_bootstrap/instruments/logging_instrument.py` — `LoggingInstrument(BaseInstrument[LoggingConfig])`.
- Modify: `lite_bootstrap/instruments/opentelemetry_instrument.py` — `OpenTelemetryInstrument(BaseInstrument[OpentelemetryConfig])`.
- Modify: `lite_bootstrap/instruments/prometheus_instrument.py` — `PrometheusInstrument(BaseInstrument[PrometheusConfig])`.
- Modify: `lite_bootstrap/instruments/pyroscope_instrument.py` — `PyroscopeInstrument(BaseInstrument[PyroscopeConfig])`.
- Modify: `lite_bootstrap/instruments/sentry_instrument.py` — `SentryInstrument(BaseInstrument[SentryConfig])`.
- Modify: `lite_bootstrap/instruments/swagger_instrument.py` — `SwaggerInstrument(BaseInstrument[SwaggerConfig])`.

In each of the above, the existing `bootstrap_config: <ConfigClass>` field declaration is **removed** — it's now provided by the generic parent.

**Bootstrappers (3 files — delete the 4 pure-annotation subclasses, update `instruments_types` lists to reference base names):**
- Modify: `lite_bootstrap/bootstrappers/fastapi_bootstrapper.py` — delete `FastAPILoggingInstrument` and `FastAPISentryInstrument`; replace their entries in `instruments_types` with `LoggingInstrument` / `SentryInstrument`.
- Modify: `lite_bootstrap/bootstrappers/litestar_bootstrapper.py` — delete `LitestarSentryInstrument`; replace entry with `SentryInstrument`.
- Modify: `lite_bootstrap/bootstrappers/faststream_bootstrapper.py` — delete `FastStreamSentryInstrument`; replace entry with `SentryInstrument`.

The `FreeBootstrapper` already uses the base instrument names directly — no changes needed there.

**Framework subclasses with real bootstrap code stay AS-IS** (their `bootstrap_config: <FrameworkConfig>` annotations are still useful for type narrowing). The list (15 subclasses kept):

- FastAPI: `FastAPICorsInstrument`, `FastAPIHealthChecksInstrument`, `FastAPIOpenTelemetryInstrument`, `FastAPIPrometheusInstrument`, `FastAPISwaggerInstrument`.
- Litestar: `LitestarCorsInstrument`, `LitestarHealthChecksInstrument`, `LitestarLoggingInstrument`, `LitestarOpenTelemetryInstrument`, `LitestarPrometheusInstrument`, `LitestarSwaggerInstrument`.
- FastStream: `FastStreamHealthChecksInstrument`, `FastStreamLoggingInstrument`, `FastStreamOpenTelemetryInstrument`, `FastStreamPrometheusInstrument`.

---

## Locked decisions (revised from sequencing spec)

- **Single-level generic:** `BaseInstrument` is generic; base instruments concretely parameterize. **Revised** from the sequencing spec's two-level approach.
- **Kept framework subclasses retain `bootstrap_config: <FrameworkConfig>` annotations.** **Revised** from "drop redundant annotations." Under single-level-generic, these are not redundant — they provide essential type narrowing for framework field access.
- **Deletions unchanged:** the four pure-annotation subclasses (`FastAPILoggingInstrument`, `FastAPISentryInstrument`, `LitestarSentryInstrument`, `FastStreamSentryInstrument`) still get deleted.
- **Pyroscope handling:** `PyroscopeInstrument` is used as-is across all bootstrappers (no framework subclass). It still gets parameterized as `PyroscopeInstrument(BaseInstrument[PyroscopeConfig])` for symmetry.
- **No new tests.** This is a behavior-preserving refactor; existing tests verify correctness.

---

## Cross-cutting concerns to verify during implementation

1. **Generic + slots + frozen dataclass interaction.** Python 3.10 has historically had subtle issues with `@dataclasses.dataclass(slots=True)` combined with `typing.Generic`. If `just test` or `just lint` (ty check) surfaces errors related to slot conflicts or generic metaclass issues on `BaseInstrument`, fall back to dropping `slots=True` from `BaseInstrument` only. Document the change.

2. **Field declaration removal.** When we remove `bootstrap_config: <ConfigClass>` from each base instrument's body, the dataclass machinery should inherit the parent's `bootstrap_config: ConfigT` declaration. Verify by running `just test` after each instrument file change — any broken instantiation will surface immediately.

3. **`instruments_types` ClassVar typing.** `BaseBootstrapper.instruments_types: typing.ClassVar[list[type[BaseInstrument]]]` — after `BaseInstrument` becomes generic, this becomes `list[type[BaseInstrument[Any]]]` semantically. Should still work because `type[BaseInstrument]` accepts subclasses regardless of parameterization. If `ty check` complains, may need to adjust the annotation.

4. **`abc.ABC` + `typing.Generic`.** `BaseInstrument(abc.ABC, typing.Generic[ConfigT])` requires the MRO to be: BaseInstrument → ABC → Generic → object. Both `abc.ABC` and `typing.Generic` are designed to work together, but verify the order doesn't break dataclass machinery.

---

## Task 1: Create branch

**Files:** (no files; git only)

- [ ] **Step 1: Branch off `main`**

```bash
git checkout main
git pull --ff-only origin main
git checkout -b refactor/des-1-generic-instruments
```

Expected: `Switched to a new branch 'refactor/des-1-generic-instruments'`.

This is the only PR in the sequence that uses the `refactor/` branch prefix (not `fix/`), because it's the only one that's a pure refactor with no fix component.

---

## Task 2: Make `BaseInstrument` generic

**File:** `lite_bootstrap/instruments/base.py`

- [ ] **Step 1: Add the `ConfigT` TypeVar and parameterize `BaseInstrument`**

Current (lines 1-46):

```python
import abc
import dataclasses
import typing

import typing_extensions


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class BaseConfig:
    ...


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class BaseInstrument(abc.ABC):
    bootstrap_config: BaseConfig
    not_ready_message = ""
    missing_dependency_message = ""

    def bootstrap(self) -> None: ...  # noqa: B027

    def teardown(self) -> None: ...  # noqa: B027

    def is_ready(self) -> bool:
        return True

    @staticmethod
    def check_dependencies() -> bool:
        return True
```

Replace the `BaseInstrument` block (lines 30-45) with:

```python
ConfigT = typing.TypeVar("ConfigT", bound=BaseConfig)


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class BaseInstrument(abc.ABC, typing.Generic[ConfigT]):
    bootstrap_config: ConfigT
    not_ready_message = ""
    missing_dependency_message = ""

    def bootstrap(self) -> None: ...  # noqa: B027

    def teardown(self) -> None: ...  # noqa: B027

    def is_ready(self) -> bool:
        return True

    @staticmethod
    def check_dependencies() -> bool:
        return True
```

Two changes:
1. Add `ConfigT = typing.TypeVar("ConfigT", bound=BaseConfig)` between the two dataclasses.
2. `BaseInstrument` now inherits from `abc.ABC, typing.Generic[ConfigT]`; the `bootstrap_config` field type changes from `BaseConfig` to `ConfigT`.

- [ ] **Step 2: Quick smoke check**

```bash
just test -- tests/test_free_bootstrap.py -v
```

Expected: PASS. The `FreeBootstrapper` uses the base instruments directly with `FreeBootstrapperConfig`; if generic+slots+frozen has an issue, this test surfaces it first.

If this test fails with a slots/generic-related error, fall back to dropping `slots=True` from `BaseInstrument`:

```python
@dataclasses.dataclass(kw_only=True, frozen=True)
class BaseInstrument(abc.ABC, typing.Generic[ConfigT]):
    ...
```

Re-run the test. Note the change in the eventual commit message if so.

---

## Task 3: Parameterize each base instrument

For each instrument file, change the class signature from `class XInstrument(BaseInstrument):` to `class XInstrument(BaseInstrument[XConfig]):` and remove the redundant `bootstrap_config: XConfig` field declaration from the class body.

### Step 1: `lite_bootstrap/instruments/cors_instrument.py`

Current (around lines 17-25):

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class CorsInstrument(BaseInstrument):
    bootstrap_config: CorsConfig
    not_ready_message = "cors_allowed_origins or cors_allowed_origin_regex must be provided"

    def is_ready(self) -> bool:
        return bool(self.bootstrap_config.cors_allowed_origins) or bool(
            self.bootstrap_config.cors_allowed_origin_regex,
        )
```

Replace with:

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class CorsInstrument(BaseInstrument[CorsConfig]):
    not_ready_message = "cors_allowed_origins or cors_allowed_origin_regex must be provided"

    def is_ready(self) -> bool:
        return bool(self.bootstrap_config.cors_allowed_origins) or bool(
            self.bootstrap_config.cors_allowed_origin_regex,
        )
```

Single change: parameterize the base, drop the redundant `bootstrap_config: CorsConfig` field.

### Step 2: `lite_bootstrap/instruments/healthchecks_instrument.py`

Current (around lines 29-38):

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class HealthChecksInstrument(BaseInstrument):
    bootstrap_config: HealthChecksConfig
    not_ready_message = "health_checks_enabled is False"

    def is_ready(self) -> bool:
        return self.bootstrap_config.health_checks_enabled

    def render_health_check_data(self) -> HealthCheckTypedDict:
        return self.bootstrap_config.health_check_data
```

Replace with:

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class HealthChecksInstrument(BaseInstrument[HealthChecksConfig]):
    not_ready_message = "health_checks_enabled is False"

    def is_ready(self) -> bool:
        return self.bootstrap_config.health_checks_enabled

    def render_health_check_data(self) -> HealthCheckTypedDict:
        return self.bootstrap_config.health_check_data
```

### Step 3: `lite_bootstrap/instruments/logging_instrument.py`

Current (around lines 117-145):

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class LoggingInstrument(BaseInstrument):
    bootstrap_config: LoggingConfig
    not_ready_message = "logging_enabled is False"
    missing_dependency_message = "structlog is not installed"
    _logger_factory: "MemoryLoggerFactory | None" = dataclasses.field(
        default_factory=lambda: None, init=False, repr=False, compare=False
    )
    ...
```

Change only the class signature and remove the `bootstrap_config: LoggingConfig` line:

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class LoggingInstrument(BaseInstrument[LoggingConfig]):
    not_ready_message = "logging_enabled is False"
    missing_dependency_message = "structlog is not installed"
    _logger_factory: "MemoryLoggerFactory | None" = dataclasses.field(
        default_factory=lambda: None, init=False, repr=False, compare=False
    )
    ...
```

Everything below the field declarations stays unchanged.

### Step 4: `lite_bootstrap/instruments/opentelemetry_instrument.py`

Current (around lines 80-90):

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class OpenTelemetryInstrument(BaseInstrument):
    bootstrap_config: OpentelemetryConfig
    not_ready_message = "opentelemetry_endpoint is empty and opentelemetry_log_traces is False"
    missing_dependency_message = "opentelemetry is not installed"
    _tracer_provider: "TracerProvider | None" = dataclasses.field(
        default_factory=lambda: None, init=False, repr=False, compare=False
    )
    ...
```

Replace the class signature and drop `bootstrap_config: OpentelemetryConfig`:

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class OpenTelemetryInstrument(BaseInstrument[OpentelemetryConfig]):
    not_ready_message = "opentelemetry_endpoint is empty and opentelemetry_log_traces is False"
    missing_dependency_message = "opentelemetry is not installed"
    _tracer_provider: "TracerProvider | None" = dataclasses.field(
        default_factory=lambda: None, init=False, repr=False, compare=False
    )
    ...
```

Rest of the class unchanged.

### Step 5: `lite_bootstrap/instruments/prometheus_instrument.py`

Current (around lines 13-21):

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class PrometheusInstrument(BaseInstrument):
    bootstrap_config: PrometheusConfig
    not_ready_message = "prometheus_metrics_path is empty or not valid"

    def is_ready(self) -> bool:
        return bool(self.bootstrap_config.prometheus_metrics_path) and is_valid_path(
            self.bootstrap_config.prometheus_metrics_path
        )
```

Replace with:

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class PrometheusInstrument(BaseInstrument[PrometheusConfig]):
    not_ready_message = "prometheus_metrics_path is empty or not valid"

    def is_ready(self) -> bool:
        return bool(self.bootstrap_config.prometheus_metrics_path) and is_valid_path(
            self.bootstrap_config.prometheus_metrics_path
        )
```

### Step 6: `lite_bootstrap/instruments/pyroscope_instrument.py`

Current (around lines 21-46, after PR6's mixin landed):

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class PyroscopeInstrument(BaseInstrument):
    bootstrap_config: PyroscopeConfig
    not_ready_message = "pyroscope_endpoint is empty"
    missing_dependency_message = "pyroscope is not installed"

    def is_ready(self) -> bool:
        return bool(self.bootstrap_config.pyroscope_endpoint)
    ...
```

Replace class signature and drop the field:

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class PyroscopeInstrument(BaseInstrument[PyroscopeConfig]):
    not_ready_message = "pyroscope_endpoint is empty"
    missing_dependency_message = "pyroscope is not installed"

    def is_ready(self) -> bool:
        return bool(self.bootstrap_config.pyroscope_endpoint)
    ...
```

Rest unchanged.

### Step 7: `lite_bootstrap/instruments/sentry_instrument.py`

Current (around lines 94-105):

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class SentryInstrument(BaseInstrument):
    bootstrap_config: SentryConfig
    not_ready_message = "sentry_dsn is empty"
    missing_dependency_message = "sentry_sdk is not installed"

    def is_ready(self) -> bool:
        return bool(self.bootstrap_config.sentry_dsn)
    ...
```

Replace:

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class SentryInstrument(BaseInstrument[SentryConfig]):
    not_ready_message = "sentry_dsn is empty"
    missing_dependency_message = "sentry_sdk is not installed"

    def is_ready(self) -> bool:
        return bool(self.bootstrap_config.sentry_dsn)
    ...
```

### Step 8: `lite_bootstrap/instruments/swagger_instrument.py`

Current (around lines 13-16):

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class SwaggerInstrument(BaseInstrument):
    bootstrap_config: SwaggerConfig
```

Replace with:

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class SwaggerInstrument(BaseInstrument[SwaggerConfig]):
    pass
```

The body becomes empty — replace with `pass`. This is the smallest instrument class.

### Step 9: Intermediate verification

After all nine instrument files are updated:

```bash
just test -- tests/instruments/ -v
just test -- tests/test_free_bootstrap.py -v
```

Expected: all pass. The instrument-level tests + the free-bootstrapper test exercise every base instrument directly. If any fail, debug before moving to Task 4.

---

## Task 4: Delete the four pure-annotation framework subclasses

### Step 1: `lite_bootstrap/bootstrappers/fastapi_bootstrapper.py`

Locate `FastAPILoggingInstrument` (around lines 111-113):

```python
@dataclasses.dataclass(kw_only=True, frozen=True)
class FastAPILoggingInstrument(LoggingInstrument):
    bootstrap_config: FastAPIConfig
```

Delete the entire block.

Locate `FastAPISentryInstrument` (around lines 141-143):

```python
@dataclasses.dataclass(kw_only=True, frozen=True)
class FastAPISentryInstrument(SentryInstrument):
    bootstrap_config: FastAPIConfig
```

Delete the entire block.

In `FastAPIBootstrapper.instruments_types`:

```python
    instruments_types: typing.ClassVar = [
        FastAPICorsInstrument,
        FastAPIOpenTelemetryInstrument,
        PyroscopeInstrument,
        FastAPISentryInstrument,         # ← replace with SentryInstrument
        FastAPIHealthChecksInstrument,
        FastAPILoggingInstrument,        # ← replace with LoggingInstrument
        FastAPIPrometheusInstrument,
        FastAPISwaggerInstrument,
    ]
```

Replace `FastAPISentryInstrument` with `SentryInstrument` and `FastAPILoggingInstrument` with `LoggingInstrument`.

### Step 2: `lite_bootstrap/bootstrappers/litestar_bootstrapper.py`

Locate `LitestarSentryInstrument` (around lines 199-201):

```python
@dataclasses.dataclass(kw_only=True, frozen=True)
class LitestarSentryInstrument(SentryInstrument):
    bootstrap_config: LitestarConfig
```

Delete the entire block.

In `LitestarBootstrapper.instruments_types`, replace `LitestarSentryInstrument` with `SentryInstrument`.

### Step 3: `lite_bootstrap/bootstrappers/faststream_bootstrapper.py`

Locate `FastStreamSentryInstrument` (around lines 135-137):

```python
@dataclasses.dataclass(kw_only=True, frozen=True)
class FastStreamSentryInstrument(SentryInstrument):
    bootstrap_config: FastStreamConfig
```

Delete the entire block.

In `FastStreamBootstrapper.instruments_types`, replace `FastStreamSentryInstrument` with `SentryInstrument`.

### Step 4: Verify imports

After the deletions, the framework bootstrappers no longer reference the deleted classes by name. Any imports of `FastAPILoggingInstrument` / `FastAPISentryInstrument` / `LitestarSentryInstrument` / `FastStreamSentryInstrument` from other test files or modules would break.

Run a sanity grep:

```bash
grep -rn "FastAPILoggingInstrument\|FastAPISentryInstrument\|LitestarSentryInstrument\|FastStreamSentryInstrument" .
```

Expected: only matches in the plan/spec docs (which describe the deletion). Zero matches in `lite_bootstrap/` or `tests/`. If any test file imports a deleted class, update it to use the base class name.

---

## Task 5: Verify and commit

- [ ] **Step 1: Run the full test suite**

```bash
just test
```

Expected: 89/89 pass. No behavior change should result from this refactor.

If any framework integration test (`test_fastapi_bootstrap`, `test_litestar_bootstrap`, `test_faststream_bootstrap`) fails, the most likely cause is type-narrowing surprise on a framework subclass that needs to access framework-specific config fields. Verify the kept framework subclasses still declare `bootstrap_config: <FrameworkConfig>` where they override `bootstrap()`.

- [ ] **Step 2: Run lint**

```bash
just lint
```

Expected: clean. Watch for:

- F401 unused-import warnings — possible if a bootstrapper imports something it no longer uses after the deletions.
- `ty check` complaints about the new generic parameterization — should be silent, but if not, narrow the issue and address.

- [ ] **Step 3: Sanity-check the diff**

```bash
git diff --stat
```

Expected: 12 files changed. Approximate line counts (rough):
- `base.py`: +4 / -1 (TypeVar + Generic + bootstrap_config type)
- 8 instrument files: roughly -1 line each (drop the redundant field declaration)
- 3 bootstrapper files: ~-3 lines per deleted subclass + 1-2 line changes in `instruments_types`

Total net: roughly -10 to -20 lines.

- [ ] **Step 4: Commit**

Stage exactly the 12 modified files:

```bash
git add \
  lite_bootstrap/instruments/base.py \
  lite_bootstrap/instruments/cors_instrument.py \
  lite_bootstrap/instruments/healthchecks_instrument.py \
  lite_bootstrap/instruments/logging_instrument.py \
  lite_bootstrap/instruments/opentelemetry_instrument.py \
  lite_bootstrap/instruments/prometheus_instrument.py \
  lite_bootstrap/instruments/pyroscope_instrument.py \
  lite_bootstrap/instruments/sentry_instrument.py \
  lite_bootstrap/instruments/swagger_instrument.py \
  lite_bootstrap/bootstrappers/fastapi_bootstrapper.py \
  lite_bootstrap/bootstrappers/litestar_bootstrapper.py \
  lite_bootstrap/bootstrappers/faststream_bootstrapper.py
git commit -m "$(cat <<'EOF'
refactor: make BaseInstrument generic; delete pure-annotation subclasses

Closes DES-1: the four pure type-annotation framework subclasses
(FastAPILoggingInstrument, FastAPISentryInstrument, LitestarSentryInstrument,
FastStreamSentryInstrument) existed only to narrow bootstrap_config. They
contributed no behavior.

Make BaseInstrument generic in ConfigT (TypeVar bound to BaseConfig).
Each base instrument concretely parameterizes the generic
(LoggingInstrument(BaseInstrument[LoggingConfig]), etc.) and drops its
own redundant bootstrap_config field declaration — the type is now
provided by the parent's generic parameter.

Delete the four pure-annotation framework subclasses. In the three
affected bootstrappers' instruments_types lists, replace the deleted
class references with the base names (SentryInstrument, LoggingInstrument).

Framework subclasses that override bootstrap() with real framework-specific
logic (FastAPICorsInstrument, LitestarLoggingInstrument, etc. — 15 in
total) keep their existing structure including the bootstrap_config:
<FrameworkConfig> annotation. These annotations are NOT redundant under
the single-level-generic design adopted here — they provide essential
type narrowing for framework field access (e.g.,
self.bootstrap_config.application inside FastAPICorsInstrument.bootstrap).

This deviates from the sequencing spec's "drop redundant annotations
on kept subclasses" decision: a two-level-generic design would be needed
to make those annotations truly redundant, and the complexity isn't
worth it. The audit's stated goal (eliminate the pure-annotation
boilerplate) is fully addressed regardless.

No behavior change. Existing tests verify correctness.

Closes DES-1 from the audit.
EOF
)"
```

---

## Task 6: Push and open PR

- [ ] **Step 1: Push the branch**

```bash
git push -u origin refactor/des-1-generic-instruments
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --title "refactor: make BaseInstrument generic; delete pure-annotation subclasses" --body "$(cat <<'EOF'
## Summary
Closes DES-1 from an internal audit: the four pure type-annotation framework subclasses (`FastAPILoggingInstrument`, `FastAPISentryInstrument`, `LitestarSentryInstrument`, `FastStreamSentryInstrument`) existed only to narrow `bootstrap_config`. They contributed no behavior.

- `BaseInstrument` is now generic in `ConfigT` (`TypeVar` bound to `BaseConfig`).
- Each base instrument concretely parameterizes the generic (`LoggingInstrument(BaseInstrument[LoggingConfig])`, etc.) and drops its redundant `bootstrap_config` field declaration — the type is provided by the parent.
- The four pure-annotation framework subclasses are deleted. The three affected bootstrappers' `instruments_types` lists now reference the base names directly (`SentryInstrument`, `LoggingInstrument`).
- Framework subclasses that override `bootstrap()` with framework-specific logic (15 in total) keep their existing structure.

No behavior change. Existing tests verify correctness.

## Deviation from sequencing spec
The sequencing spec called for "dropping redundant `bootstrap_config:` annotations on kept subclasses." Under a single-level-generic design those annotations are NOT redundant — they provide essential type narrowing for framework field access (e.g. `self.bootstrap_config.application` in `FastAPICorsInstrument.bootstrap()`). Making them truly redundant would require a two-level-generic design (each base instrument with its own bounded `TypeVar`); the complexity isn't worth the marginal cleanup. The audit's stated goal — eliminating the pure-annotation boilerplate — is fully addressed regardless.

## Test plan
- [x] `just test` — full suite passes (89/89).
- [x] `just lint` — clean.
- [ ] Reviewer: confirm the generic + slots + frozen dataclass combination works on Python 3.10. If `BaseInstrument`'s `slots=True` had to be dropped during implementation, the commit message will note it.
- [ ] Reviewer: confirm the kept framework subclasses (`FastAPICorsInstrument`, `LitestarLoggingInstrument`, etc.) still access framework-specific config fields correctly.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review

**Spec coverage check** against the sequencing spec (PR7 section) and audit (DES-1):

| Spec item | Task |
|-----------|------|
| `BaseInstrument` becomes generic in `ConfigT` (bound to `BaseConfig`) | Task 2, Step 1 |
| Each base instrument concretely parameterizes | Task 3, Steps 1-8 |
| Each base instrument drops its redundant `bootstrap_config:` field declaration | Task 3, Steps 1-8 |
| Delete `FastAPILoggingInstrument` | Task 4, Step 1 |
| Delete `FastAPISentryInstrument` | Task 4, Step 1 |
| Delete `LitestarSentryInstrument` | Task 4, Step 2 |
| Delete `FastStreamSentryInstrument` | Task 4, Step 3 |
| Update `FastAPIBootstrapper.instruments_types` to reference base names | Task 4, Step 1 |
| Update `LitestarBootstrapper.instruments_types` | Task 4, Step 2 |
| Update `FastStreamBootstrapper.instruments_types` | Task 4, Step 3 |
| Branch name `refactor/des-1-generic-instruments` | Task 1, Step 1 |
| Verification: `just test` + `just lint` clean | Task 5, Steps 1-2 |

**Deviations from sequencing spec (documented in commit and PR body):**
- Single-level generic rather than two-level.
- Kept framework subclasses retain their `bootstrap_config:` annotations.

**Deferred:**
- REF-1 (`_build_excluded_urls` duplication between FastAPI and Litestar OTel instruments) — fold into a quick PR8 if PR7's diff stays manageable; otherwise separate follow-up.
- REF-2 (dead defensive check in `LitestarLoggingInstrument.bootstrap()`) — same.
- REF-5 (collapse near-empty `swagger_instrument.py` and `prometheus_instrument.py` base files) — out of scope.

These three are explicitly noted in the sequencing spec as follow-ups to PR7. Decide once PR7's actual diff lands whether to bundle them or split.
