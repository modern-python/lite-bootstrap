# PR12: Base Layer Cleanup (REF-3 + REF-5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:**
- **REF-3**: Drop `abc.ABC` from `BaseInstrument`. After PR7 made the class generic and removed the `# noqa: B027` suppressions, the `abc.ABC` parent serves no purpose — all four methods (`bootstrap`, `teardown`, `is_ready`, `check_dependencies`) are concrete no-ops with sensible defaults. Removing it clarifies the class's role as a regular generic base.
- **REF-5**: Add a one-line module docstring to `swagger_instrument.py` and `prometheus_instrument.py` explaining that these files are config holders; framework-specific behavior lives in the bootstrapper subclasses. Per the locked decision in the sequencing spec, KEEP these files as separate modules (don't collapse).

**Architecture:** Three files, three small edits. No behavior change.

**Tech Stack:** Python 3.10+ dataclasses, generics.

**Parent spec:** `docs/superpowers/specs/2026-06-01-deferred-refactors-sequencing.md` (PR12 section).
**Parent audit:** `docs/superpowers/specs/2026-05-31-bug-refactor-audit.md` (REF-3, REF-5).

---

## File Structure

Three files modified.

- Modify: `lite_bootstrap/instruments/base.py` — drop `abc.ABC` from `BaseInstrument`; remove the `import abc`.
- Modify: `lite_bootstrap/instruments/swagger_instrument.py` — add module docstring.
- Modify: `lite_bootstrap/instruments/prometheus_instrument.py` — add module docstring.

---

## Locked decisions (from sequencing spec)

- **REF-3 scope:** Only `BaseInstrument` loses `abc.ABC`. `BaseBootstrapper` (in `lite_bootstrap/bootstrappers/base.py`) keeps `abc.ABC` because it HAS abstract methods (`not_ready_message`, `_prepare_application`, `is_ready`).
- **REF-5 scope:** Keep `swagger_instrument.py` and `prometheus_instrument.py` as separate files (don't collapse). Add module docstrings explaining the split.

---

## Task 1: Create branch

**Files:** (no files; git only)

- [ ] **Step 1: Branch off `main`**

```bash
git checkout main
git pull --ff-only origin main
git checkout -b refactor/ref-3-5-base-layer
```

Expected: `Switched to a new branch 'refactor/ref-3-5-base-layer'`.

---

## Task 2: Apply both changes, verify, commit

### Step 1: REF-3 — drop `abc.ABC` from `BaseInstrument`

**File:** `lite_bootstrap/instruments/base.py`

Current file:

```python
import abc
import dataclasses
import typing

import typing_extensions


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class BaseConfig:
    ...


ConfigT = typing.TypeVar("ConfigT", bound=BaseConfig)


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class BaseInstrument(abc.ABC, typing.Generic[ConfigT]):
    bootstrap_config: ConfigT
    not_ready_message = ""
    missing_dependency_message = ""

    def bootstrap(self) -> None: ...

    def teardown(self) -> None: ...

    def is_ready(self) -> bool:
        return True

    @staticmethod
    def check_dependencies() -> bool:
        return True
```

Two changes:

1. Remove `import abc` from the top (it's no longer used in this file).
2. Change `class BaseInstrument(abc.ABC, typing.Generic[ConfigT]):` to `class BaseInstrument(typing.Generic[ConfigT]):`.

After:

```python
import dataclasses
import typing

import typing_extensions


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class BaseConfig:
    ...


ConfigT = typing.TypeVar("ConfigT", bound=BaseConfig)


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class BaseInstrument(typing.Generic[ConfigT]):
    bootstrap_config: ConfigT
    not_ready_message = ""
    missing_dependency_message = ""

    def bootstrap(self) -> None: ...

    def teardown(self) -> None: ...

    def is_ready(self) -> bool:
        return True

    @staticmethod
    def check_dependencies() -> bool:
        return True
```

`BaseConfig` is preserved unchanged (it never used `abc.ABC`).

### Step 2: REF-5 — add docstring to `swagger_instrument.py`

**File:** `lite_bootstrap/instruments/swagger_instrument.py`

Current file:

```python
import dataclasses

from lite_bootstrap.instruments.base import BaseConfig, BaseInstrument


@dataclasses.dataclass(kw_only=True, frozen=True)
class SwaggerConfig(BaseConfig):
    swagger_static_path: str = "/static"
    swagger_path: str = "/docs"
    swagger_offline_docs: bool = False


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class SwaggerInstrument(BaseInstrument[SwaggerConfig]):
    pass
```

Add a module docstring at the top:

```python
"""Swagger config and minimal base instrument; framework-specific behavior lives in the bootstrapper subclasses."""

import dataclasses

from lite_bootstrap.instruments.base import BaseConfig, BaseInstrument


@dataclasses.dataclass(kw_only=True, frozen=True)
class SwaggerConfig(BaseConfig):
    swagger_static_path: str = "/static"
    swagger_path: str = "/docs"
    swagger_offline_docs: bool = False


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class SwaggerInstrument(BaseInstrument[SwaggerConfig]):
    pass
```

Single addition: the module docstring on line 1.

### Step 3: REF-5 — add docstring to `prometheus_instrument.py`

**File:** `lite_bootstrap/instruments/prometheus_instrument.py`

Current file:

```python
import dataclasses

from lite_bootstrap.helpers.path import is_valid_path
from lite_bootstrap.instruments.base import BaseConfig, BaseInstrument


@dataclasses.dataclass(kw_only=True, frozen=True)
class PrometheusConfig(BaseConfig):
    prometheus_metrics_path: str = "/metrics"
    prometheus_metrics_include_in_schema: bool = False


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class PrometheusInstrument(BaseInstrument[PrometheusConfig]):
    not_ready_message = "prometheus_metrics_path is empty or not valid"

    def is_ready(self) -> bool:
        return bool(self.bootstrap_config.prometheus_metrics_path) and is_valid_path(
            self.bootstrap_config.prometheus_metrics_path
        )
```

Add a module docstring:

```python
"""Prometheus config and readiness check; framework-specific bootstrap lives in the bootstrapper subclasses."""

import dataclasses

from lite_bootstrap.helpers.path import is_valid_path
from lite_bootstrap.instruments.base import BaseConfig, BaseInstrument


@dataclasses.dataclass(kw_only=True, frozen=True)
class PrometheusConfig(BaseConfig):
    ...
```

(Rest of the file unchanged.)

### Step 4: Run the full test suite

```bash
just test
```

Expected: 128/128 PASS. REF-3 is a metaclass/MRO change but `abc.ABC` was unused (no abstract methods); dropping it should be invisible at runtime. REF-5 is pure docstring additions.

Watch for surprises in:
- `tests/test_free_bootstrap.py` — exercises the base instrument lifecycle directly.
- Framework integration tests — instantiate instruments via the bootstrapper chain.

If anything fails, the most likely cause is some `isinstance(..., abc.ABC)` check somewhere, or a place that relies on the `abc.ABC` metaclass. Search the codebase: `grep -rn "abc\.ABC\|isinstance.*ABC" lite_bootstrap/ tests/`. If only `bootstrappers/base.py` matches (BaseBootstrapper still uses ABC), all good.

### Step 5: Run lint

```bash
just lint
```

Expected: clean. Watch for `F401` warning on the removed `import abc` — should not fire if the import was actually removed.

### Step 6: Commit

Stage exactly three files:

```bash
git add \
  lite_bootstrap/instruments/base.py \
  lite_bootstrap/instruments/swagger_instrument.py \
  lite_bootstrap/instruments/prometheus_instrument.py
git commit -m "$(cat <<'EOF'
refactor: drop unused abc.ABC from BaseInstrument; document config holders

REF-3: BaseInstrument inherited from abc.ABC but defined no abstract
methods. After PR7 made the class generic and removed the # noqa: B027
suppressions, abc.ABC serves no purpose — all four methods
(bootstrap, teardown, is_ready, check_dependencies) are concrete
no-ops with sensible defaults. Drop the abc.ABC parent and the now-
unused `import abc`.

BaseBootstrapper still uses abc.ABC (it has real abstract methods:
not_ready_message, _prepare_application, is_ready) and is unchanged.

REF-5: Add one-line module docstrings to swagger_instrument.py and
prometheus_instrument.py explaining that these files hold config and
minimal base logic; framework-specific bootstrap behavior lives in
the bootstrapper subclasses (FastAPISwaggerInstrument, etc.). These
files were left as separate modules per the locked decision in the
deferred-refactors sequencing spec.

No behavior change.

Closes REF-3 and REF-5 from the audit.
EOF
)"
```

---

## Task 3: Push and open PR

- [ ] **Step 1: Push the branch**

```bash
git push -u origin refactor/ref-3-5-base-layer
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --title "refactor: drop unused abc.ABC from BaseInstrument; document config holders" --body "$(cat <<'EOF'
## Summary
Two small base-layer cleanups:

- **REF-3:** `BaseInstrument` inherited from `abc.ABC` but defined no abstract methods. After PR7 made the class generic and removed the `# noqa: B027` suppressions, `abc.ABC` serves no purpose — all four methods (`bootstrap`, `teardown`, `is_ready`, `check_dependencies`) are concrete no-ops with sensible defaults. Drop the `abc.ABC` parent and the now-unused `import abc`. `BaseBootstrapper` still uses `abc.ABC` (it has real abstract methods) and is unchanged.
- **REF-5:** Added one-line module docstrings to `swagger_instrument.py` and `prometheus_instrument.py` explaining that these files hold config and minimal base logic; framework-specific bootstrap behavior lives in the bootstrapper subclasses. Kept as separate modules per the locked decision in the deferred-refactors sequencing spec.

No behavior change.

Closes REF-3 and REF-5 from an internal audit.

## Test plan
- [x] `just test` — 128/128.
- [x] `just lint` — clean.
- [ ] Reviewer: confirm no `isinstance(..., abc.ABC)` check anywhere in the codebase relies on `BaseInstrument`'s ABC parent.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review

**Spec coverage check** against the sequencing spec (PR12 section) and audit (REF-3, REF-5):

| Spec item | Task |
|-----------|------|
| REF-3: drop `abc.ABC` from `BaseInstrument`; drop unused `import abc` | Task 2, Step 1 |
| REF-3: keep `abc.ABC` on `BaseBootstrapper` (not touched) | Task 2, Step 1 (out of scope confirmation) |
| REF-5: docstring on `swagger_instrument.py` | Task 2, Step 2 |
| REF-5: docstring on `prometheus_instrument.py` | Task 2, Step 3 |
| REF-5: keep both files separate (don't collapse) | Locked decisions section |
| Branch name `refactor/ref-3-5-base-layer` | Task 1, Step 1 |
| Verification: `just test` + `just lint` clean | Task 2, Steps 4-5 |

All spec items covered. No placeholders.

**Risk:** Low. Both REF-3 and REF-5 are essentially metadata/documentation changes. The only theoretical risk is a downstream consumer relying on `isinstance(inst, abc.ABC)` checks on `BaseInstrument` instances — vanishingly unlikely in practice. The test suite catches it if anything's broken.
