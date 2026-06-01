# PR8: Sentry Micro-Fixes (LOW-1 + LOW-2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two small idiom/typing fixes in `sentry_instrument.py`:
- LOW-1: Replace `if not callback:` (sloppy callable truthiness check) with `if callback is None:` in `wrap_before_send_callbacks`.
- LOW-2: Replace `SentryConfig.sentry_before_send`'s degenerate `Callable[[Any, Any], Any | None] | None` annotation with the proper `sentry_types.EventProcessor | None`.

Both are tiny; no behavior change.

**Architecture:** Single-file edit. Two unrelated micro-fixes bundled because both touch the same module and reviewing them separately would cost more than reviewing them together.

**Tech Stack:** Python 3.10+, sentry_sdk types (`sentry_sdk._types.EventProcessor`).

**Parent spec:** `docs/superpowers/specs/2026-06-01-deferred-refactors-sequencing.md` (PR8 section).
**Parent audit:** `docs/superpowers/specs/2026-05-31-bug-refactor-audit.md` (LOW-1, LOW-2).

---

## File Structure

One file modified.

- Modify: `lite_bootstrap/instruments/sentry_instrument.py` — two changes (lines 36 and 81-82).

---

## Locked decisions

- **No new tests.** Existing Sentry tests (`tests/instruments/test_sentry_instrument.py`) cover the affected code paths. LOW-1 is an idiom change with identical runtime behavior for the only realistic input (callables and `None`); LOW-2 is type-only.

---

## Task 1: Create branch

**Files:** (no files; git only)

- [ ] **Step 1: Branch off `main`**

```bash
git checkout main
git pull --ff-only origin main
git checkout -b fix/low-1-2-sentry-micro
```

Expected: `Switched to a new branch 'fix/low-1-2-sentry-micro'`.

---

## Task 2: Apply two micro-fixes, verify, commit

### Step 1: Fix LOW-2 (`sentry_before_send` typing)

**File:** `lite_bootstrap/instruments/sentry_instrument.py:36`

Current line:

```python
    sentry_before_send: typing.Callable[[typing.Any, typing.Any], typing.Any | None] | None = None
```

This annotation is degenerate: `typing.Any | None` collapses to `typing.Any` (since `Any` is the top type for type-checking purposes), so the outer `| None` is the only meaningful nullability. Functionally the annotation reduces to `Callable[..., Any] | None`.

The file already imports the proper type under `TYPE_CHECKING` at lines 10-12:

```python
if typing.TYPE_CHECKING:
    from sentry_sdk import _types as sentry_types
    from sentry_sdk.integrations import Integration
```

And `wrap_before_send_callbacks` (later in the same file) already uses `"sentry_types.EventProcessor"` in its own signature:

```python
def wrap_before_send_callbacks(
    *callbacks: typing.Optional["sentry_types.EventProcessor"],
) -> "sentry_types.EventProcessor":
```

So `sentry_types.EventProcessor` is already in scope. Replace line 36 with:

```python
    sentry_before_send: "sentry_types.EventProcessor | None" = None
```

The string annotation form avoids a `NameError` at runtime when `sentry_sdk` isn't installed (since `sentry_types` lives under the `TYPE_CHECKING` block).

### Step 2: Fix LOW-1 (`if not callback:` → `if callback is None:`)

**File:** `lite_bootstrap/instruments/sentry_instrument.py:80-82`

Current code:

```python
    def run_before_send(
        event: "sentry_types.Event", hint: "sentry_types.Hint"
    ) -> typing.Optional["sentry_types.Event"]:
        for callback in callbacks:
            if not callback:
                continue

            temp_event = callback(event, hint)
            ...
```

The `if not callback:` is checking truthiness, but Python callables are always truthy unless they define a custom `__bool__`. The intent is clearly "skip None entries." Replace `if not callback:` with `if callback is None:` to match the intent:

