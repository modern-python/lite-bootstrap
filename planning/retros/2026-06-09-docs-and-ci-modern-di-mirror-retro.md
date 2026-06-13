# Retrospective: docs + CI mirror of modern-di (PRs #112–#115)

Date: 2026-06-09
Scope: One-session sequence of four PRs that brought lite-bootstrap's docs publishing and CI shape into alignment with the sibling [`modern-di`](https://github.com/modern-python/modern-di) project.

## What shipped

| PR | Title | Size |
|---|---|---|
| [#112](https://github.com/modern-python/lite-bootstrap/pull/112) | docs: migrate from Read the Docs to GitHub Actions + Pages | 9 commits, ~200 lines (+ spec + plan) |
| [#113](https://github.com/modern-python/lite-bootstrap/pull/113) | ci: bump action pins to match modern-di | 9 lines |
| [#114](https://github.com/modern-python/lite-bootstrap/pull/114) | ci: drop codecov upload step | 7 lines |
| [#115](https://github.com/modern-python/lite-bootstrap/pull/115) | ci: split ci.yml into reusable `_checks.yml` | 36 → 14 + new 39 |

End state: `ci.yml`, `_checks.yml`, `docs.yml`, the `docs-deploy` Justfile recipe, `mkdocs.yml site_url`, and `docs/CNAME` are all byte-identical to modern-di's equivalents. `lite-bootstrap.modern-python.org` is live with TLS.

## What went well

- **"Mirror modern-di" as a scope anchor.** Every micro-decision (action versions, paths filter, concurrency group, recipe text) collapsed from "design choice" to "match or deviate." Verbatim copies + a literal `diff` against the reference were the strongest possible correctness signal — caught divergence at the byte level, not the behaviour level.
- **Out-of-scope sections paid off across PRs.** PR #112's spec deliberately listed 3 deferred items (action bumps, codecov decision, structural split). Each became a tight, focused follow-up PR with its scope and rationale already half-written. The user didn't have to re-explain what they wanted.
- **The brainstorming → spec → plan → execute pipeline collapsed user decision points.** User approved once at brainstorm ("yes, that domain"), once at spec ("write the plan"), once at execution mode ("subagent-driven"). No back-and-forth mid-implementation; the gates caught misunderstandings before code was touched.
- **Operator follow-up checklist in the PR body was load-bearing.** Most of the post-merge "operator actions" listed in PR #112 (DNS, Pages enable, HTTPS cert) turned out to already be done or auto-triggered by the merge — we only discovered this because the checklist forced us to verify each item explicitly. Without the checklist we'd have asked the maintainer to do work that didn't need doing.
- **Spec gap caught by the grep step.** Task 6's "find any remaining `readthedocs.io` references outside `planning/`" caught 6 README links the spec had missed. Cost: one extra commit. Saved: a broken-link PR landing in main.
- **Final-branch code review surfaced zero issues.** Not because the reviewer was lenient — because the byte-identical-to-modern-di constraint left almost no room for error. This is a good signal that the scope anchor worked.

## What didn't go well

- **Subagent-driven workflow was over-engineered for trivial config edits.** The skill prescribes implementer + spec reviewer + code reviewer per task. For 4-line verbatim copies, that's 3× the overhead with no quality signal. I caught this after Task 1 and switched to "implementer subagent + direct controller verification + single final review across the branch." Should have noticed earlier and stated the deviation up front instead of mid-flight.
- **Heredoc backtick escaping bug, twice.** With `<<'EOF'` (quoted delimiter), backticks are preserved literally — no escape needed. I escaped them anyway in the plan's gh-pr-create heredoc (caught during plan self-review) AND in the live PR #112 body (had to `gh pr edit` after creation). Same mistake within the same session is the smell of an unincorporated lesson.
- **Spec missed the README.** "Migrate the docs URL" should have triggered an automatic "grep the whole repo for the old URL" check at the design stage, not as a Task 6 side effect. The plan's grep step caught it, but only because the grep happened to include `--include='*.md'`. If the migration had touched a non-Markdown file (e.g., a config YAML referencing the old domain), the spec's narrow file list would have missed it.
- **Confusing implementer report on Task 6.** The Task 6 implementer reported `exit=1, no matches` from the grep AND listed 6 README references they "found before reverting edits." Two different searches conflated in one report. Cost: 30 seconds of confusion verifying directly. Tighter implementer prompt could have asked for the grep output verbatim and clearer "what I changed vs. what I considered changing."
- **Spec + plan committed to local `main` instead of the feature branch.** Working out fine because main was only ahead of origin/main; the commits came along on the feature branch and rode the PR cleanly. But the right pattern is: branch first, then commit spec/plan on the branch. Mid-session I would not have been able to abandon the work without git surgery.
- **Auto-mode classifier false-positive on `gh repo view --json homepageUrl`.** A read-only query (`--json` extracting a field) was flagged as a "homepage change" by keyword match. Trivial cost, but worth noting that the classifier can over-block on harmless reads.

## What I'd do differently next time

1. **For URL migrations**, treat "grep entire repo for old URL" as a pre-implementation design step. Add a `grep -rn <old-url> .` to the spec's "current state" section. Then every reference is in the changeset from day one.
2. **Calibrate subagent overhead up front.** When tasks are mechanical verbatim edits, dispatch implementer-only with the controller verifying directly; reserve per-task spec/quality reviewers for tasks with non-trivial design choices. State this calibration in the controller's first message of the execution skill, not after the first task.
3. **Internalize heredoc rules.** With `<<'EOF'`, no escapes. With `<<EOF`, escapes for `$` and `` ` ``. The third time would be unforgivable.
4. **Branch before committing planning artifacts.** A new branch costs nothing; a misplaced commit on main is annoying to clean up if the work doesn't land.
5. **Consider bundling closely related small PRs.** Splitting PRs #113, #114, #115 was clean for git history and reviewability, but bundled as one "align CI with modern-di" PR they would have been ~30 lines total — borderline-trivial to review as a unit. Defensible either way; worth being explicit about the trade-off rather than defaulting to split.

## Process metrics

- **Wall-clock**: brainstorm → all 4 PRs merged in ~75 minutes.
- **PR review latency**: user merged each PR within ~1–2 minutes of opening. This kept the cadence tight and let later PRs build on merged state instead of stacked branches.
- **Failed CI runs**: zero across all four PRs.
- **Bytes changed in production code** (excluding spec/plan/retro): ~75 net new lines + ~50 removed.

## Memory / convention deltas

None worth memorising. The strongest takeaways (heredoc backticks, URL-migration grep step) are general execution lessons rather than facts about this project. The retro file itself stays as the durable artifact.
