# Planning

Specs, plans, and change history for `lite-bootstrap`. The living truth
about *what the system does now* lives in [`architecture/`](../architecture/)
at the repo root; this directory records *how it got there*.

## Conventions

> This section is the portable convention, sourced from the canonical repo
> [`lesnik512/planning-convention`](https://github.com/lesnik512/planning-convention)
> (applied version in [`.convention-version`](.convention-version)). To update
> it, run that repo's `APPLY.md` flow. The generated change index (`just index`)
> and the `## Other` pointers below are repo-local.

### Two axes, never mixed

- **`architecture/` (repo root) — the present.** One file per capability,
  living prose, updated in the same PR that ships the change. The truth home.
- **`planning/changes/` — the past-and-pending.** One folder per change,
  kept in place after ship.

A change **promotes** its conclusions into the affected
`architecture/<capability>.md` by hand **in the implementing PR, alongside the
code** — the edit rides in the same diff and is reviewed with it, never applied
as a separate post-merge step. That hand-edit is what keeps `architecture/`
true; the bundle stays in `changes/` as the *why*.

### Change bundles

A change is a folder `changes/YYYY-MM-DD.NN-<slug>/`:

- `YYYY-MM-DD` — proposal date; `.NN` — zero-padded intra-day counter
  (`.01`, `.02`, …) that breaks same-date ties so the timeline sorts stably.
- `<slug>` — kebab-case description, not a story ID.

`summary` is written when the change is created (the intent one-liner) and
**finalized at ship** to state the realized result — set in the implementing
PR, alongside the code and the `architecture/` promotion. No post-merge
bookkeeping, no folder move. `date` and `slug` are never written — they are
read from the bundle's directory name.

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
- **`decisions/<YYYY-MM-DD>-<slug>.md`** — one file per design decision taken
  (especially options *rejected*), each with a revisit trigger, so reviews don't
  re-litigate them; listed by `just index`.
- **`releases/<semver>.md`** — per-release user-facing notes.
- **`audits/<date>-<slug>.md`** — findings from a code/docs/bug-hunt sweep;
  spawns fix changes.
- **`retros/<date>-<slug>.md`** — what we learned after a body of work.
- **`deferred.md`** — real-but-unscheduled items, each with a revisit trigger.

Templates live in [`_templates/`](_templates/).

### Frontmatter

`date` and `slug` are **derived from the directory / file name** — never
repeated in frontmatter. So:

- `design.md` / `change.md`: `summary` (single line) only.
- `plan.md`: **no frontmatter** — its identity is the bundle directory.
- `decisions/*.md`: `status` (accepted|superseded), `summary`, and optional
  `supersedes` / `superseded_by`.
- Files in `architecture/` carry **no** frontmatter — living prose, dated by git.

**`summary`** is one line: written at creation as the intent, then **finalized
at ship** to state the realized result — what shipped and its effect. It is the
only field the index renders.

## Index

The listing is **generated**, not maintained — run `just index` to print it:
changes flat, newest-first, then decisions newest-first. The frontmatter in
each bundle / decision file is the single source of truth; there is no
committed copy to drift.

## Other

- **[`architecture/`](../architecture/)** at the repo root — the living
  capability truth (config model, instruments, bootstrappers). The promotion
  target on every ship.
- **[decisions/](decisions/)** — design decisions taken (and alternatives
  rejected), each with a revisit trigger, so reviews don't re-litigate them;
  indexed by `just index`.
- **[audits/](audits/)** — findings reports (2026-05-31 bug+refactor audit,
  2026-06-05 bug audit v2).
- **[retros/](retros/)** — what we learned after a body of work.
- **[deferred.md](deferred.md)** — the long-tail register of real-but-
  unscheduled items with revisit triggers.
