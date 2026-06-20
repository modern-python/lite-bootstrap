---
status: shipped
date: 2026-06-13
slug: portable-planning-convention
summary: Adopt the portable two-axis convention: `architecture/` truth home + `changes/` bundles, per-arc bundling of the audit arcs, fresh Index.
supersedes: null
superseded_by: null
pr: "120"
outcome: "ships in #120 — defines the convention; no architecture/ promotion applies"
---

# Design: Adopt the portable OpenSpec-shaped planning convention

## Summary

Replace `lite-bootstrap`'s ad-hoc `planning/` layout (`specs/` mixing design
specs + audits + retros + sequencing docs, a flat `plans/`, a bespoke
`templates/lightweight-plan-template.md`) with the **portable two-axis
convention** already shipped in `faststream-outbox`: a new `architecture/`
directory at the repo root holds the *living truth* — what the system does now,
one file per capability — and `planning/changes/` holds the *change history*,
each change a self-contained folder bundle, `active/` → `archive/`. Shipping a
change **promotes** its conclusions into the relevant `architecture/<capability>.md`
by hand, then archives the bundle.

The convention prose (`planning/README.md` "Conventions" section) and the three
templates (`_templates/{design,plan,change}.md`) are copied **byte-identical**
from `faststream-outbox`; only the repo-specific "Index" is authored fresh. The
existing `planning/` artifacts are migrated into the new shape: design+plan
pairs become bundles, audits go to `audits/`, retros go to `retros/`,
sequencing docs become the `design.md` of per-arc bundles, and the
lightweight-plan template is deleted in favor of the copied `change.md`.

Because this repo has **no `architecture/` today**, the migration also seeds it
with three capability files drawn from `CLAUDE.md`'s Architecture section and
the existing `docs/integrations/` pages, so promotion has a real target from day
one. `CLAUDE.md`'s `## Planning artifacts` section is rewritten into a
`## Workflow` section naming `architecture/` as the promotion target.

