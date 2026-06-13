# Planning

Specs, plans, and change history for `lite-bootstrap`. The living truth
about *what the system does now* lives in [`architecture/`](../architecture/)
at the repo root; this directory records *how it got there*.

## Conventions

> This section is the portable convention — identical across the
> modern-python repos. The Index below is repo-specific. To adopt elsewhere,
> copy this section plus [`_templates/`](_templates/) and point that repo's
> `CLAUDE.md` Workflow + truth home at it.

### Two axes, never mixed

- **`architecture/` (repo root) — the present.** One file per capability,
  living prose, updated whenever a change ships. The truth home.
- **`planning/changes/` — the past-and-pending.** One folder per change,
  frozen once shipped.

Shipping a change **promotes** its conclusions into the affected
`architecture/<capability>.md` by hand, then archives the bundle. That
hand-edit is what keeps `architecture/` true; the archived bundle carries the
*why*.

### Change bundles

A change is a folder `changes/active/YYYY-MM-DD.NN-<slug>/`:

- `YYYY-MM-DD` — proposal date; `.NN` — zero-padded intra-day counter
  (`.01`, `.02`, …) that breaks same-date ties so the timeline sorts stably.
- `<slug>` — kebab-case description, not a story ID.

On merge the folder moves to `changes/archive/` with `status: shipped`, `pr:`,
and `outcome:` filled, and its line moves from **Active** to **Archived** in
the Index below.

### Three lanes

| Lane | Artifacts | Use when |
|------|-----------|----------|
| **Full** | `design.md` + `plan.md` | design judgment; new file/module; public-API change; cross-cutting/multi-file; non-trivial test design |
| **Lightweight** | `change.md` | small-but-real: ≲30 LOC net, ≤2 files, no new file, no public-API change, single straightforward test |
| **Tiny** | none — conventional commit | typo, dep bump, linter/formatter/CI tweak, mechanical rename, single-line config |

Heavier lane wins on ambiguity. A `change.md` that outgrows its lane splits
into `design.md` + `plan.md`.

### Artifacts at a glance

- **`design.md`** — the spec: the *thinking* (why, design, trade-offs, scope).
- **`plan.md`** — the plan: the *sequencing* (the executor's task checklist).
- **`change.md`** — both, condensed, for the lightweight lane.
- **`releases/<semver>.md`** — per-release user-facing notes.
- **`audits/<date>-<slug>.md`** — findings from a code/docs/bug-hunt sweep;
  spawns fix changes.
- **`retros/<date>-<slug>.md`** — what we learned after a body of work.
- **`deferred.md`** — real-but-unscheduled items, each with a revisit trigger.

Templates live in [`_templates/`](_templates/).

### Frontmatter

`design.md` / `change.md`: `status` (draft|approved|shipped|superseded),
`date`, `slug`, `supersedes`, `superseded_by`, `pr`, `outcome`.
`plan.md`: `status`, `date`, `slug`, `spec`, `pr`. Files in `architecture/`
carry **no** frontmatter — living prose, dated by git.

## Index

### Active

- **[portable-planning-convention](changes/active/2026-06-13.01-portable-planning-convention/design.md)**
  (2026-06-13) — Adopt the portable two-axis convention: `architecture/` truth
  home + `changes/` bundles, per-arc bundling of the audit arcs, fresh Index.
  *This change.*

### Archived (shipped)

- **[mkdocs-github-pages](changes/archive/2026-06-09.01-mkdocs-github-pages/design.md)**
  (#112–#115, 2026-06-09) — Docs hosting moved from Read the Docs to GitHub
  Actions + Pages.
- **[bug-audit-v2](changes/archive/2026-06-05.01-bug-audit-v2/design.md)**
  (#108–#110, 2026-06-05) — 26 findings (UX · logic · security · tests) shipped
  across three themed PRs.
- **[deferred-refactors](changes/archive/2026-06-01.03-deferred-refactors/design.md)**
  (#96–#103, 2026-06-01) — The 20 deferred items from the 2026-05-31 audit
  (REF/TEST/LOW) across eight PRs.
- **[fastmcp-bootstrapper](changes/archive/2026-06-01.02-fastmcp-bootstrapper/design.md)**
  (2026-06-01) — New `FastMcpBootstrapper` mirroring microbootstrap's fastmcp
  support.
- **[instrument-skip-rework](changes/archive/2026-06-01.01-instrument-skip-rework/design.md)**
  (2026-06-01) — Replace `InstrumentNotReadyWarning` with a pre-instantiation
  config check + summary log. *Partially superseded by
  [stdlib-logging-and-build-summary](changes/archive/2026-06-02.01-stdlib-logging-and-build-summary/design.md).*
- **[stdlib-logging-and-build-summary](changes/archive/2026-06-02.01-stdlib-logging-and-build-summary/design.md)**
  (#107, 2026-06-02) — Stdlib `logging` in `bootstrappers/base.py` + public
  `build_summary()`.
- **[audit-implementation](changes/archive/2026-05-31.01-audit-implementation/design.md)**
  (#89–#95, 2026-05-31) — Criticals (CRIT-1..3) + design issues (DES-1..5) +
  paired tests across seven sequenced PRs.

## Other

- **[`architecture/`](../architecture/)** at the repo root — the living
  capability truth (config model, instruments, bootstrappers). The promotion
  target on every ship.
- **[audits/](audits/)** — findings reports (2026-05-31 bug+refactor audit,
  2026-06-05 bug audit v2).
- **[retros/](retros/)** — what we learned after a body of work.
- **[deferred.md](deferred.md)** — the long-tail register of real-but-
  unscheduled items with revisit triggers.
