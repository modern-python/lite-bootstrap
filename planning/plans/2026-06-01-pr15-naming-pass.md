# PR15: Naming Pass — `Opentelemetry`→`OpenTelemetry` + `FreeBootstrapperConfig`→`FreeConfig`

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The final PR of the deferred-refactors sequence. Two API-surface renames with silent backward-compatibility aliases.

- **Bonus (Otel capitalization)**: `OpentelemetryConfig` → `OpenTelemetryConfig` to match `OpenTelemetryServiceFieldsConfig` (introduced in PR6) and conventional OpenTelemetry capitalization.
- **LOW-7**: `FreeBootstrapperConfig` → `FreeConfig` for consistency with sibling configs (`FastAPIConfig`, `LitestarConfig`, `FastStreamConfig` — none carry the `Bootstrapper` infix).

Backward compat: silent aliases (`OpentelemetryConfig = OpenTelemetryConfig`, `FreeBootstrapperConfig = FreeConfig`) at module level plus a `FreeBootstrapperConfig` re-export in `lite_bootstrap/__init__.py`. Existing user code that imports the old names continues to work unchanged.

**Architecture:** Mechanical renames across 11 files (7 production + 4 test). The aliases are simple assignments — same class object, so `isinstance(x, OldName)` and `isinstance(x, NewName)` are interchangeable.

**Tech Stack:** Python 3.10+ dataclasses, module-level aliases.

**Parent spec:** `docs/superpowers/specs/2026-06-01-deferred-refactors-sequencing.md` (PR15 section).
**Parent audit:** `docs/superpowers/specs/2026-05-31-bug-refactor-audit.md` (LOW-7).

---

## File Structure

11 files modified, no new files.

**Production (7 files):**
- `lite_bootstrap/instruments/opentelemetry_instrument.py` — rename `OpentelemetryConfig` → `OpenTelemetryConfig`; add silent alias.
- `lite_bootstrap/bootstrappers/free_bootstrapper.py` — rename `FreeBootstrapperConfig` → `FreeConfig`; add silent alias; update internal references.
- `lite_bootstrap/bootstrappers/fastapi_bootstrapper.py` — update import and inheritance to `OpenTelemetryConfig`.
- `lite_bootstrap/bootstrappers/litestar_bootstrapper.py` — same.
- `lite_bootstrap/bootstrappers/faststream_bootstrapper.py` — same.
- `lite_bootstrap/__init__.py` — export both `FreeConfig` (canonical) and `FreeBootstrapperConfig` (alias) in `__all__`.

**Tests (4 files):**
- `tests/test_free_bootstrap.py` — update internal usages to `FreeConfig`.
- `tests/instruments/test_opentelemetry_instrument.py` — update usages to `OpenTelemetryConfig`.
- `tests/instruments/test_logging_instrument.py` — update usages to `OpenTelemetryConfig`.
- `tests/instruments/test_pyroscope_instrument.py` — update usages to `FreeConfig`.

---

## Locked decisions (from sequencing spec, Q2 + Q7)

- **Silent aliases** (no warn-on-access). Library is small; warn-on-access is overkill for two renames.
- **Both names in `__init__.py`** for `FreeBootstrapperConfig`/`FreeConfig`. `OpentelemetryConfig` is not in `__init__.py` today, so the module-level alias suffices.
- **Update internal references and tests to the new names.** Aliases serve external users, not internal code. Aliases also exercise the new public API via tests.
- **Alias is a class assignment, not a subclass:** `OpentelemetryConfig = OpenTelemetryConfig` — same class object. `isinstance(x, OpentelemetryConfig) is isinstance(x, OpenTelemetryConfig)`. No `__init_subclass__` surprises, no MRO churn.

---

## Cross-cutting concerns

1. **Pickling.** Class identity is preserved by the alias (same object). New pickles use `OpenTelemetryConfig.__qualname__`. Old pickles (made before the rename, containing `OpentelemetryConfig` in their serialized form) still unpickle because the alias keeps the name resolvable in the module namespace. No data migration needed.

2. **Import ordering.** The alias line MUST come AFTER the class definition. Standard Python — but easy to get wrong if reordering imports.

3. **No PLR2004 noqa.** No new magic-value assertions in this PR.

---

