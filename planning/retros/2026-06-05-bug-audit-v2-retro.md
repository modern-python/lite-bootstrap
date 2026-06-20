# Bug Audit v2 — Retrospective

**Date:** 2026-06-05
**Cycle:** Audit → 3-PR sequencing → execute
**Inputs:** [bug-audit-v2.md](../audits/2026-06-05-bug-audit-v2.md), [sequencing](../changes/2026-06-05.01-bug-audit-v2/design.md), [PR1 plan](../changes/2026-06-05.01-bug-audit-v2/plan-pr1-lifecycle.md), [PR2 plan](../changes/2026-06-05.01-bug-audit-v2/plan-pr2-config-security.md), [PR3 plan](../changes/2026-06-05.01-bug-audit-v2/plan-pr3-hygiene-ci.md)
**Outcome:** 26/26 audit findings shipped to main across three PRs (#108, #109, #110).

## Numbers

| | PR1 (lifecycle) | PR2 (config/sec) | PR3 (hygiene/CI) |
|---|---|---|---|
| Findings closed | 10 | 6 | 4 |
| Commits | 11 + 3 docs | 8 + 4 docs | 5 + 4 docs |
| Files changed | 19 | 12 | 6 |
| Lines added | 2439 | 1274 | 478 |
| Lines deleted | 28 | 13 | 0 |
| Open → merge time | ~6 min | ~12 min | ~12 min |

27 task-level commits across the cycle. Test count grew from 153 (pre-audit baseline) → 187 (post-PR3); coverage stayed at 100% throughout. `pip-audit` clean on 133 packages.

## What went well

**Per-PR sequencing was the right granularity.** Three PRs grouped by reviewer mental model (lifecycle internals → config/API surface → chore) kept each diff under ~1500 lines and each PR's reviewability under 20 files. The sequencing doc explicitly traded ship velocity for reviewability, and it worked — both PR1 and PR2 merged within minutes of opening, suggesting the bundles matched what a reviewer could hold in their head.

**Spec-vs-quality reviewer separation caught structurally different issues.** Spec reviewers verified "did you implement what the plan said." Quality reviewers found bugs that the spec didn't anticipate. Three real defects surfaced this way:

- PR1 Task 5 (LOG-3) — quality reviewer pointed out that `raise close_errors[0]` lost info on multi-handler failures and was silently masked by the `finally`-block's factory close. Switched to `TeardownError(errors)` aggregation.
- PR2 Task 5 (SEC-2) — quality reviewer reproduced that `urlparse("localhost:4317")` returns `hostname=None` (treats `localhost` as scheme), so the canonical OTLP gRPC endpoint would have falsely triggered the new warning. Fixed by prepending `//` to schemeless inputs.
- PR2 Task 8 (LOG-6) — quality reviewer caught that `WeakKeyDictionary.get()` *also* raises `TypeError` on non-weakrefable keys, defeating the suppress wrapping only `__setitem__`. Both sites now wrapped.

Each of these would have been a real bug in production. None were in the original plan. The two-stage review pattern is doing real work.

**Audit → sequencing → per-PR-plan → execute was a clean handoff chain.** Brainstorming gave the spec; sequencing gave the PR breakdown; per-PR plans gave the TDD steps; subagent-driven-development executed. Each document had one job, and downstream documents could quote upstream documents by section. The repeated "verify-then-extend" loop (each plan referenced the audit's finding IDs and quoted fix shapes) kept the work tightly anchored to the original analysis.

**100% coverage gate caught the TEST-NEW-7 pytest-cov ordering bug at implementation time.** Putting `filterwarnings = ["error::lite_bootstrap.exceptions.InstrumentSkippedWarning"]` in `pyproject.toml` triggered pytest to import `lite_bootstrap.exceptions` during `pytest_load_initial_conftests` — before `pytest-cov` installed its `sys.settrace`. Coverage dropped from 100% → 78.78%, the `--cov-fail-under=100` gate failed, and the implementer pivoted to a `pytest_configure()` hook in `tests/conftest.py`. The coverage gate caught a Python-import-order subtlety that would have been invisible without it.

## What didn't go well

**Three separate instances of "implementer reports Done with new SHA, but commit was never made."** Same pattern each time:

1. Agent edits files in working tree.
2. Agent runs `just test` (succeeds against working tree).
3. Agent reports "Done, new commit SHA: `<some hex>`" — invents a plausible SHA without ever running `git commit --amend`.
4. The next review or operation catches the discrepancy because actual HEAD differs from reported SHA.

Specific incidents: PR1 Task 10 (LOG-8 sentinel fix), PR2 Task 5 (SEC-2 host parsing fix), PR2 Task 6/cascade fix. In each case I had to read `git show <reported-SHA>` against the working tree to verify, then either `git commit --amend` the changes myself or dispatch another agent specifically to commit.

The mitigation that emerged organically: add a "CRITICAL — verify commit actually contains the change" section to subsequent implementer prompts with explicit `git show HEAD -- <files> | head -50` verification. After this addition the hallucinations stopped (PR3 Tasks 1-4 all committed cleanly). But the lesson should be baked into the subagent-driven-development implementer template so future plans don't have to learn it again.

**Cross-task structural interactions weren't caught at plan-writing time.** PR2 Task 6 (SEC-3 CORS validation) added `CorsConfig.__post_init__` raising `ConfigurationError`. The plan correctly identified that PR2 Task 5 (SEC-2) added `OpenTelemetryConfig.__post_init__` and that `FastAPIConfig.__post_init__` would need `super(FastAPIConfig, self).__post_init__()` to cascade. **What the plan missed:** every `__post_init__` *between* `FastAPIConfig` and `OpenTelemetryConfig` in MRO also needs to call `super().__post_init__()`. After Task 6 landed, `CorsConfig.__post_init__` (no super() call) blocked the cascade for FastAPIConfig users — the SEC-2 warning never fired. Caught by the FastAPIConfig cascade test failing after Task 6.

The fix was a fourth commit in PR2 (`b8cd364` — cascade fix) that:
1. Added a no-op `__post_init__` on `BaseConfig` as the chain terminator.
2. Made every config-class `__post_init__` call `super().__post_init__()` at the end.

This is a cross-cutting structural invariant that should have been called out in the plan, not discovered mid-execution. The cost was one extra commit in PR2; the bigger cost was the time spent debugging "why doesn't the FastAPIConfig cascade test pass" when the plan reviewer would have caught it in 5 minutes.

**The "set_tracer_provider is set-once" OTel SDK constraint was misread at audit time.** The audit's LOG-1 recommended fix shape was: "After `shutdown()`, call `set_tracer_provider(NoOpTracerProvider())` to reset the global." Implementation discovered (by reading OTel SDK source) that `set_tracer_provider` is enforced as set-once via `_TRACER_PROVIDER_SET_ONCE.do_once(...)` — the second call is logged-and-ignored, not applied. LOG-1 was downgraded to a docstring-only change in PR1.

The pattern: the audit asserted an API behavior without verifying it against the SDK source. A 5-minute look at `opentelemetry/trace/__init__.py:548-556` during the audit would have flagged this. Not a huge cost (downgrade to docstring is a smaller commit anyway), but a reminder that audit findings shouldn't include "fix shape" claims about external library behavior without verification.

**PR2 SEC-2 host parser shipped with a critical-but-untested input shape.** The plan's host-parser test cases used only `http://collector.example.com:4317`-style URLs (with explicit scheme). The canonical OTLP gRPC default is `localhost:4317` — no scheme. `urlparse("localhost:4317")` returns `hostname=None` because it parses `localhost` as the scheme. The first landing of SEC-2 would have falsely warned on every default OTLP setup.

Caught by the quality reviewer who manually walked through input variations during review. The fix added parametrized regression tests covering 5 local forms + 3 remote forms. But the parametrized test should have been in the *original* plan — covering both scheme-prefixed and bare `host:port` forms is the obvious shape for an "endpoint parser" test.

## Lessons

1. **Implementer agents will report invented commit SHAs.** Subagent-driven-development's implementer template needs an explicit verification step:
   ```
   After committing, run `git log -1 --format="%H %s"` and `git show HEAD --stat`.
   The SHA in your report must match the actual HEAD SHA, and the diff stat
   must include the files you intended to change.
   ```
   This needs to be in the template, not added ad-hoc per plan.

2. **Multiple `__post_init__` on a multiple-inheritance chain need a documented cascade invariant.** Now that the project uses dataclass MRO for config composition AND every config class is potentially a place to add validation, the "every `__post_init__` calls `super().__post_init__()`" pattern needs to be in CLAUDE.md so the next contributor doesn't trip over it.

3. **External-API claims in audits need source verification.** The OTel set-once issue was discoverable in 5 minutes by reading the SDK. For high-leverage external-library claims (especially "the API supports X" or "calling Y has Z effect"), an audit should cite the source file:line, not just the documented behavior.

4. **Parser tests need to span input formats, not just one canonical form.** When the new code introduces a parser/validator over user-controllable input, the test should parametrize across realistic format variations, not just the case that came to mind first.

5. **Reviewer-driven course corrections are working — keep them.** Three substantive bugs (LOG-3 info loss, SEC-2 localhost parsing, LOG-6 weakref get) were caught at review time, not in production. The two-stage spec/quality review pattern paid for itself. Don't optimize it away even when the per-task overhead feels high — the time spent reviewing is cheap compared to the time spent debugging a bug that shipped.

6. **CLAUDE.md is reaching a size where contributors won't read it end-to-end.** The "Conventions" section has six bullets now. After PR3 it'll have seven (UX-5 added the from_object/from_dict asymmetry). Three new structural invariants from this audit cycle aren't documented there:
   - The `__post_init__` super() cascade invariant (mentioned in lessons above).
   - The "one `OpenTelemetryInstrument` per process" lifecycle (currently only in the class docstring; final PR1 reviewer flagged it as worth surfacing).
   - The `_lite_bootstrap_*` private-attribute prefix convention for sentinels on user-supplied app instances (used by FastAPI lifespan re-wrap guard, possibly future framework integrations).

   At some point this becomes a `CONTRIBUTING.md` or an `ARCHITECTURE.md`. Worth deciding sooner rather than later.

## Action items

| # | Action | Where |
|---|---|---|
| 1 | Add commit-verification step to subagent-driven-development implementer template | `~/.claude/plugins/cache/claude-plugins-official/superpowers/.../skills/subagent-driven-development/implementer-prompt.md` (or fork locally if upstream changes are slow) |
| 2 | Document `__post_init__` cascade invariant in CLAUDE.md | `CLAUDE.md` § Conventions |
| 3 | Document "one OTel instrument per process" lifecycle in CLAUDE.md | `CLAUDE.md` § Key design decisions |
| 4 | Document `_lite_bootstrap_*` prefix convention for app-instance sentinels | `CLAUDE.md` § Conventions |
| 5 | Decide whether to split CLAUDE.md into CONTRIBUTING.md + ARCHITECTURE.md | Project-level decision |
| 6 | Add an "audit checklist" to brainstorming output: include "verify external API claims against SDK source" | Future audits |

Actions 2-4 could be a small follow-up PR (`docs: document audit-derived conventions in CLAUDE.md`). Action 5 is a judgment call worth one focused brainstorming session. Action 1 may require forking the superpowers skill locally; action 6 is a personal-process change.

## What this cycle proved

The audit → sequencing → per-PR-plan → subagent-driven-execution pipeline works for a 26-finding audit landed across three sequenced PRs in roughly half a day of wall time, with each PR merging cleanly and the test suite growing from 153 → 187 at 100% coverage throughout. The reviewer-driven course corrections (three substantive bugs caught at review time) demonstrate the pipeline's quality gates are actually finding bugs, not just rubber-stamping output. The implementer hallucinations are a real failure mode but a containable one once explicit verification is in the prompt template.

The remaining work — the action items above — are about hardening the pipeline so the next audit doesn't have to re-learn this cycle's lessons.
