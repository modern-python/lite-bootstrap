---
status: shipped
date: 2026-06-24
slug: unify-teardown-attach
spec: unify-teardown-attach
pr: 130
---

# unify-teardown-attach — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps
> use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the teardown-on-shutdown guard into one
`BaseBootstrapper._attach_teardown_once`, route all four app-bearing
bootstrappers through it, and extend the double-attach warning uniformly to
Litestar and FastStream.

**Spec:** [`design.md`](./design.md)

**Branch:** `feat/unify-teardown-attach`

**Commit strategy:** Per-task commits (each task leaves the suite green).

TDD throughout: failing test first, watch it fail for the right reason, then
implement to green. Each task ends green at 100% coverage.

---

### Task 1: `_attach_teardown_once` seam on `BaseBootstrapper` (red → green)

**Files:**
- Modify: `lite_bootstrap/bootstrappers/base.py`
- Modify: `tests/test_free_bootstrap.py` (de-facto base-behavior test surface)

Add the guarded seam and unit-test it directly against a dummy target. No
bootstrapper is rewired yet, so the existing suite stays green.

- [ ] **Step 1: Write the direct seam test, red.**

  On a `FreeBootstrapper` instance, call the inherited
  `_attach_teardown_once(target, spy)` with `target = types.SimpleNamespace()`:
  - first call runs `spy` exactly once and sets `getattr(target, marker)` truthy
  - second call emits `UserWarning` (match `"already has a lite-bootstrap teardown hook"`)
    and does **not** run `spy` again

  Run `just test -- -k attach_teardown_once` → fails (method does not exist).

- [ ] **Step 2: Implement `_attach_teardown_once` + `_TEARDOWN_MARKER`.**

  Add the method and the `_TEARDOWN_MARKER` class constant per the spec
  (getattr → warn+skip, else setattr + `attach()`), `stacklevel=3`, warning noun
  from `type(self).__name__`.

  Run `just test -- -k attach_teardown_once` → green.

- [ ] **Step 3: Commit.**

  ```bash
  git add lite_bootstrap/bootstrappers/base.py tests/test_free_bootstrap.py
  git commit -m "feat: add BaseBootstrapper._attach_teardown_once guarded seam

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 2: Route FastAPI + FastMCP through the seam

**Files:**
- Modify: `lite_bootstrap/bootstrappers/fastapi_bootstrapper.py`
- Modify: `lite_bootstrap/bootstrappers/fastmcp_bootstrapper.py`
- Modify: `tests/test_fastapi_bootstrap.py`, `tests/test_fastmcp_bootstrap.py`

Migrate the two already-guarded bootstrappers; behavior preserved (warn + skip),
detection unified to the marker.

- [ ] **Step 1: Update the existing double-attach tests to the unified wording.**

  In `test_fastapi_bootstrap.py:130` and `test_fastmcp_bootstrap.py:283`, change
  the warning `match`/substring to `"already has a lite-bootstrap teardown hook"`.
  Keep the attach-once assertions (FastAPI lifespan not re-wrapped; FastMCP single
  `_TeardownProvider`). Run those tests → red (old wording gone once impl changes).

- [ ] **Step 2: Migrate FastAPI.**

  Replace the inline marker-check/wrap in `__init__` with
  `self._attach_teardown_once(application, lambda: self._wrap_lifespan(application))`;
  move the `_merge_lifespan_context` body into `_wrap_lifespan` (or inline lambda).
  Remove the old `_lite_bootstrap_lifespan_attached` get/set.

- [ ] **Step 3: Migrate FastMCP.**

  Replace the structural `isinstance(p, _TeardownProvider)` guard in `__init__`
  with `self._attach_teardown_once(app, lambda: app.add_provider(_TeardownProvider(self.teardown)))`.
  Keep the `_TeardownProvider` class (attach mechanism).

  Run `just test -- -k "fastapi or fastmcp"` → green. Confirm
  `test_fastmcp_bootstrap.py:61` (ASGI-lifespan teardown) still passes.

- [ ] **Step 4: Commit.**

  ```bash
  git add lite_bootstrap/bootstrappers/fastapi_bootstrapper.py \
          lite_bootstrap/bootstrappers/fastmcp_bootstrapper.py \
          tests/test_fastapi_bootstrap.py tests/test_fastmcp_bootstrap.py
  git commit -m "refactor: route FastAPI + FastMCP teardown attach through the seam

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 3: Extend the guard to Litestar + FastStream (red → green)

