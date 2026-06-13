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
