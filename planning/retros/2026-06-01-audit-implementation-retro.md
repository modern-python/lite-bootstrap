# Retrospective: 15-PR Audit Implementation Arc

**Date:** 2026-06-01
**Scope:** PRs #89–103 across two sequenced waves
**Parent docs:**
- Audit: [2026-05-31-bug-refactor-audit.md](../audits/2026-05-31-bug-refactor-audit.md)
- Sequencing 1: [2026-05-31-audit-implementation-sequencing.md](../changes/2026-05-31.01-audit-implementation.md)
- Sequencing 2: [2026-06-01-deferred-refactors-sequencing.md](../changes/2026-06-01.03-deferred-refactors.md)

---

## What shipped

**Wave 1 (criticals + design issues, PRs #89–95):**
- 3 critical bugs (redoc `root_path`, OTel tracer shutdown, idempotent teardown)
- 5 design issues (skip_sentry leak, dead conjuncts, config method semantics, OTel mixin, generic BaseInstrument)
- 9 paired regression tests

**Wave 2 (deferred refactors, PRs #96–103):**
- 7 refactor opportunities (OTel hoist, logging split, base layer, frozen cascade, FastStream timeout, naming pass)
- 3 test-gap fills (standalone instrument tests, `is_valid_path` negatives, logging lifecycle replay)
- 9 LOW-priority cleanups (Sentry idiom/typing, OTel newline + `id()` comment, docstrings, etc.)
- 1 bonus capitalization rename (`Opentelemetry` → `OpenTelemetry`)

**Test suite:** 79 → 129 tests (+50, ~63% growth). 100% coverage preserved.

**Process artifacts:** 1 audit doc + 2 sequencing specs + 15 implementation plans + 1 retro doc = ~18 markdown docs totaling ~5,000 lines, against ~1,500 lines of net code change.

---

## What went well

**1. Two-stage subagent review caught issues in 5 of 15 PRs.**

The "spec compliance review → code quality review" gate caught real problems before push:
- **PR2:** Shutdown-exception leaving stale `_tracer_provider` (flagged as PR3 follow-up).
- **PR5:** Missing pinning test for `from_dict({"x": None})` overrides defaults — added to amended commit.
- **PR10:** `# noqa: PLR2004` slipped in; user intervention → extract `expected_max_age = 600` named local. Pattern then propagated to PR11, PR14.
- **PR11:** Dead `import logging.handlers` after file split — caught by quality reviewer, amended.
- **PR13:** `FastAPIConfig(application=None)` regression from sentinel-identity check — fixed via guard (later dropped as unreachable by user).

None of these would have surfaced from `just test`/`just lint` alone.

**2. Plan → red test → fix → green test discipline.**

For every fix-class PR (criticals + DES-4), the plan called for a regression test that failed first, passed after. The implementer reported the actual failure mode in every case. This proved the test was actually covering the bug, not asserting incidentals.

**3. Model selection paid off.**

`haiku` for mechanical PRs (PR8 micro-fixes, PR10 test additions, PR12 base-layer cleanup, PR14 config field, PR15 renames). `sonnet` for refactors with real judgment (PR7 generic, PR11 file split, PR13 cascade). No PR needed `opus`. Cost-aware without quality compromise.

**4. Pyright vs ty pattern was stable and predictable.**

Once established (conditional imports + framework subclass invariant complaints), every PR's Pyright noise was the same shape. We dismissed it confidently 15 times in a row, and `ty check` never disagreed.

**5. Real-time spec corrections.**

Three times we caught spec-vs-reality drift and updated docs retroactively:
- PR13: sequencing spec assumed 2-class scope; actual was 24 (Python frozen cascade). Plan + spec updated.
- PR13: spec called for `typing.cast` sentinel; user contributed a proper `UnsetType` class. Plan + spec updated.
- PR7: deviation from sequencing's "drop redundant annotations" decision — documented in commit and PR body rather than silently diverging.

**6. The user-as-reviewer loop.**

Each PR-level review caught things only domain knowledge can catch — the frozen cascade hazard, the `UnsetType` improvement, the no-`PLR2004`-noqa policy, the unreachable `None` guard. The subagents executed; the user steered.

---

## What didn't go well

**1. Plan accuracy on cross-cutting changes was uneven.**

- PR13 plan: said "2 classes lose `frozen`"; reality required 24 because of Python's frozen-inheritance rule. The implementer hit `TypeError` on the partial cascade and had to recover. Should have been caught at plan time by writing one example child class and checking the rule.
- PR15 plan: said "11 files"; actual was 10. Off-by-one because I miscounted while writing. Reviewer didn't flag.
- PR7: deviation from sequencing spec was legitimate but required mid-execution decision. The sequencing spec's locked decision wasn't fully thought through.

**2. Several PRs required amend cycles for issues the plan should have prevented.**

PR5 (missing pin), PR10 (PLR2004 noqa), PR11 (dead `logging.handlers` import), PR13 (None guard). Five amend cycles across 15 PRs is high; each one was caught by reviewer rather than implementer.

**3. Doc accumulation outpaced code change.**

~5,000 lines of plans/specs/audit for ~1,500 lines of code. For trivial PRs (PR8: 2-line edit) this is comically inverted — PR8's plan was 222 lines. The methodology had no fast lane for small changes.

**4. Pyright noise was constant ambient cost.**

15 PRs × ~20 diagnostic lines per session = ~300 false-positive lines I had to evaluate-and-dismiss. Cumulative cognitive load was real. Never addressed at the system level.

**5. The bonus Otel rename grew without being formally added to the audit.**

Surfaced as a code-review comment in PR6. Re-mentioned in PR12 review. Landed in PR15 as the "bonus" item. Never recorded as an audit finding — the audit doc remains incomplete relative to what shipped.

**6. Spec/plan/code update cadence wasn't consistent.**

When PR13 deviated, we updated the spec retroactively. When PR15's file count was wrong, we noted it in the PR body but didn't fix the plan. When PR7 deviated, we documented in commit but not in the sequencing spec. Inconsistent hygiene.

---

## Key insights

**1. The 4-phase methodology has high ceiling but mediocre floor.**

`brainstorm → spec → plan → subagent execute + review` produced excellent results on PRs that warranted it (PR7, PR11, PR13). For trivial PRs (PR8, PR12, PR14), the same methodology consumed disproportionate planning effort for marginal benefit. The plan WAS the diff for several of these.

**2. TDD + two-stage review beats either alone.**

TDD caught implementation errors. Two-stage review caught spec-vs-implementation drift and code-smell issues. Together they caught 5 distinct bug categories. Neither alone would have caught all five.

**3. Subagent dispatch costs real attention, not just tokens.**

Each PR involved 3 subagent dispatches (implement, spec review, quality review) plus 1 user check. That's 4 review surface points per PR × 15 PRs = 60 review events. Worth it in aggregate, but the per-PR overhead is non-trivial.

**4. Reviewers caught what the planner missed.**

Plans aren't self-checking. The reviewers' "verify by reading the actual code" instruction caught implementer-report discrepancies and plan-vs-reality gaps in multiple PRs. Trust-but-verify is not a slogan — it's the only thing that catches lying-to-yourself errors.

**5. User domain knowledge is irreplaceable.**

Every plan deviation that improved on the plan (frozen cascade, UnsetType, no-noqa policy, unreachable-guard cleanup) came from the user. The subagents executed loyally; the user pushed back when loyalty diverged from quality.

**6. Pyright vs ty as a real divergence point.**

The project enforces `ty`. Pyright is unmaintained noise from the IDE. We dismissed Pyright reliably, but the cost was real, and a future contributor would face the same wall. This is technical debt the audit didn't catch.

---

## Action items for next effort

| # | Action | Cost | Priority |
|---|--------|------|----------|
| 1 | Add a "lightweight plan" template for sub-30-LOC PRs. Skip the multi-task structure; one diff + verification step suffices. | Low | Medium |
| 2 | Pre-flight grep verification in every cross-file plan. PR13's cascade hazard would have surfaced at plan time. | Low | High |
| 3 | Resolve Pyright vs ty divergence. Either suppress noise patterns in `pyproject.toml`, document why Pyright is intentionally not enforced, or add Pyright to CI with a strict ignore list. | Medium | Medium |
| 4 | Update audit / sequencing specs in real time as discoveries occur. PR13's cascade and PR15's file count are precedents — going forward, treat spec corrections as part of the PR, not a future cleanup. | Low | High |
| 5 | Record the `# noqa: PLR2004` policy and other emergent conventions in `CLAUDE.md`. PLR2004 policy emerged in PR10; future implementer subagents shouldn't have to be told. | Low | Medium |
| 6 | The "bonus" Otel rename should be backfilled into the audit doc as a tracked finding (LOW-10 or similar). Future readers should see the full set of items the codebase addressed. | Low | Low |
| 7 | Consider whether the two-stage review is needed for every PR. Mechanical fixes (PR8, PR12) likely don't need code quality review beyond spec compliance. Trim where the marginal value is low. | Low | Low |

---

## Closing assessment

The arc shipped what it set out to ship. 3 critical bugs closed, 5 design issues addressed, 7 refactors landed, 50 new tests added, every LOW item cleaned up. No production regressions. The methodology worked.

The methodology was also heavier than the work in places. The next time this team takes on an audit, the lightweight-plan template (action #1) and pre-flight grep (action #2) would meaningfully reduce overhead without giving up the review gates that caught real bugs.

The most underrated factor: the user remained in the loop as a quality reviewer. Without the cascade catch, the UnsetType contribution, the noqa policy, and the unreachable-guard cleanup, the codebase would have shipped a lower-quality version of these 15 PRs. The subagent loop produces consistent execution but does not produce judgment.

---

## Addendum (2026-06-02): PR #107 instrument skip rework

A second large refactor shipped after the original arc closed: PR #107, replacing `InstrumentNotReadyWarning` with `is_configured()` classmethod + structured `skipped_instruments` + summary log. Same methodology (brainstorm → spec → plan → subagent execution). Surfaced three new datapoints worth recording.

### What worked

- **Mid-design pivot to the right pattern.** During brainstorming the user pushed back on `is_configured` taking `bootstrap_config` as an arg ("why does it need it if config is on self?"). That question forced the design conversation through pre-#88 history (instance method + instantiation first) and led to confirming the classmethod-with-arg design was correct. Without the pushback I would have proposed the design without explaining the cascade of constraints.
- **The lightweight template + combined-review pattern (action items #1 and #7 from the original retro) was validated again.** PR16 was the first test; PR #107's combined review structure followed the same pattern even though it didn't end up running formally (the subagent disconnect made the formal review unnecessary — I verified inline).
- **Real-time spec correction (action #4) was honored.** During execution the design pivoted from `_get_logger()` to stdlib `logging` + public `build_summary()` method. A new spec doc (`2026-06-02-stdlib-logging-and-build-summary-design.md`) was written for the pivot rather than letting the doc drift from reality.

### What didn't work

- **Long-running subagent dispatches are fragile.** The implementer dispatch ran ~60 minutes (94 tool uses) before the socket dropped. Work was orphaned mid-flow — the production code edits were done but verification, commit, and docs (Task 9) were not. Recovery worked, but a smaller scope per dispatch would have lost less work.
- **`_get_logger()` was a defensive workaround, not a design.** I introduced it to fix structlog's `cache_logger_on_first_use=True` caching interaction with `capture_logs()` at test time. It made the tests pass but produced an ugly API. The user's subsequent pivot — switch the bootstrapper to stdlib `logging` and expose `build_summary()` as a public method — was the actual right answer. `caplog` (pytest's stdlib-logging capture fixture) was the right test mechanism, which the original plan flagged but the subagent ignored in favor of `capture_logs()`. The lesson: when a fix feels like fighting the framework, the framework choice is probably wrong.
- **LSP violations on framework instrument override parameter types are an emergent pattern.** Three `# ty: ignore[invalid-method-override]` were needed for `FastStreamOpenTelemetryInstrument.is_configured`, `FastStreamPrometheusInstrument.is_configured`, and `LitestarSwaggerInstrument.is_configured` because they narrow `bootstrap_config` to framework-specific types. The pattern was acceptable for `bootstrap_config:` field overrides (covariant) but ty enforces strict invariance on method parameters. Worth noting in CLAUDE.md if more `classmethod` overrides arise.

### Key insight

**The subagent does mechanical migration; design quality comes from human review iteration.** PR #107 needed 5 user follow-up commits after my work to reach the shipped design (`fa135d2`, `41d83bb`, `c14c455`, `4f051d6`, `86b43ef`). Each addressed a quality concern: silent-skip contract test, build_summary docstring tightening, empty-section handling, faststream warning leak fix, `isEnabledFor` guard on the summary log. None of these were in the original plan; all came from review iteration after the mechanical work landed.

This matches the original retro's closing observation. Worth restating concretely: the subagent loop reliably produces a green-tests implementation of the spec, but the spec is rarely the right design. The design emerges during review.

### New action items

| # | Action | Cost | Priority |
|---|--------|------|----------|
| 8 | When a fix requires a defensive workaround in production code to make tests pass, step back and ask whether the test mechanism (or the framework choice) is wrong. `_get_logger()` is the case study. | Low | High |
| 9 | Cap single-dispatch subagent scope. The 94-tool-use, ~60-minute dispatch for PR #107 was too long. Either split into checkpointed sub-dispatches or set an explicit "implement only Tasks N–M, stop and report" boundary so progress doesn't get orphaned if the connection drops. | Low | High |
| 10 | Document the LSP-violation pattern for classmethod overrides in CLAUDE.md alongside the existing covariant-narrowing note. `# ty: ignore[invalid-method-override]` is now established convention. | Low | Low |
