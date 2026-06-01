# Lightweight Plan Template

For sub-30-LOC PRs where the diff IS effectively the plan, use this template
instead of the full multi-task plan structure. The full structure is
appropriate when there's real design judgment, cross-cutting changes, or
multiple coordinated edits; for trivial fixes the overhead is inverted (PR8 was
a 222-line plan for a 2-line edit).

Use the full template when ANY of these apply:
- More than 2 production files modified
- Cross-cutting / cascade-style change (frozen-inheritance, generic typing, file split)
- New module/file introduced
- Public API surface changes (renames, additions, removals)
- Behavior change with non-trivial test design (regression test that hand-crafts mock state, lifecycle replay, etc.)

Use the lightweight template when ALL of these apply:
- ≤2 production files modified
- ≤30 LOC net change
- No new files
- No public API change (or trivial rename with alias)
- The test (if any) is a single straightforward addition

---

## Template

```markdown
# PR<N>: <Short title>

**Goal:** <One sentence: what changes and why>

**Files:**
- `path/to/file1.py` — what changes
- `path/to/tests/test_file.py` — test added/updated (if applicable)

**Parent spec:** `<sequencing spec path>`
**Audit ref:** `<audit finding ID>`

---

## Diff (or close enough)

`path/to/file1.py`:

```python
# Before:
<old code>

# After:
<new code>
```

`tests/test_file.py`:

```python
# Append at end of file:
def test_<name>() -> None:
    # ...
```

---

## Verification

1. `just test -- tests/path/to/test_file.py::<test_name> -v` — failing test:
   expected error: `<exact assertion failure or exception>`
2. Apply the production change.
3. `just test -- tests/path/to/test_file.py::<test_name> -v` — passes.
4. `just test` — full suite (target: <expected count>).
5. `just lint` — clean.

## Pre-flight grep (if change touches public symbols or cross-file references)

```bash
grep -rn "<symbol>" lite_bootstrap/ tests/ --include="*.py"
```

Confirm the number of matches and their files before editing. After the change,
re-run the grep and verify it matches expectations (all updated, or only
intentional alias / backward-compat sites remain).

## Commit

```bash
git add <exact files>
git commit -m "<conventional commit subject>"
```

## PR

Branch: `fix/<finding-id>-<slug>` or `refactor/<finding-id>-<slug>`.
Push, open via `gh pr create` with body summarizing the change.
```

---

## Pre-flight grep checklist

Add this section to ANY plan (lightweight or full) that touches symbols
referenced across multiple files. PR13 needed this: its surgical 2-class
scope was actually a 24-class cascade because of Python's frozen-inheritance
rule. A pre-flight grep would have surfaced the cascade at plan time.

Before drafting the diffs, run:

```bash
# Find all references to the symbol(s) being changed
grep -rln "<SymbolName>" lite_bootstrap/ tests/ --include="*.py"

# Count occurrences per file for scope estimation
grep -rc "<SymbolName>" lite_bootstrap/ tests/ --include="*.py" | grep -v ":0$"

# For inheritance / type-system changes, check what inherits from / references
# the affected type
grep -rn "class.*(\b<BaseClass>\b)" lite_bootstrap/ --include="*.py"
grep -rn ": <TypeName>\b" lite_bootstrap/ tests/ --include="*.py"
```

Bake the resulting file list into the plan. If the count diverges from
"a couple of files", reconsider whether the lightweight template is still
appropriate — you may have crossed into full-template territory.

For renames specifically, also check `__init__.py` exports:

```bash
grep -n "<SymbolName>" lite_bootstrap/__init__.py
```

If the symbol is publicly exported, the rename must include a backward-compat
alias in `__init__.py` (see PR15 for the established pattern).

---

## Type-checker behavior validation (when the plan claims type narrowing)

Add this section to ANY plan that claims a type-checker behavior — narrowing
across asserts, casts, sentinel identity checks, etc. PR16's plan claimed
"`ty` and Pyright both narrow `str | None` → `str` after the assert." The
`ty` half was correct; the Pyright half was wrong (Pyright doesn't narrow
attribute chains across asserts because in theory any intervening call
could mutate the attribute). The reviewer caught the discrepancy; no harm
done, but the plan over-promised.

Lesson: `ty` and Pyright behave differently in many narrowing scenarios,
especially:
- Attribute access (`self.x.y`) across asserts — `ty` narrows, Pyright doesn't
- `typing.cast` with string forward references — sometimes one accepts, the other complains
- TypedDict optional-key access — different default policies
- Conditional imports under `if X is not None:` runtime guards — Pyright pessimistic

Before writing a plan that depends on a type-checker behavior:

1. Write the minimal failing/working pattern in a scratch file.
2. Run `just lint` (which runs `ty`). Observe the diagnostic state.
3. Check the relevant Pyright output (e.g., open in IDE; or `uv run pyright <file>` if Pyright is installed).
4. Bake the OBSERVED behavior into the plan, not the assumed behavior.

If the two checkers disagree, the plan must say so explicitly and explain
why the change is still worth landing. The runtime safety + documentation
value of an assert often justifies it even when one checker doesn't
narrow — but say so.

---

## When the lightweight template isn't enough

The lightweight template fails when:

- The change cascades in non-obvious ways (Python language rules, framework conventions, build tooling)
- The test setup requires real fixture / mock state work (multiple `patch.object`, fixture composition, conditional skip logic)
- The behavior change crosses module boundaries
- The reviewer would benefit from explicit "Why this approach over alternatives"

In those cases, fall back to the full plan structure with explicit Task 1-N
sections, locked decisions, cross-cutting concerns, and self-review checklist.
The full template's structure is overhead, but it's overhead that has bought
real correctness wins — see PRs #7, #11, #13 for cases where the detailed
plan caught issues at plan time.

## Related conventions (PR8–15 emergent rules)

- **No `# noqa: PLR2004`** — extract magic values to named locals.
- **Backward-compat aliases for renames** — module-level class assignment + `__init__.py` re-export if the old name was public.
- **Frozen-config bypass in `__post_init__`** — `object.__setattr__` is acceptable with a one-line comment documenting the trade-off.
- **Optional-import guard pattern** — top-level `if import_checker.is_X_installed: import X` is the established pattern. Pyright doesn't model the guard; the project enforces `ty` instead. See `pyproject.toml` `[tool.pyright]` suppressions.
- **Real-time spec corrections** — when a plan / spec deviates from reality during execution, update the doc in the same PR as the implementation, not as a future cleanup.
