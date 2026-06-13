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