**Files:**
- Modify: `lite_bootstrap/bootstrappers/litestar_bootstrapper.py`
- Modify: `lite_bootstrap/bootstrappers/faststream_bootstrapper.py`
- Modify: `tests/test_litestar_bootstrap.py`, `tests/test_faststream_bootstrap.py`

New behavior: these two gain the double-attach guard.

- [ ] **Step 1: Write the new double-attach tests, red.**

  - Litestar: construct two `LitestarBootstrapper`s on the same `LitestarConfig`
    (shared `application_config`); assert the second warns
    (`"already has a lite-bootstrap teardown hook"`) and
    `len(application_config.on_shutdown)` increased by exactly 1 total.
  - FastStream: construct two `FastStreamBootstrapper`s on the same app; assert the
    second warns.

  Run those tests → fail (no guard yet; no warning emitted).

- [ ] **Step 2: Route Litestar + FastStream through the seam.**

  Litestar `__init__`: keep the `application_config.debug = ...` line, replace the
  bare `on_shutdown.append` with
  `self._attach_teardown_once(application_config, lambda: application_config.on_shutdown.append(self.teardown))`.
  FastStream `__init__`: replace the bare `on_shutdown(self.teardown)` with
  `self._attach_teardown_once(application, lambda: application.on_shutdown(self.teardown))`.

  Run `just test -- -k "litestar or faststream"` → green.

- [ ] **Step 3: Commit.**

  ```bash
  git add lite_bootstrap/bootstrappers/litestar_bootstrapper.py \
          lite_bootstrap/bootstrappers/faststream_bootstrapper.py \
          tests/test_litestar_bootstrap.py tests/test_faststream_bootstrap.py
  git commit -m "feat: extend teardown double-attach guard to Litestar + FastStream

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 4: Ship-time docs + index

**Files:**
- Modify: `architecture/bootstrappers.md`
- Modify: `CLAUDE.md`
- Modify: `planning/changes/2026-06-24.01-unify-teardown-attach/design.md` (frontmatter)

- [ ] **Step 1: Update `architecture/bootstrappers.md`.**

  In the teardown section (§42) and the app-tagging sentinel section (§68): name
  the unified `_attach_teardown_once` seam, the `_lite_bootstrap_teardown_attached`
  marker (rename from `_lite_bootstrap_lifespan_attached`), and that the
  double-attach guard now applies uniformly to all four app-bearing frameworks.

- [ ] **Step 2: Update `CLAUDE.md`.**

  Update the `_lite_bootstrap_*` convention bullet: the marker is now
  `_lite_bootstrap_teardown_attached`, set once via the shared
  `BaseBootstrapper._attach_teardown_once`, uniform across FastAPI/Litestar/
  FastStream/FastMCP.

- [ ] **Step 3: Fill design frontmatter + regenerate index.**

  Set `summary`; set `status` per the merge state (see candidate-1 precedent:
  `approved` until a PR exists, `shipped` + `pr` at PR time). Run `just index`.

- [ ] **Step 4: Final verification.**

  `just lint-ci` clean (incl. `ty`), `just test` green at 100%.

- [ ] **Step 5: Commit.**

  ```bash
  git add architecture/bootstrappers.md CLAUDE.md \
          planning/changes/2026-06-24.01-unify-teardown-attach/ planning/
  git commit -m "docs: record unified teardown-attach seam in architecture + CLAUDE

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```