This change touches no runtime code, no test code, and no public API. It is the
`lite-bootstrap` instance of the same convention adopted in `faststream-outbox`
(its `portable-planning-convention`, #77).

## Motivation

`lite-bootstrap`'s `planning/` directory grew organically and now mixes four
distinct artifact kinds in two flat directories, with no convention document and
no living-truth home:

- **`planning/specs/` conflates three things.** It holds actual design specs
  (`*-design.md`), audit findings reports (`bug-refactor-audit.md`,
  `bug-audit-v2.md`), retros (`*-retro.md`), and sequencing docs
  (`*-sequencing.md` — plans-of-plans that order many PRs). A reader cannot tell
  artifact kind from location.

- **`planning/plans/` is a flat pile of ~23 files.** Most are per-PR execution
  plans (`pr1`…`pr16`) spawned by one audit + one sequencing doc, with no
  grouping back to the arc that produced them. The relationship between a
  sequencing doc and its PR plans is implicit.

- **No living-truth home.** The closest thing to "what the system does now" is
  `CLAUDE.md`'s Architecture section, which is AI-instruction prose, not a
  navigable capability reference. There is no step that forces it to stay
  current when behavior changes.

- **No convention document.** There is no `planning/README.md`; the layout is
  undocumented and diverges from the sibling repos (`faststream-outbox`,
  `httpware`, `modern-di`). `faststream-outbox` has already converged on a
  portable convention (#77) designed to drop into the other three repos; this
  change is that adoption for `lite-bootstrap`.

The portable convention resolves all four: it separates living truth
(`architecture/`) from change history (`planning/changes/`), names the
promotion boundary, gives audits/retros/sequencing dedicated homes, and ships a
single documented convention identical across the ecosystem.

## Non-goals

- **Rewriting or trimming archived prose.** Existing shipped specs/plans/audits/
  retros move into the new layout verbatim; only their location and (for bundle
  `design.md` files) frontmatter linkage change.

- **Retrofitting frontmatter onto every historical plan file.** Each migrated
  bundle's `design.md` gets full YAML frontmatter; the grouped per-PR plan files
  inside an arc bundle keep their original prose headers (see Design §4). Adding
  9+ frontmatter blocks to frozen executor checklists is double-entry bookkeeping
  with no payoff for archived material.

- **Authoring exhaustive `architecture/` capability prose.** The three seed files
  capture current truth at the level `CLAUDE.md` + `docs/` already document it.
  They are a real starting point, not a from-scratch system manual; future
  changes deepen them via promotion.

- **Formal OpenSpec spec-deltas.** No `ADDED`/`MODIFIED`/`REMOVED` blocks.
  Promotion is a hand-edit of the affected `architecture/<capability>.md`,
  recoverable via `git log -p`. (Same decision as `faststream-outbox` #77.)

- **An index generator or frontmatter-lint CI job.** The README Index stays
  hand-maintained.

- **Rolling the convention out to `httpware` / `modern-di`.** Out of scope; each
  is separate demand-gated work.

- **mkdocs-serving `planning/` or `architecture/`.** `docs_dir: docs`, so both
  are already excluded from the site; this change does not add them.

## Design

### 1. The model: two axes, never mixed

The convention rests on one distinction, identical to `faststream-outbox`:

> **`architecture/` (repo root) is the present.** One file per capability,
> describing what the system does *now*. Living prose, updated whenever a change
> ships. The truth home and promotion target.
>
> **`planning/changes/` is the past-and-pending.** One folder per change,
> describing how a piece of behavior got (or will get) there. Frozen once
> shipped.

A reader wanting current truth reads `architecture/`; a reader wanting the
rationale follows a promotion back to the archived change bundle. The two spaces
are two top-level homes (`architecture/` at root, `planning/` for history);
naming the boundary — not co-locating — removes the muddle.

### 2. Target directory layout

```
architecture/                      # LIVING TRUTH (new) — promotion target
  config-model.md
  instruments.md
  bootstrappers.md

planning/
  README.md                        # Conventions (byte-identical) + Index (fresh)
  changes/
    active/
      .gitkeep                     # empty after migration (all prior work shipped)
    archive/
      <YYYY-MM-DD.NN-slug>/        # one folder per shipped change
        design.md                  # spec — the thinking            (FULL lane)
        plan.md                    # plan — the sequencing          (FULL lane)
        # OR change.md             # single file                    (LIGHTWEIGHT lane)
  audits/
    2026-05-31-bug-refactor-audit.md
    2026-06-05-bug-audit-v2.md
  retros/
    2026-06-01-audit-implementation-retro.md
    2026-06-05-bug-audit-v2-retro.md
    2026-06-09-docs-and-ci-modern-di-mirror-retro.md
  releases/
    1.1.0.md                       # unchanged
  deferred.md                      # NEW — standard header, "none today"
  _templates/
    design.md  plan.md  change.md  # copied byte-identical from faststream-outbox
```

After migration, `planning/specs/`, `planning/plans/`, and
`planning/templates/` no longer exist.

### 3. `architecture/` seed — three capability files

This repo has no `architecture/` today, so the migration creates it and seeds
three capability files. Content is drawn from `CLAUDE.md`'s Architecture section
(core pattern, key design decisions, module layout) and the existing
`docs/integrations/` pages — internal capability truth, written as living prose
with **no frontmatter** (dated by git):

- **`architecture/config-model.md`** — `BaseConfig` (frozen, `kw_only`
  dataclasses); the `from_dict` vs `from_object` None-handling asymmetry;
  `UnsetType` / `UNSET` sentinel and the `FastAPIConfig.application`
  construction; the `__post_init__` cascade invariant (every config
  `__post_init__` calls `super().__post_init__()`; `BaseConfig` terminates the
  chain).

- **`architecture/instruments.md`** — `BaseInstrument[ConfigT]` generic,
  non-frozen dataclass with slots; lifecycle via `bootstrap()` / `teardown()`;
  skip check via `is_configured()`; the instrument catalog (logging,
  opentelemetry, sentry, prometheus/metrics, pyroscope, cors, swagger, health);
  optional-dependency guard (`import_checker.is_X_installed`); the logging↔Sentry
  and OTel↔logging integrations; the OpenTelemetry single-instance-per-process
  constraint.

- **`architecture/bootstrappers.md`** — `BaseBootstrapper` (abc) and the five
  framework bootstrappers (FastAPI, Litestar, FastStream, FastMcp, Free); the
  instrument registry; `is_configured → check_dependencies → instantiate`
  ordering with `skipped_instruments`; reverse-order idempotent teardown; the
  `build_summary()` log line; the `_lite_bootstrap_*` app-tagging sentinel
  convention.

Three cohesive files are the starting granularity; finer splits (e.g. one file
per instrument) can come later via normal changes.

### 4. Migration mapping

#### 4a. Clean design+plan pairs → one full bundle each

Each existing `*-design.md` + its matching plan becomes a bundle under
`changes/`:

| Bundle | design.md ← | plan.md ← |
|--------|-------------|-----------|
| `…-fastmcp-bootstrapper/` | `specs/2026-06-01-fastmcp-bootstrapper-design.md` | `plans/2026-06-01-fastmcp-bootstrapper.md` |
| `…-instrument-skip-rework/` | `specs/2026-06-01-instrument-skip-rework-design.md` | `plans/2026-06-01-instrument-skip-rework.md` |
| `…-stdlib-logging-and-build-summary/` | `specs/2026-06-02-stdlib-logging-and-build-summary-design.md` | `plans/2026-06-02-stdlib-logging-and-build-summary.md` |
| `…-mkdocs-github-pages/` | `specs/2026-06-09-mkdocs-github-actions-design.md` | `plans/2026-06-09-mkdocs-github-actions-plan.md` |

#### 4b. Audit arcs → per-arc bundle

An audit arc is `1 audit → 1 sequencing doc → many PR plans`. Per-arc bundling:
the **sequencing doc becomes the bundle's `design.md`** (it is the design-level
"why this set of PRs, in this order"); the wave's per-PR execution plans are
grouped into the same folder as `plan-prN-<slug>.md`; the audit findings report
goes to `audits/` and the retro to `retros/`.

| Bundle | design.md ← (sequencing) | grouped per-PR plans (← `plans/`) |
|--------|--------------------------|-----------------------------------|
| `2026-05-31.NN-audit-implementation/` | `audit-implementation-sequencing.md` | `pr1-crit1-redoc-root-path`, `pr2-crit2-otel-shutdown`, `pr3-crit3-idempotent-teardown`, `pr4-des4-des5-small-cleanups`, `pr5-des3-config-method-semantics`, `pr6-des2-otel-fields-mixin`, `pr7-des1-generic-instruments` |
| `2026-06-01.NN-deferred-refactors/` | `deferred-refactors-sequencing.md` | `pr8-low-1-2-sentry-micro`, `pr9-otel-touch-ups`, `pr10-test-gap-fill`, `pr11-logging-cleanup`, `pr12-base-layer-cleanup`, `pr13-frozen-setattr`, `pr14-faststream-timeout`, `pr15-naming-pass`, `pr16-post-retro-hygiene` |
| `2026-06-05.NN-bug-audit-v2/` | `bug-audit-v2-sequencing.md` | `pr1-lifecycle`, `pr2-config-security`, `pr3-hygiene-ci` |

Parent audits → `audits/`:
- `specs/2026-05-31-bug-refactor-audit.md` → `audits/2026-05-31-bug-refactor-audit.md`
- `specs/2026-06-05-bug-audit-v2.md` → `audits/2026-06-05-bug-audit-v2.md`

Retros → `retros/`:
- `specs/2026-06-01-audit-implementation-retro.md` → `retros/2026-06-01-audit-implementation-retro.md`
- `specs/2026-06-05-bug-audit-v2-retro.md` → `retros/2026-06-05-bug-audit-v2-retro.md`
- `specs/2026-06-09-docs-and-ci-modern-di-mirror-retro.md` → `retros/2026-06-09-docs-and-ci-modern-di-mirror-retro.md`

#### 4c. `.NN` assignment and frontmatter

- **`.NN`** (zero-padded intra-day counter) is assigned by **merge order** per
  date; PR numbers referenced in the existing docs give the order. Where two
  bundles share a date (notably `2026-06-01`, which has `instrument-skip-rework`,
  `fastmcp-bootstrapper`, and `deferred-refactors`), `.01`/`.02`/`.03` break the
  tie. A cosmetic mis-order is harmless — both bundles still exist and sort
  adjacently. Exact `.NN` values are assigned in the implementation plan.

- **Frontmatter (pragmatic retrofit):** each bundle's `design.md` gets full YAML
  frontmatter (`status: shipped`, `date`, `slug`, `supersedes`/`superseded_by`,
  `pr`, `outcome`). For clean-pair bundles, `plan.md` gets `plan.md` frontmatter.
  The **grouped per-PR plan files inside arc bundles keep their original prose
  headers** — they are frozen executor checklists, and the bundle's `design.md`
  carries the lifecycle metadata for the whole arc. This is a deliberate scope
  cut (see Non-goals): we do not author 9+ new frontmatter blocks for archived
  checklists. `instrument-skip-rework` is partially superseded by
  `stdlib-logging-and-build-summary`; that linkage is preserved via
  `supersedes`/`superseded_by` on the two `design.md` files.

#### 4d. Other moves

- `planning/templates/lightweight-plan-template.md` → **deleted** (superseded by
  the copied `_templates/change.md`).
- `planning/releases/1.1.0.md` → **unchanged**, stays at `planning/releases/`.
- `git mv` is used throughout to preserve blame.

### 5. The convention doc (`planning/README.md`)

Two sections:

1. **Conventions** — copied **byte-identical** from
   `faststream-outbox/planning/README.md` (the two-axis model, change-bundle
   identity, three lanes, frontmatter schema, audits/retros/releases/deferred/
   templates). This is the portable core, identical across repos. The only edit
   is to the prose that names this repo's truth home where the abstract
   "truth home" needs a concrete instance — kept consistent with how
   `faststream-outbox` references its own `architecture/`.
2. **Index** — authored **fresh** for `lite-bootstrap`. Lists Active (none after
   migration) and Archived (all migrated bundles, one line each with PR + date),
   plus an "Other" pointer block to `architecture/` (the promotion target),
   `audits/`, and `retros/`.

### 6. Three ceremony lanes (carried in the Conventions section)

| Lane | Artifact(s) | Use when |
|------|-------------|----------|
| **Full** | `design.md` + `plan.md` | design judgment; new file/module; public-API change; cross-cutting/multi-file; non-trivial test design |
| **Lightweight** | `change.md` | small-but-real: ≲30 LOC net, ≤2 files, no new file, no public-API change, single straightforward test |
| **Tiny** | none — conventional commit | typo, dep bump, linter/formatter/CI tweak, mechanical rename, single-line config |

Heavier lane wins on ambiguity. A `change.md` that outgrows its lane splits into
`design.md` + `plan.md`.

### 7. `_templates/`

Copy all three template files byte-identical from
`faststream-outbox/planning/_templates/`: `design.md`, `plan.md`, `change.md`.
Their `changes/active/` path references are already correct for this layout.

### 8. `CLAUDE.md` update

This repo's `CLAUDE.md` has a `## Planning artifacts` section (not a
`## Workflow` section). Rewrite it into a `## Workflow` section mirroring
`faststream-outbox`:

1. Per-feature pipeline: brainstorming → spec in
   `planning/changes/active/YYYY-MM-DD.NN-<slug>/design.md` → writing-plans →
   `plan.md` → executing-plans / subagent-driven-development →
   requesting-code-review → finishing-a-development-branch.
2. On merge: bundle moves to `planning/changes/` with `status: shipped`,
   `pr:`, `outcome:` filled, **and the change promotes its conclusions into the
   affected `architecture/<capability>.md`** — name `architecture/` explicitly as
   the promotion target.
3. The spec/plan/architecture artifact-boundary paragraph.
4. The three-lane paragraph.
5. Pointers to `planning/README.md` and `planning/_templates/`.

The `## Architecture` section's existing pointers are untouched. The "Planning
artifacts" content that still applies (the `planning/specs/` vs `planning/plans/`
distinction) is replaced wholesale by the new convention.