## Task 1: Create branch

**Files:** (no files; git only)

- [ ] **Step 1: Branch off `main`**

```bash
git checkout main
git pull --ff-only origin main
git checkout -b refactor/low-7-naming
```

Expected: `Switched to a new branch 'refactor/low-7-naming'`.

---

## Task 2: Rename `OpentelemetryConfig` → `OpenTelemetryConfig`

### Step 1: Rename in `lite_bootstrap/instruments/opentelemetry_instrument.py`

Locate the class definition (after `OpenTelemetryServiceFieldsConfig` from PR6):

```python
@dataclasses.dataclass(kw_only=True, frozen=True)
class OpentelemetryConfig(OpenTelemetryServiceFieldsConfig):
    ...
```

Change `class OpentelemetryConfig` → `class OpenTelemetryConfig`.

Locate `OpenTelemetryInstrument`'s generic parameter:

```python
class OpenTelemetryInstrument(BaseInstrument[OpentelemetryConfig]):
```

Change to `BaseInstrument[OpenTelemetryConfig]`.

Locate any other reference to `OpentelemetryConfig` in the file (e.g., field type annotations, function signatures) — there shouldn't be many; the symbol mostly appears in the class definition and the instrument generic.

**Add the alias at the very end of the file**, after all class declarations:

```python
# Backward-compatible alias preserved for users importing the old (lowercase t) spelling.
OpentelemetryConfig = OpenTelemetryConfig
```

### Step 2: Update inheritance + imports in three framework bootstrappers

**File:** `lite_bootstrap/bootstrappers/fastapi_bootstrapper.py`

Locate the import line:

```python
from lite_bootstrap.instruments.opentelemetry_instrument import OpentelemetryConfig, OpenTelemetryInstrument
```

Change `OpentelemetryConfig` → `OpenTelemetryConfig`.

Locate `FastAPIConfig`'s inheritance:

```python
class FastAPIConfig(
    CorsConfig,
    HealthChecksConfig,
    LoggingConfig,
    OpentelemetryConfig,    # ← change to OpenTelemetryConfig
    ...
```

Change `OpentelemetryConfig` → `OpenTelemetryConfig`.

**File:** `lite_bootstrap/bootstrappers/litestar_bootstrapper.py` — same two changes.

**File:** `lite_bootstrap/bootstrappers/faststream_bootstrapper.py` — same two changes.

### Step 3: Update tests

**Files:** `tests/instruments/test_opentelemetry_instrument.py`, `tests/instruments/test_logging_instrument.py`

In each test file, change every `OpentelemetryConfig` reference (in imports and constructor calls) to `OpenTelemetryConfig`. Use Edit's `replace_all=true` for safety:

```python
# Before:
from lite_bootstrap.instruments.opentelemetry_instrument import OpentelemetryConfig, ...

# After:
from lite_bootstrap.instruments.opentelemetry_instrument import OpenTelemetryConfig, ...
```

And similarly for constructor calls like `OpentelemetryConfig(...)` → `OpenTelemetryConfig(...)`.

### Step 4: Smoke test after the Otel rename

```bash
just test -- tests/instruments/test_opentelemetry_instrument.py tests/instruments/test_logging_instrument.py -v
```

Expected: all PASS. If anything fails with `NameError`, check that all references were updated.

---

## Task 3: Rename `FreeBootstrapperConfig` → `FreeConfig`

### Step 1: Rename in `lite_bootstrap/bootstrappers/free_bootstrapper.py`

Current class:

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class FreeBootstrapperConfig(LoggingConfig, OpentelemetryConfig, PyroscopeConfig, SentryConfig): ...
```

Two changes here:
1. Rename to `class FreeConfig(LoggingConfig, OpenTelemetryConfig, PyroscopeConfig, SentryConfig): ...` (also picks up the Otel rename from Task 2).
2. Update the bootstrapper:

```python
class FreeBootstrapper(BaseBootstrapper[None]):
    ...
    instruments_types: typing.ClassVar = [...]
    bootstrap_config: FreeBootstrapperConfig    # ← change to FreeConfig
    not_ready_message = ""
    ...
    def __init__(self, bootstrap_config: FreeBootstrapperConfig) -> None:    # ← change to FreeConfig
        super().__init__(bootstrap_config)
