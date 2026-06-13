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