### 9. justfile — add `docs-build`

The convention's Testing step references `just docs-build`, but this repo's
justfile has only `docs-deploy` (gh-deploy). Add a check-only target:

```
docs-build:
    uvx --with-requirements docs/requirements.txt mkdocs build --strict
```

Small and optional; makes the verification step repeatable and matches
`faststream-outbox`.

### 10. `deferred.md`

Create `planning/deferred.md` with the standard header (copied from
`faststream-outbox`, adapted), recording that there are **no deferred items
today**. It is the long-tail register of real-but-unscheduled items with revisit
triggers; items graduate from here into `changes/active/` bundles.

### 11. Dogfood — this change is its own bundle

This adoption is itself a change, so it lands as
`planning/changes/active/2026-06-13.01-portable-planning-convention/`:

- This `design.md` is written there now (during brainstorming) — the first use
  of the new layout.
- The implementation plan is written to `plan.md` in the same folder.
- On merge, the bundle moves to `changes/` with `status: shipped`,
  `pr:`, `outcome:` filled, and its line moves to Archived in the README Index.
  No `architecture/` promotion applies — this change defines the convention
  (which lives in `README.md`) and seeds `architecture/`, rather than altering a
  library capability.

## Operations

None. No DNS, infra, or external-account changes. Pure in-repo file moves, new
files, and doc edits.

