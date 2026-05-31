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