```python
    def run_before_send(
        event: "sentry_types.Event", hint: "sentry_types.Hint"
    ) -> typing.Optional["sentry_types.Event"]:
        for callback in callbacks:
            if callback is None:
                continue

            temp_event = callback(event, hint)
            ...
```

Only the conditional changes; the rest of the function is unchanged.

### Step 3: Run the Sentry test file

```bash
just test -- tests/instruments/test_sentry_instrument.py -v
```

Expected: all tests PASS. The existing tests cover both `enrich_sentry_event_from_structlog_log` (which goes through `wrap_before_send_callbacks`) and the `SentryInstrument.bootstrap()` path that uses `sentry_before_send`.

### Step 4: Run the full test suite

```bash
just test
```

Expected: 89/89 (or whatever the current count is after PR7 — should be 89). No behavior change should affect any test.

### Step 5: Run lint

```bash
just lint
```

Expected: clean. The `# ty: ignore` removal opportunity (if the original line had one — check during implementation) should also clear without warnings.

### Step 6: Commit

Stage the single modified file:

```bash
git add lite_bootstrap/instruments/sentry_instrument.py
git commit -m "$(cat <<'EOF'
fix: tighten Sentry idiom and typing micro-issues

LOW-1: wrap_before_send_callbacks used `if not callback:` to skip None
entries in *callbacks. Callables are always truthy unless they define
__bool__, so the truthiness check is semantically wrong even if it
happens to work. Use `if callback is None:` to match the intent.

LOW-2: SentryConfig.sentry_before_send was annotated
`Callable[[Any, Any], Any | None] | None`. The inner `Any | None`
collapses to `Any`, so the annotation reduces to
`Callable[..., Any] | None` — the union adds nothing. Use the proper
`sentry_types.EventProcessor | None` instead (already imported under
TYPE_CHECKING in the same file).

No behavior change.

Closes LOW-1 and LOW-2 from the audit.
EOF
)"
```

---

## Task 3: Push and open PR

- [ ] **Step 1: Push the branch**

```bash
git push -u origin fix/low-1-2-sentry-micro
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --title "fix: tighten Sentry idiom and typing micro-issues" --body "$(cat <<'EOF'
## Summary
Two micro-fixes in \`sentry_instrument.py\`:

- **LOW-1:** \`wrap_before_send_callbacks\` used \`if not callback:\` to skip \`None\` entries. Callables are always truthy unless they define \`__bool__\`, so the truthiness check is semantically wrong (happens to work, but obscures the intent). Use \`if callback is None:\` instead.
- **LOW-2:** \`SentryConfig.sentry_before_send\` was annotated \`Callable[[Any, Any], Any | None] | None\`. The inner \`Any | None\` collapses to \`Any\`, so the annotation reduces to \`Callable[..., Any] | None\` — the union adds nothing. Use the proper \`sentry_types.EventProcessor | None\` (already imported under \`TYPE_CHECKING\` in the same file).

No behavior change. No new tests — existing Sentry tests cover both paths.

Closes LOW-1 and LOW-2 from an internal audit.

## Test plan
- [x] \`just test -- tests/instruments/test_sentry_instrument.py -v\` — pass.
- [x] \`just test\` — full suite passes.
- [x] \`just lint\` — clean.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review

**Spec coverage check** against the sequencing spec (PR8 section) and audit (LOW-1, LOW-2):

| Spec item | Task |
|-----------|------|
| LOW-1: `if not callback:` → `if callback is None:` | Task 2, Step 2 |
| LOW-2: `sentry_before_send` typing → `sentry_types.EventProcessor \| None` | Task 2, Step 1 |
| Branch name `fix/low-1-2-sentry-micro` | Task 1, Step 1 |
| Verification: `just test` + `just lint` clean | Task 2, Steps 3-5 |
| Single-file diff | Task 2, Step 6 |

All spec items covered. No placeholders. Smallest PR in the deferred-refactors sequence; both edits are pre-existing patterns already used elsewhere in the same file (string-quoted forward reference for the type; explicit `is None` checks in other modules).