## Testing

No code touched, so correctness is verified by:

- `just lint-ci` passes (eof-fixer + ruff format/check in check mode + ty; the
  markdown/format gate, since no Python changes).
- `just docs-build` (`mkdocs build --strict`) passes. `architecture/` is outside
  `docs_dir: docs`, so it is not part of the site build; the strict build only
  re-validates the existing `docs/` tree, which this change leaves untouched.
- Repo-wide grep sweeps return zero stale references:
  - `grep -rn "planning/specs"` — none outside this bundle's own prose.
  - `grep -rn "planning/plans"` — none.
  - `grep -rn "lightweight-plan-template"` — none.
- Every `planning/changes/**/design.md` and `plan.md` (clean-pair) has parseable
  YAML frontmatter — spot-checked on review.
- `planning/README.md` Conventions section is byte-identical to
  `faststream-outbox` (diff -w shows only the Index and any deliberate truth-home
  reference) — verified with `diff`.
- `planning/README.md` Index links resolve — manual click-through.
- The post-migration tree matches §2 exactly; `planning/specs/`,
  `planning/plans/`, `planning/templates/` are gone.

No new pytest, no new CI job.

## Risk

- **`.NN` ordering for same-date bundles is a judgment call.** `2026-06-01` has
  three bundles. *Mitigation:* PR numbers in the existing docs give merge order;
  a wrong tiebreak is cosmetic (bundles sort adjacently regardless).

- **`architecture/` seed drifts from reality immediately.** Hand-written seed
  prose can lag the code the moment it lands. *Mitigation:* the seed is sourced
  from `CLAUDE.md` + `docs/`, which are current; and the convention forces
  promotion on every future change, which is the mechanism that keeps it true.
  An imperfect-but-real seed is strictly better than an empty truth home.

- **`git mv` blame continuity through folder regrouping.** *Mitigation:*
  `git log --follow` and GitHub web both follow renames; low practical impact
  for planning artifacts.

- **Convention drift on the next change.** A contributor could skip the lanes or
  forget the `architecture/` promotion. *Mitigation:* `CLAUDE.md` names
  `architecture/` as the promotion target so PR review catches a missing
  promotion the way it catches a missing test; templates make the shape
  copy-pasteable.

- **Grouped per-PR plan files lack frontmatter.** A future tooling pass that
  assumes every plan file has frontmatter would skip them. *Mitigation:* this is
  an accepted, documented scope cut (Non-goals); the bundle `design.md` carries
  the arc's lifecycle metadata, and no such tooling exists or is planned.