```

Replace both `FreeBootstrapperConfig` occurrences with `FreeConfig`.

**Add the alias at the end of the file:**

```python
# Backward-compatible alias preserved for users importing the old name.
FreeBootstrapperConfig = FreeConfig
```

### Step 2: Update `lite_bootstrap/__init__.py`

Current:

```python
from lite_bootstrap.bootstrappers.free_bootstrapper import FreeBootstrapper, FreeBootstrapperConfig
...
__all__ = [
    ...
    "FreeBootstrapper",
    "FreeBootstrapperConfig",
    ...
]
```

Change to:

```python
from lite_bootstrap.bootstrappers.free_bootstrapper import FreeBootstrapper, FreeBootstrapperConfig, FreeConfig
...
__all__ = [
    ...
    "FreeBootstrapper",
    "FreeBootstrapperConfig",
    "FreeConfig",
    ...
]
```

Both names exported. Alphabetical order in `__all__` keeps `FreeBootstrapperConfig` before `FreeConfig`. Add `FreeConfig` after `FreeBootstrapperConfig`.

### Step 3: Update tests

**File:** `tests/test_free_bootstrap.py`

Change every `FreeBootstrapperConfig` → `FreeConfig` (in imports, fixture annotations, constructor calls). Use Edit's `replace_all=true`.

**File:** `tests/instruments/test_pyroscope_instrument.py`

The pyroscope tests use `FreeBootstrapperConfig` to exercise the inheritance-through-Free path. Change references to `FreeConfig`.

### Step 4: Smoke test after the Free rename

```bash
just test -- tests/test_free_bootstrap.py tests/instruments/test_pyroscope_instrument.py -v
```

Expected: all PASS.

---

## Task 4: Verify everything, commit

### Step 1: Run the full test suite

```bash
just test
```

Expected: 129/129 PASS. No behavior change; just symbol renames.

### Step 2: Verify the aliases work for external imports

```bash
uv run python -c "from lite_bootstrap import FreeBootstrapperConfig, FreeConfig; assert FreeBootstrapperConfig is FreeConfig; print('FreeConfig alias OK')"
uv run python -c "from lite_bootstrap.instruments.opentelemetry_instrument import OpentelemetryConfig, OpenTelemetryConfig; assert OpentelemetryConfig is OpenTelemetryConfig; print('OpenTelemetryConfig alias OK')"
```

Both should print `... OK`. If either fails, the alias is broken.

### Step 3: Run lint

```bash
just lint
```

Expected: clean. Watch for:
- `ruff format` may reorder imports — accept its formatting.
- `ty` should be happy with both names since they're the same class.

### Step 4: Sanity grep — verify no leftover old-name references in internal code

```bash
grep -rn "OpentelemetryConfig\|FreeBootstrapperConfig" lite_bootstrap/ tests/ --include="*.py" | grep -v "alias\|backward"
```

Expected: ONLY the two alias-definition lines (`OpentelemetryConfig = OpenTelemetryConfig` and `FreeBootstrapperConfig = FreeConfig`) PLUS the `__init__.py` import/export entries (3 matches total for `FreeBootstrapperConfig`: import line, `__all__` entry, alias line; 1 match total for `OpentelemetryConfig`: the alias line).

If any other `*.py` file has a reference to the old names outside these alias contexts, that's a missed update — fix it.

### Step 5: Commit

Stage all 11 files explicitly:

```bash
git add \
  lite_bootstrap/instruments/opentelemetry_instrument.py \
  lite_bootstrap/bootstrappers/free_bootstrapper.py \
  lite_bootstrap/bootstrappers/fastapi_bootstrapper.py \
  lite_bootstrap/bootstrappers/litestar_bootstrapper.py \
  lite_bootstrap/bootstrappers/faststream_bootstrapper.py \
  lite_bootstrap/__init__.py \
  tests/test_free_bootstrap.py \
  tests/instruments/test_opentelemetry_instrument.py \
  tests/instruments/test_logging_instrument.py \
  tests/instruments/test_pyroscope_instrument.py
git commit -m "$(cat <<'EOF'
refactor: rename OpentelemetryConfig → OpenTelemetryConfig; FreeBootstrapperConfig → FreeConfig

Two API-surface renames with silent backward-compatibility aliases.

