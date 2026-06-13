---
status: draft
date: 2026-06-13
slug: portable-planning-convention
spec: portable-planning-convention
pr: null
---

# Portable planning convention — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate `lite-bootstrap`'s `planning/` to the portable two-axis
convention from `faststream-outbox` — `architecture/` truth home +
`planning/changes/` bundles — and seed the truth home.

**Spec:** [`design.md`](./design.md)

**Architecture:** Pure file moves + new docs. Create `architecture/` (3 seed
files), restructure `planning/` into `changes/{active,archive}/` bundles +
`audits/` + `retros/`, copy the portable README Conventions + templates
byte-identical from `faststream-outbox`, author a fresh Index, and rewrite
`CLAUDE.md`'s planning section. No runtime/test/API code is touched.

**Tech Stack:** Markdown, `git mv`, `just lint-ci`, `mkdocs build --strict`.

**Branch:** `docs/portable-planning-convention` (already created; the spec is
already committed there).

**Source repo (copy-from):** `/Users/kevinsmith/src/pypi/faststream-outbox`.

**Commit strategy:** Per-task commits.

**`.NN` assignment (final, by merge order; cosmetic for archived material):**

| Bundle id | design.md source | grouped plans / pair plan |
|-----------|------------------|---------------------------|
| `2026-05-31.01-audit-implementation` | `audit-implementation-sequencing.md` | `pr1-crit1`…`pr7-des1` (#89–95) |
| `2026-06-01.01-instrument-skip-rework` | `instrument-skip-rework-design.md` | `instrument-skip-rework.md` |
| `2026-06-01.02-fastmcp-bootstrapper` | `fastmcp-bootstrapper-design.md` | `fastmcp-bootstrapper.md` |
| `2026-06-01.03-deferred-refactors` | `deferred-refactors-sequencing.md` | `pr8-low`…`pr16-post-retro-hygiene` (#96–103) |
| `2026-06-02.01-stdlib-logging-and-build-summary` | `stdlib-logging-and-build-summary-design.md` | `stdlib-logging-and-build-summary.md` (#107) |
| `2026-06-05.01-bug-audit-v2` | `bug-audit-v2-sequencing.md` | `pr1-lifecycle`, `pr2-config-security`, `pr3-hygiene-ci` (#108–110) |
| `2026-06-09.01-mkdocs-github-pages` | `mkdocs-github-actions-design.md` | `mkdocs-github-actions-plan.md` (docs+CI arc #112–115) |

---

### Task 1: Scaffold the new `planning/` skeleton + copy templates

**Files:**
- Create: `planning/changes/active/.gitkeep`, `planning/changes/archive/` (via bundles later)
- Create: `planning/audits/`, `planning/retros/`
- Create: `planning/_templates/{design,plan,change}.md` (copied byte-identical)
- Create: `planning/deferred.md`

- [ ] **Step 0: Remove the stray `plan.md` ignore rule**

  `.gitignore` line 22 ignores the literal filename `plan.md` — it collides with
  every change bundle's `plan.md` under the new convention (the old flat plans
  escaped only because they were named `YYYY-MM-DD-prN-*.md`). The sibling
  `faststream-outbox` repo does not ignore it. Delete the line:

  ```bash
  cd /Users/kevinsmith/src/pypi/lite-bootstrap
  git rm --cached --ignore-unmatch -q -- plan.md 2>/dev/null || true   # no-op; nothing tracked
  sed -i '' '/^plan\.md$/d' .gitignore
  git check-ignore planning/changes/active/2026-06-13.01-portable-planning-convention/plan.md && echo "STILL IGNORED (bad)" || echo "plan.md no longer ignored"
  ```
  Expected: `plan.md no longer ignored`.

- [ ] **Step 1: Create the directory skeleton**

  ```bash
  cd /Users/kevinsmith/src/pypi/lite-bootstrap
  mkdir -p planning/changes/active planning/changes/archive planning/audits planning/retros planning/_templates
  touch planning/changes/active/.gitkeep
  ```

- [ ] **Step 2: Copy the three templates byte-identical**

  ```bash
  cp /Users/kevinsmith/src/pypi/faststream-outbox/planning/_templates/design.md planning/_templates/design.md
  cp /Users/kevinsmith/src/pypi/faststream-outbox/planning/_templates/plan.md   planning/_templates/plan.md
  cp /Users/kevinsmith/src/pypi/faststream-outbox/planning/_templates/change.md planning/_templates/change.md
  ```

- [ ] **Step 3: Verify templates are byte-identical**

  Run:
  ```bash
  diff /Users/kevinsmith/src/pypi/faststream-outbox/planning/_templates/design.md planning/_templates/design.md \
    && diff /Users/kevinsmith/src/pypi/faststream-outbox/planning/_templates/plan.md planning/_templates/plan.md \
    && diff /Users/kevinsmith/src/pypi/faststream-outbox/planning/_templates/change.md planning/_templates/change.md \
    && echo "TEMPLATES IDENTICAL"
  ```
  Expected: `TEMPLATES IDENTICAL` (no diff output).

- [ ] **Step 4: Create `planning/deferred.md`**

  Write `planning/deferred.md` with the standard header, adapted to this repo
  (no items today):

  ```markdown
  # Deferred Work

  Items raised in reviews or audits that are real but not actionable now.
  Each is parked here with the reason it's deferred and the concrete trigger
  that should bring it back. This is the long-tail register — not a backlog
  of planned work. When an item is picked up it graduates to a spec/plan
  bundle in [`changes/active/`](changes/active/); see [CLAUDE.md](../CLAUDE.md#workflow).

  ## Open

  _None._
  ```

- [ ] **Step 5: Commit**

  ```bash
  git add planning/changes planning/audits planning/retros planning/_templates planning/deferred.md
  git commit -m "docs(planning): scaffold changes/audits/retros/_templates skeleton

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 2: Seed `architecture/` truth home (3 capability files)

**Files:**
- Create: `architecture/config-model.md`
- Create: `architecture/instruments.md`
- Create: `architecture/bootstrappers.md`

**Sources to synthesize from:** `CLAUDE.md` (`## Architecture` → Core pattern,
Key design decisions, Module layout) and `docs/integrations/*.md`. Living prose,
**no frontmatter** (dated by git). Keep each file to the invariants a reader
needs to understand the capability *now* — not change history.

- [ ] **Step 1: Write `architecture/config-model.md`**

  Sections to cover (synthesize from CLAUDE.md "Frozen configs…", "FastAPIConfig…",
  "from_dict vs from_object", "__post_init__ cascade" bullets + `docs/introduction/configuration.md`):
  - `BaseConfig` — frozen, `kw_only` dataclass; framework configs compose
    instrument configs via multiple inheritance.
  - `from_dict` vs `from_object` — the `None`-handling asymmetry (explicit-None
    override vs attribute filtering), with the one-line example.
  - `UnsetType` / `UNSET` sentinel (`lite_bootstrap/types.py`) and the
    `FastAPIConfig.application` construction in `__post_init__` (frozen bypass via
    `object.__setattr__`).
  - The `__post_init__` cascade invariant (every config `__post_init__` calls
    `super().__post_init__()`; `BaseConfig` is the no-op terminator; the
    `super(FastAPIConfig, self)` form under `slots=True`).

- [ ] **Step 2: Write `architecture/instruments.md`**

  Sections (synthesize from CLAUDE.md "Optional dependencies", "Frozen configs/
  non-frozen instruments", "Logging↔Sentry", "OTel↔Logging", "OpenTelemetryInstrument
  single-instance", "Module layout"):
  - `BaseInstrument[ConfigT]` — generic, non-frozen dataclass with slots; lifecycle
    via `bootstrap()` / `teardown()`; skip check via `is_configured()`.
  - The instrument catalog (logging, opentelemetry, sentry, prometheus/metrics,
    pyroscope, cors, swagger, health) and `logging_factory.py` split-out.
  - Optional-dependency guard (`import_checker.is_X_installed`,
    `importlib.util.find_spec`); why instruments lose `frozen=True`.
  - Cross-instrument integrations: logging↔Sentry (`before_send` chaining,
    `skip_sentry`), OTel↔logging (span/trace-id injection).
  - OpenTelemetry single-instance-per-process constraint (set-once tracer provider;
    teardown flushes but cannot reset the global).

- [ ] **Step 3: Write `architecture/bootstrappers.md`**

  Sections (synthesize from CLAUDE.md "Core pattern", "Instrument skip ordering",
  "Instrument registry", "Idempotent teardown", "_lite_bootstrap_* prefix" +
  `docs/integrations/*.md`):
  - `BaseBootstrapper` (abc) + the five bootstrappers (FastAPI, Litestar,
    FastStream, FastMcp, Free).
  - Skip ordering: `is_configured` → `check_dependencies` → instantiate;
    `skipped_instruments`; `InstrumentDependencyMissingWarning`.
  - Instrument registry: `bootstrap()` in order, `teardown()` in reverse;
    idempotent teardown (`is_bootstrapped` guard, `try/finally` state reset).
  - `build_summary()` one-line `logging` summary (stdlib logging, `caplog`-friendly).
  - `_lite_bootstrap_*` app-tagging sentinel convention (e.g.
    `_lite_bootstrap_lifespan_attached`).

- [ ] **Step 4: Verify the three files exist and are non-empty**

  Run: `wc -l architecture/*.md`
  Expected: three files, each with substantive line counts (not empty).

- [ ] **Step 5: Commit**

  ```bash
  git add architecture/
  git commit -m "docs(architecture): seed truth home (config-model, instruments, bootstrappers)

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 3: Migrate the four clean design+plan pairs into bundles

**Files (per bundle: `git mv` design + plan, then add/adjust frontmatter):**

- [ ] **Step 1: `git mv` the four pairs into bundle folders**

  ```bash
  cd /Users/kevinsmith/src/pypi/lite-bootstrap

  # instrument-skip-rework (2026-06-01.01)
  mkdir -p planning/changes/archive/2026-06-01.01-instrument-skip-rework
  git mv planning/specs/2026-06-01-instrument-skip-rework-design.md planning/changes/archive/2026-06-01.01-instrument-skip-rework/design.md
  git mv planning/plans/2026-06-01-instrument-skip-rework.md         planning/changes/archive/2026-06-01.01-instrument-skip-rework/plan.md

  # fastmcp-bootstrapper (2026-06-01.02)
  mkdir -p planning/changes/archive/2026-06-01.02-fastmcp-bootstrapper
  git mv planning/specs/2026-06-01-fastmcp-bootstrapper-design.md planning/changes/archive/2026-06-01.02-fastmcp-bootstrapper/design.md
  git mv planning/plans/2026-06-01-fastmcp-bootstrapper.md        planning/changes/archive/2026-06-01.02-fastmcp-bootstrapper/plan.md

  # stdlib-logging-and-build-summary (2026-06-02.01)
  mkdir -p planning/changes/archive/2026-06-02.01-stdlib-logging-and-build-summary
  git mv planning/specs/2026-06-02-stdlib-logging-and-build-summary-design.md planning/changes/archive/2026-06-02.01-stdlib-logging-and-build-summary/design.md
  git mv planning/plans/2026-06-02-stdlib-logging-and-build-summary.md        planning/changes/archive/2026-06-02.01-stdlib-logging-and-build-summary/plan.md

  # mkdocs-github-pages (2026-06-09.01)
  mkdir -p planning/changes/archive/2026-06-09.01-mkdocs-github-pages
  git mv planning/specs/2026-06-09-mkdocs-github-actions-design.md planning/changes/archive/2026-06-09.01-mkdocs-github-pages/design.md
  git mv planning/plans/2026-06-09-mkdocs-github-actions-plan.md   planning/changes/archive/2026-06-09.01-mkdocs-github-pages/plan.md
  ```

- [ ] **Step 2: Prepend frontmatter to each `design.md`**

  These docs currently open with a prose `# Title` + `**Date:**`/`**Status:**`
  lines. Prepend a YAML frontmatter block at the very top of each `design.md`
  (leave the existing prose body intact below it):

  `…/2026-06-01.01-instrument-skip-rework/design.md`:
  ```yaml
  ---
  status: shipped
  date: 2026-06-01
  slug: instrument-skip-rework
  supersedes: null
  superseded_by: stdlib-logging-and-build-summary
  pr: null
  outcome: shipped (partially superseded; see stdlib-logging-and-build-summary)
  ---
  ```

  `…/2026-06-01.02-fastmcp-bootstrapper/design.md`:
  ```yaml
  ---
  status: shipped
  date: 2026-06-01
  slug: fastmcp-bootstrapper
  supersedes: null
  superseded_by: null
  pr: null
  outcome: shipped
  ---
  ```

  `…/2026-06-02.01-stdlib-logging-and-build-summary/design.md`:
  ```yaml
  ---
  status: shipped
  date: 2026-06-02
  slug: stdlib-logging-and-build-summary
  supersedes: instrument-skip-rework
  superseded_by: null
  pr: "107"
  outcome: "merged as #107"
  ---
  ```

  `…/2026-06-09.01-mkdocs-github-pages/design.md`:
  ```yaml
  ---
  status: shipped
  date: 2026-06-09
  slug: mkdocs-github-pages
  supersedes: null
  superseded_by: null
  pr: null
  outcome: shipped in the docs+CI modern-di mirror arc (#112–#115)
  ---
  ```

- [ ] **Step 3: Prepend frontmatter to each `plan.md`**

  `…/2026-06-01.01-instrument-skip-rework/plan.md`:
  ```yaml
  ---
  status: shipped
  date: 2026-06-01
  slug: instrument-skip-rework
  spec: instrument-skip-rework
  pr: null
  ---
  ```

  `…/2026-06-01.02-fastmcp-bootstrapper/plan.md`:
  ```yaml
  ---
  status: shipped
  date: 2026-06-01
  slug: fastmcp-bootstrapper
  spec: fastmcp-bootstrapper
  pr: null
  ---
  ```

  `…/2026-06-02.01-stdlib-logging-and-build-summary/plan.md`:
  ```yaml
  ---
  status: shipped
  date: 2026-06-02
  slug: stdlib-logging-and-build-summary
  spec: stdlib-logging-and-build-summary
  pr: "107"
  ---
  ```

  `…/2026-06-09.01-mkdocs-github-pages/plan.md`:
  ```yaml
  ---
  status: shipped
  date: 2026-06-09
  slug: mkdocs-github-pages
  spec: mkdocs-github-pages
  pr: null
  ---
  ```

- [ ] **Step 4: Fix any internal cross-links broken by the rename**

  Run: `grep -rn "instrument-skip-rework\|2026-06-01-fastmcp\|2026-06-02-stdlib\|2026-06-09-mkdocs" planning/changes/archive/`
  For each hit that points at an old `planning/specs|plans/...` path or a sibling
  doc's old filename, update it to the new bundle path
  (`./design.md`, `./plan.md`, or `../<bundle-id>/design.md`). The
  `stdlib-logging` design references `instrument-skip-rework`'s old plan path —
  repoint it to `../2026-06-01.01-instrument-skip-rework/plan.md`.

- [ ] **Step 5: Verify frontmatter parses**

  Run:
  ```bash
  for f in planning/changes/archive/*/design.md planning/changes/archive/*/plan.md; do
    python3 -c "import sys,yaml; t=open('$f').read(); assert t.startswith('---'); yaml.safe_load(t.split('---')[1]); print('OK $f')"
  done
  ```
  Expected: `OK …` for all eight files (uses `uv run python` if PyYAML is not on
  the system interpreter: `uv run python -c …`).

- [ ] **Step 6: Commit**

  ```bash
  git add planning/changes/archive planning/specs planning/plans
  git commit -m "docs(planning): migrate clean design+plan pairs into change bundles

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 4: Migrate the three audit arcs + audits/ + retros/

**Files:** three per-arc bundles (sequencing → `design.md`, PR plans grouped as
`plan-pr*.md`), two audits → `audits/`, three retros → `retros/`.

- [ ] **Step 1: `git mv` the audit arc bundles**

  ```bash
  cd /Users/kevinsmith/src/pypi/lite-bootstrap

  # Arc 1: audit-implementation (2026-05-31.01) — sequencing → design.md, pr1..7 grouped
  mkdir -p planning/changes/archive/2026-05-31.01-audit-implementation
  git mv planning/specs/2026-05-31-audit-implementation-sequencing.md planning/changes/archive/2026-05-31.01-audit-implementation/design.md
  git mv planning/plans/2026-05-31-pr1-crit1-redoc-root-path.md       planning/changes/archive/2026-05-31.01-audit-implementation/plan-pr1-crit1-redoc-root-path.md
  git mv planning/plans/2026-05-31-pr2-crit2-otel-shutdown.md         planning/changes/archive/2026-05-31.01-audit-implementation/plan-pr2-crit2-otel-shutdown.md
  git mv planning/plans/2026-05-31-pr3-crit3-idempotent-teardown.md   planning/changes/archive/2026-05-31.01-audit-implementation/plan-pr3-crit3-idempotent-teardown.md
  git mv planning/plans/2026-06-01-pr4-des4-des5-small-cleanups.md    planning/changes/archive/2026-05-31.01-audit-implementation/plan-pr4-des4-des5-small-cleanups.md
  git mv planning/plans/2026-06-01-pr5-des3-config-method-semantics.md planning/changes/archive/2026-05-31.01-audit-implementation/plan-pr5-des3-config-method-semantics.md
  git mv planning/plans/2026-06-01-pr6-des2-otel-fields-mixin.md      planning/changes/archive/2026-05-31.01-audit-implementation/plan-pr6-des2-otel-fields-mixin.md
  git mv planning/plans/2026-06-01-pr7-des1-generic-instruments.md    planning/changes/archive/2026-05-31.01-audit-implementation/plan-pr7-des1-generic-instruments.md

  # Arc 2: deferred-refactors (2026-06-01.03) — sequencing → design.md, pr8..16 grouped
  mkdir -p planning/changes/archive/2026-06-01.03-deferred-refactors
  git mv planning/specs/2026-06-01-deferred-refactors-sequencing.md planning/changes/archive/2026-06-01.03-deferred-refactors/design.md
  git mv planning/plans/2026-06-01-pr8-low-1-2-sentry-micro.md  planning/changes/archive/2026-06-01.03-deferred-refactors/plan-pr8-low-1-2-sentry-micro.md
  git mv planning/plans/2026-06-01-pr9-otel-touch-ups.md        planning/changes/archive/2026-06-01.03-deferred-refactors/plan-pr9-otel-touch-ups.md
  git mv planning/plans/2026-06-01-pr10-test-gap-fill.md        planning/changes/archive/2026-06-01.03-deferred-refactors/plan-pr10-test-gap-fill.md
  git mv planning/plans/2026-06-01-pr11-logging-cleanup.md      planning/changes/archive/2026-06-01.03-deferred-refactors/plan-pr11-logging-cleanup.md
  git mv planning/plans/2026-06-01-pr12-base-layer-cleanup.md   planning/changes/archive/2026-06-01.03-deferred-refactors/plan-pr12-base-layer-cleanup.md
  git mv planning/plans/2026-06-01-pr13-frozen-setattr.md       planning/changes/archive/2026-06-01.03-deferred-refactors/plan-pr13-frozen-setattr.md
  git mv planning/plans/2026-06-01-pr14-faststream-timeout.md   planning/changes/archive/2026-06-01.03-deferred-refactors/plan-pr14-faststream-timeout.md
  git mv planning/plans/2026-06-01-pr15-naming-pass.md          planning/changes/archive/2026-06-01.03-deferred-refactors/plan-pr15-naming-pass.md
  git mv planning/plans/2026-06-01-pr16-post-retro-hygiene.md   planning/changes/archive/2026-06-01.03-deferred-refactors/plan-pr16-post-retro-hygiene.md

  # Arc 3: bug-audit-v2 (2026-06-05.01) — sequencing → design.md, pr1..3 grouped
  mkdir -p planning/changes/archive/2026-06-05.01-bug-audit-v2
  git mv planning/specs/2026-06-05-bug-audit-v2-sequencing.md planning/changes/archive/2026-06-05.01-bug-audit-v2/design.md
  git mv planning/plans/2026-06-05-pr1-lifecycle.md       planning/changes/archive/2026-06-05.01-bug-audit-v2/plan-pr1-lifecycle.md
  git mv planning/plans/2026-06-05-pr2-config-security.md planning/changes/archive/2026-06-05.01-bug-audit-v2/plan-pr2-config-security.md
  git mv planning/plans/2026-06-05-pr3-hygiene-ci.md      planning/changes/archive/2026-06-05.01-bug-audit-v2/plan-pr3-hygiene-ci.md
  ```

- [ ] **Step 2: `git mv` audits → `audits/` and retros → `retros/`**

  ```bash
  git mv planning/specs/2026-05-31-bug-refactor-audit.md planning/audits/2026-05-31-bug-refactor-audit.md
  git mv planning/specs/2026-06-05-bug-audit-v2.md       planning/audits/2026-06-05-bug-audit-v2.md

  git mv planning/specs/2026-06-01-audit-implementation-retro.md         planning/retros/2026-06-01-audit-implementation-retro.md
  git mv planning/specs/2026-06-05-bug-audit-v2-retro.md                 planning/retros/2026-06-05-bug-audit-v2-retro.md
  git mv planning/specs/2026-06-09-docs-and-ci-modern-di-mirror-retro.md planning/retros/2026-06-09-docs-and-ci-modern-di-mirror-retro.md
  ```

- [ ] **Step 3: Prepend frontmatter to the three arc `design.md` files**

  (Grouped `plan-pr*.md` files keep their original prose headers — deliberate,
  per spec Non-goals. Audits and retros keep their original prose headers too.)

  `…/2026-05-31.01-audit-implementation/design.md`:
  ```yaml
  ---
  status: shipped
  date: 2026-05-31
  slug: audit-implementation
  supersedes: null
  superseded_by: null
  pr: null
  outcome: "shipped as #89–#95"
  ---
  ```

  `…/2026-06-01.03-deferred-refactors/design.md`:
  ```yaml
  ---
  status: shipped
  date: 2026-06-01
  slug: deferred-refactors
  supersedes: null
  superseded_by: null
  pr: null
  outcome: "shipped as #96–#103"
  ---
  ```

  `…/2026-06-05.01-bug-audit-v2/design.md`:
  ```yaml
  ---
  status: shipped
  date: 2026-06-05
  slug: bug-audit-v2
  supersedes: null
  superseded_by: null
  pr: null
  outcome: "shipped as #108–#110"
  ---
  ```

- [ ] **Step 4: Repoint cross-links in the moved arc/audit/retro docs**

  The sequencing `design.md` files and retros link to their parent audit and
  sibling plans by old paths. Update those links:

  Run: `grep -rn "planning/specs\|planning/plans\|2026-05-31-bug-refactor-audit\|-sequencing.md\|../plans/" planning/changes/archive planning/audits planning/retros`

  For each hit, repoint:
  - parent-audit links → `../../audits/2026-05-31-bug-refactor-audit.md` (or
    `2026-06-05-bug-audit-v2.md`) from within a bundle.
  - sibling-plan links → the new `plan-pr*.md` name in the same bundle folder.
  - sequencing/retro cross-references → the new bundle `design.md` path or
    `retros/` path.

- [ ] **Step 5: Verify arc frontmatter parses + no plans left behind**

  Run:
  ```bash
  for f in planning/changes/archive/2026-05-31.01-audit-implementation/design.md \
           planning/changes/archive/2026-06-01.03-deferred-refactors/design.md \
           planning/changes/archive/2026-06-05.01-bug-audit-v2/design.md; do
    python3 -c "import yaml; t=open('$f').read(); assert t.startswith('---'); yaml.safe_load(t.split('---')[1]); print('OK $f')"
  done
  ls planning/specs planning/plans
  ```
  Expected: three `OK` lines; `planning/specs` and `planning/plans` now empty
  (or "No such file" if git removed them — both acceptable).

- [ ] **Step 6: Commit**

  ```bash
  git add planning/
  git commit -m "docs(planning): migrate audit arcs into per-arc bundles; sort audits/retros

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 5: Remove the old directories + lightweight template

**Files:**
- Delete: `planning/templates/lightweight-plan-template.md`
- Remove now-empty `planning/specs/`, `planning/plans/`, `planning/templates/`

- [ ] **Step 1: Remove the lightweight template and empty dirs**

  ```bash
  git rm planning/templates/lightweight-plan-template.md
  # specs/ and plans/ are emptied by git after the moves; remove any stray files
  rmdir planning/specs planning/plans planning/templates 2>/dev/null || true
  ```

- [ ] **Step 2: Verify the old layout is gone**

  Run: `ls planning/`
  Expected: `README.md` (next task) is absent yet; present dirs are
  `_templates  audits  changes  deferred.md  releases  retros`. No `specs`,
  `plans`, or `templates`.

- [ ] **Step 3: Commit**

  ```bash
  git add -A planning/
  git commit -m "docs(planning): drop superseded lightweight-plan template and empty dirs

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 6: Author `planning/README.md` (Conventions byte-identical + fresh Index)

**Files:**
- Create: `planning/README.md`

- [ ] **Step 1: Build the README from three parts**

  Assemble `planning/README.md` as:

  1. **Intro** (repo-specific — adapt the faststream-outbox intro, swapping the
     repo name):
     ```markdown
     # Planning

     Specs, plans, and change history for `lite-bootstrap`. The living truth
     about *what the system does now* lives in [`architecture/`](../architecture/)
     at the repo root; this directory records *how it got there*.
     ```

  2. **Conventions** — copied **byte-identical** from
     `/Users/kevinsmith/src/pypi/faststream-outbox/planning/README.md`: the block
     from the `## Conventions` header through the end of the `### Frontmatter`
     subsection (i.e. everything before `## Index`). Do not edit a word of it.

  3. **Index + Other** — authored fresh (Step 2).

  Extraction helper for the Conventions block:
  ```bash
  awk '/^## Conventions/{f=1} /^## Index/{f=0} f' \
    /Users/kevinsmith/src/pypi/faststream-outbox/planning/README.md
  ```

- [ ] **Step 2: Author the fresh `## Index` + `## Other` sections**

  Append after the Conventions block:

  ```markdown
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
  ```

- [ ] **Step 3: Verify the Conventions block is byte-identical**

  Run:
  ```bash
  diff <(awk '/^## Conventions/{f=1} /^## Index/{f=0} f' /Users/kevinsmith/src/pypi/faststream-outbox/planning/README.md) \
       <(awk '/^## Conventions/{f=1} /^## Index/{f=0} f' planning/README.md) \
    && echo "CONVENTIONS IDENTICAL"
  ```
  Expected: `CONVENTIONS IDENTICAL` (no diff).

- [ ] **Step 4: Verify Index links resolve**

  Run:
  ```bash
  grep -oE '\]\(([^)]+\.md)\)' planning/README.md | sed -E 's/\]\(|\)//g' | while read p; do
    [ -f "planning/$p" ] || [ -f "$p" ] || echo "BROKEN: $p"
  done; echo "done"
  ```
  Expected: only `done` (no `BROKEN:` lines). (`../architecture/...` paths
  resolve from `planning/`.)

- [ ] **Step 5: Commit**

  ```bash
  git add planning/README.md
  git commit -m "docs(planning): add README — portable Conventions + fresh Index

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 7: Update `CLAUDE.md` (`## Workflow`) and add `just docs-build`

**Files:**
- Modify: `CLAUDE.md` (`## Planning artifacts` → `## Workflow`)
- Modify: `justfile` (add `docs-build`)

- [ ] **Step 1: Replace the `## Planning artifacts` section in `CLAUDE.md`**

  Delete the existing `## Planning artifacts` section (the `planning/specs/` vs
  `planning/plans/` description and the "superpowers default" note) and replace
  it with a `## Workflow` section adapted from `faststream-outbox`. Use this text
  (adjusting the truth-home reference to this repo's `architecture/`):

  ```markdown
  ## Workflow

  Per-feature: brainstorming → spec in `planning/changes/active/YYYY-MM-DD.NN-<slug>/design.md` → writing-plans → plan in `planning/changes/active/YYYY-MM-DD.NN-<slug>/plan.md` → executing-plans / subagent-driven-development → requesting-code-review → finishing-a-development-branch. Each change is a folder bundle; `<slug>` is a kebab-case description, not a story ID; `.NN` is a zero-padded intra-day counter that breaks same-date ties so the timeline sorts stably. On merge, the bundle moves to `planning/changes/archive/` with `status: shipped`, `pr:`, and `outcome:` filled, **and the change promotes its conclusions into the affected `architecture/<capability>.md`** — that hand-edit is what keeps `architecture/` true. See [`planning/README.md`](planning/README.md) for the conventions + index and [`planning/_templates/`](planning/_templates/) for copy-and-fill starting points.

  **Spec** (`design.md`) captures the *thinking* — why, what the design is, trade-offs, scope. Written before code; rarely revised after merge. **Plan** (`plan.md`) captures the *sequencing* — the ordered checklist an executor walks; references the spec for the "why". **`architecture/`** captures the *invariants* of shipped systems — the living truth, promoted from a change on merge. A plan paragraph that would still read correctly with all task numbers and checkboxes removed is design content and belongs in the spec.

  **Three lanes.** Scale the artifact to the change. **Full** — a `design.md` + `plan.md` bundle — for real design judgment, a new file/module, a public-API change, cross-cutting/multi-file work, or non-trivial test design. **Lightweight** — a single `change.md` — for small-but-real changes (≲30 LOC net, ≤2 files, no new file, no public-API change, a single straightforward test). **Tiny** — no bundle, just a conventional commit — for a typo, dep bump, linter/formatter/CI tweak, a mechanical rename, or a single-line config change. Heavier lane wins on ambiguity; a `change.md` that outgrows its lane splits into `design.md` + `plan.md`.

  Design docs and implementation plans live under `planning/` (not under `docs/`, so they're excluded from the mkdocs site automatically). When superpowers skills default to `docs/superpowers/specs/` or `docs/superpowers/plans/`, use the change bundle under `planning/changes/active/` here instead.
  ```

- [ ] **Step 2: Add a `docs-build` target to `justfile`**

  After the `docs-deploy` target, add:
  ```make
  # Strict local docs build (no deploy). Mirrors CI's link/strict checks.
  docs-build:
      uvx --with-requirements docs/requirements.txt mkdocs build --strict
  ```

- [ ] **Step 3: Verify no stale planning references remain in repo prose**

  Run:
  ```bash
  grep -rn "planning/specs\|planning/plans\|lightweight-plan-template\|planning/templates" \
    --include="*.md" --include="justfile" . \
    | grep -v "planning/changes/" || echo "NO STALE REFERENCES"
  ```
  Expected: `NO STALE REFERENCES` (hits inside migrated archive prose that
  legitimately describe history are acceptable — judge each; the goal is no
  stale *pointers* in `CLAUDE.md`, `justfile`, `README.md`, or `docs/`).

- [ ] **Step 4: Commit**

  ```bash
  git add CLAUDE.md justfile
  git commit -m "docs: rewrite CLAUDE.md Planning section as Workflow; add just docs-build

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 8: Full verification sweep

**Files:** none (verification only).

- [ ] **Step 1: Lint (markdown/format gate; no code changed)**

  Run: `just lint-ci`
  Expected: passes (eof-fixer --check, ruff format --check, ruff check --no-fix,
  ty check all green). If eof-fixer flags a new markdown file missing a trailing
  newline, run `just lint` to autofix, then re-commit.

- [ ] **Step 2: Strict docs build**

  Run: `just docs-build`
  Expected: `mkdocs build --strict` succeeds with no warnings. `architecture/`
  and `planning/` are outside `docs_dir: docs`, so they are not part of the
  build; this confirms the untouched `docs/` tree still builds clean.

- [ ] **Step 3: Stale-reference + tree sweeps**

  Run:
  ```bash
  echo "--- stale pointers ---"
  grep -rn "planning/specs\|planning/plans\|lightweight-plan-template" --include="*.md" --include="justfile" . | grep -vE "planning/changes/archive/" || echo "clean"
  echo "--- final planning tree ---"
  ls -R planning/ architecture/
  ```
  Expected: `clean` for pointers; the tree matches design §2 (no `specs/`,
  `plans/`, `templates/`; `changes/{active,archive}`, `audits`, `retros`,
  `releases`, `_templates`, `deferred.md`, `README.md` present;
  `architecture/` has three `.md` files).

- [ ] **Step 4: Frontmatter parse sweep across all bundles**

  Run:
  ```bash
  for f in $(find planning/changes -name design.md -o -name plan.md); do
    python3 -c "import yaml; t=open('$f').read(); assert t.startswith('---'),'$f'; yaml.safe_load(t.split('---')[1])" && echo "OK $f" || echo "BAD $f"
  done
  ```
  Expected: `OK` for every `design.md` / `plan.md` (the active convention bundle
  + all archived bundles). No `BAD` lines. (Grouped `plan-pr*.md` files are
  intentionally excluded — they keep prose headers.)

- [ ] **Step 5: Commit (if any lint autofix touched files)**

  ```bash
  git add -A
  git commit -m "docs(planning): lint/format fixups from convention migration

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>" || echo "nothing to commit"
  ```

---

### On merge (finishing step — not executed during the branch)

When this PR merges, self-migrate this convention bundle from `active/` to
`archive/` (it defines the convention, so **no `architecture/` promotion
applies**):

```bash
git mv planning/changes/active/2026-06-13.01-portable-planning-convention \
       planning/changes/archive/2026-06-13.01-portable-planning-convention
```

Then set `status: shipped`, `pr:`, `outcome:` in this bundle's `design.md`
frontmatter and move its line from **Active** to **Archived** in
`planning/README.md`'s Index.