OpentelemetryConfig → OpenTelemetryConfig: matches the conventional
OpenTelemetry capitalization and the OpenTelemetryServiceFieldsConfig
mixin introduced in PR6. Module-level alias `OpentelemetryConfig =
OpenTelemetryConfig` preserves existing imports. Not exported from
__init__.py (wasn't before either).

FreeBootstrapperConfig → FreeConfig: matches the sibling configs
(FastAPIConfig, LitestarConfig, FastStreamConfig — none carry the
"Bootstrapper" infix). Module-level alias plus `FreeBootstrapperConfig`
re-export in __init__.py preserves existing public imports.

Internal references and tests updated to the new canonical names.
Aliases are simple class assignments — same class object, so
isinstance(x, OldName) and isinstance(x, NewName) are interchangeable.
Old pickles continue to unpickle via the alias.

No behavior change. 129/129 tests pass.

Closes LOW-7 from the audit. Also closes the bonus Otel capitalization
item surfaced during PR6's code review.
EOF
)"
```

---

## Task 5: Push and open PR

- [ ] **Step 1: Push the branch**

```bash
git push -u origin refactor/low-7-naming
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --title "refactor: rename OpentelemetryConfig → OpenTelemetryConfig; FreeBootstrapperConfig → FreeConfig" --body "$(cat <<'EOF'
## Summary
The final PR of the deferred-refactors sequence. Two API-surface renames with silent backward-compatibility aliases:

- **`OpentelemetryConfig` → `OpenTelemetryConfig`** — matches the conventional OpenTelemetry capitalization and the `OpenTelemetryServiceFieldsConfig` mixin from PR6. Module-level alias preserves existing imports. Not exported from `__init__.py` (wasn't before).
- **`FreeBootstrapperConfig` → `FreeConfig`** — matches the sibling configs (`FastAPIConfig`, `LitestarConfig`, `FastStreamConfig` — none carry the `Bootstrapper` infix). Module-level alias plus `FreeBootstrapperConfig` re-export in `__init__.py` preserves existing public imports.

Internal references and tests updated to the new canonical names. Aliases are simple class assignments — same class object, so `isinstance(x, OldName)` and `isinstance(x, NewName)` are interchangeable. Old pickles continue to unpickle via the alias.

No behavior change. 129/129 tests pass.

Closes LOW-7 from an internal audit. Also closes the bonus Otel capitalization item surfaced during PR6's code review.

## Test plan
- [x] `just test` — 129/129.
- [x] `just lint` — clean.
- [x] Aliases verified working (`isinstance(x, OldName) is isinstance(x, NewName)` for both renames).
- [ ] Reviewer: confirm the aliases are simple class assignments (not subclasses), so isinstance behavior is fully preserved.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review

**Spec coverage check** against the sequencing spec (PR15 section) and audit (LOW-7):

| Spec item | Task |
|-----------|------|
| Rename `OpentelemetryConfig` → `OpenTelemetryConfig` | Task 2, Step 1 |
| Add silent alias `OpentelemetryConfig = OpenTelemetryConfig` | Task 2, Step 1 |
| Rename `FreeBootstrapperConfig` → `FreeConfig` | Task 3, Step 1 |
| Add silent alias `FreeBootstrapperConfig = FreeConfig` | Task 3, Step 1 |
| Export both names from `__init__.py` | Task 3, Step 2 |
| Update internal references in framework bootstrappers | Task 2, Step 2 |
| Update tests to use new canonical names | Tasks 2 Step 3 + 3 Step 3 |
| Verify aliases work (`is` identity) | Task 4, Step 2 |
| Sanity grep for missed references | Task 4, Step 4 |
| Branch name `refactor/low-7-naming` | Task 1, Step 1 |
| Verification: `just test` + `just lint` clean | Task 4, Steps 1, 3 |

All spec items covered. No placeholders.

**Risk:** Low. Aliases preserve every existing import. The mechanical rename is well-scoped (11 files, predictable changes). The sanity grep at Task 4 Step 4 catches any miss.

**Why this is the last PR:** With this merged, all 8 deferred-refactor PRs (PR8-15) close every audit finding except those explicitly marked out-of-scope in the sequencing spec. The audit becomes fully resolved.
