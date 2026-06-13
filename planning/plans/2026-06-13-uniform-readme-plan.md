# Uniform README Header + Footer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Standardize the title, badge block, and footer of the README in all 17 `modern-python` repos (15 libraries + 2 templates), one PR per repo, leaving each repo's body untouched.

**Architecture:** Each repo is its own git checkout under `~/src/pypi/<repo>` (libraries) or `~/src/<repo>` (templates). For each repo: branch `docs/uniform-readme`, replace the top-of-file header region (title + old badges) with the canonical header for that repo's archetype, normalize the footer, verify every badge URL resolves, commit, push, open a PR. No body content changes.

**Tech Stack:** Markdown, shields.io / GitHub / pypistats / context7 badges, `git`, `gh` CLI, `curl` for badge verification.

**Source spec:** `planning/specs/2026-06-13-uniform-readme-design.md`

---

## Repo archetypes

| Archetype | Repos | Header source |
|-----------|-------|---------------|
| **A — standard library** | `db-retry`, `eof-fixer`, `faststream-concurrent-aiokafka`, `faststream-outbox`, `faststream-redis-timers`, `httpware`, `lite-bootstrap`, `modern-di-fastapi`, `modern-di-faststream`, `modern-di-litestar`, `modern-di-pytest`, `modern-di-typer` (12) | `REFERENCE: Header A` |
| **B — standard library, pkg ≠ repo** | `autosemver` (pkg `semvertag`) (1) | `REFERENCE: Header A`, substitute pkg |
| **C — table exception** | `modern-di` (1) | `REFERENCE: Header C` |
| **D — showcase** | `that-depends` (1) | `REFERENCE: Header D` |
| **E — template (not on PyPI)** | `fastapi-sqlalchemy-template`, `litestar-sqlalchemy-template` (2) | `REFERENCE: Header E` |

Library checkout root: `~/src/pypi/<repo>`. Template checkout root: `~/src/<repo>`.

---

## REFERENCE: canonical blocks

> These blocks are the single source of truth. Per-repo tasks tell you which to use and which variables/conditionals apply. **Substitute `<repo>` (GitHub repo slug) and `<pkg>` (PyPI name) literally.** For archetype A/B they are identical except `autosemver`→`semvertag`.

### REFERENCE: Header A (standard library)

```markdown
# <pkg>

[![PyPI version](https://img.shields.io/pypi/v/<pkg>.svg)](https://pypi.org/project/<pkg>/)
[![Supported Python versions](https://img.shields.io/pypi/pyversions/<pkg>.svg)](https://pypi.org/project/<pkg>/)
[![Downloads](https://img.shields.io/pypi/dm/<pkg>.svg)](https://pypistats.org/packages/<pkg>)
[![Coverage](https://img.shields.io/badge/coverage-100%25-brightgreen.svg)](https://github.com/modern-python/<repo>/actions/workflows/ci.yml)
[![CI](https://github.com/modern-python/<repo>/actions/workflows/ci.yml/badge.svg)](https://github.com/modern-python/<repo>/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/modern-python/<repo>.svg)](https://github.com/modern-python/<repo>/blob/main/LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/modern-python/<repo>)](https://github.com/modern-python/<repo>/stargazers)
[![Context7](https://img.shields.io/badge/Context7-docs-blue)](https://context7.com/modern-python/<repo>)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![ty](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ty/main/assets/badge/v0.json)](https://github.com/astral-sh/ty)
```

**Conditional:** Remove the `Context7` line if Task 1 marked the repo NOT-indexed.

### REFERENCE: Header C (`modern-di` — keep the table)

Do NOT replace the existing per-package badge table. Keep the title as `# modern-di` (lowercase ATX) and the existing table immediately below it. Insert this flat badge row **between the title and the table**:

```markdown
[![Context7](https://img.shields.io/badge/Context7-docs-blue)](https://context7.com/modern-python/modern-di)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![ty](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ty/main/assets/badge/v0.json)](https://github.com/astral-sh/ty)
```

**Conditional:** Remove the `Context7` line if Task 1 marked `modern-di` NOT-indexed.

### REFERENCE: Header D (`that-depends` — showcase)

Title `# that-depends`. Badge block (note: keeps codecov live badge, mypy/pyrefly, libs.tech, llms.txt; switches downloads pepy→pypistats; adds PyPI version, CI, License, Context7; NO uv/ruff/ty; NO static 100% badge):

```markdown
# that-depends

[![PyPI version](https://img.shields.io/pypi/v/that-depends.svg)](https://pypi.org/project/that-depends/)
[![Supported Python versions](https://img.shields.io/pypi/pyversions/that-depends.svg)](https://pypi.org/project/that-depends/)
[![Downloads](https://img.shields.io/pypi/dm/that-depends.svg)](https://pypistats.org/packages/that-depends)
[![Test Coverage](https://codecov.io/gh/modern-python/that-depends/branch/main/graph/badge.svg)](https://codecov.io/gh/modern-python/that-depends)
[![CI](https://github.com/modern-python/that-depends/actions/workflows/ci.yml/badge.svg)](https://github.com/modern-python/that-depends/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/modern-python/that-depends.svg)](https://github.com/modern-python/that-depends/blob/main/LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/modern-python/that-depends)](https://github.com/modern-python/that-depends/stargazers)
[![MyPy Strict](https://img.shields.io/badge/mypy-strict-blue)](https://mypy.readthedocs.io/en/stable/getting_started.html#strict-mode-and-configuration)
[![pyrefly](https://img.shields.io/endpoint?url=https://pyrefly.org/badge.json)](https://github.com/facebook/pyrefly)
[![libs.tech recommends](https://libs.tech/project/773446541/badge.svg)](https://libs.tech/project/773446541/that-depends)
[![Context7](https://img.shields.io/badge/Context7-docs-blue)](https://context7.com/modern-python/that-depends)
[![llms.txt](https://img.shields.io/badge/llms.txt-green)](https://that-depends.modern-python.org/llms.txt)
```

### REFERENCE: Header E (template — not on PyPI)

Title `# <repo>` (lowercase ATX), keep the existing one-line tagline as the first body line. No PyPI/version/downloads badges. Drop the existing `GitHub issues`/`GitHub forks` badges.

```markdown
# <repo>

<existing one-line tagline>

[![Coverage](https://img.shields.io/badge/coverage-100%25-brightgreen.svg)](https://github.com/modern-python/<repo>/actions/workflows/ci.yml)
[![CI](https://github.com/modern-python/<repo>/actions/workflows/ci.yml/badge.svg)](https://github.com/modern-python/<repo>/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/modern-python/<repo>.svg)](https://github.com/modern-python/<repo>/blob/main/LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/modern-python/<repo>)](https://github.com/modern-python/<repo>/stargazers)
[![Context7](https://img.shields.io/badge/Context7-docs-blue)](https://context7.com/modern-python/<repo>)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![ty](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ty/main/assets/badge/v0.json)](https://github.com/astral-sh/ty)
```

**Conditional:** Remove the `Context7` line if Task 1 marked the template NOT-indexed.

### REFERENCE: Footer (all repos)

Replace the existing tail of the README (the `## 📚` / `## 📦` / `## 📝` / `## Part of modern-python` / `## License` / `## Acknowledgements`-style links, if present) so the file **ends** with exactly this. Keep any `## Acknowledgements` section that exists **above** this footer.

```markdown
## 📚 [Documentation](https://<repo>.modern-python.org)

## 📦 [PyPI](https://pypi.org/project/<pkg>)

## 📝 [License](LICENSE)

## Part of `modern-python`

Browse the full list of templates and libraries in
[`modern-python`](https://github.com/modern-python) — see the org profile for the categorized index.
```

**Conditionals:**
- Remove the `## 📚 [Documentation]` line if Task 1 marked the repo as having NO live docs site.
- Remove the `## 📦 [PyPI]` line for templates (archetype E).

---

## REFERENCE: per-repo procedure

Every per-repo task (Tasks 2–18) follows these exact steps. `$ROOT` = `~/src/pypi` for libraries, `~/src` for templates. Replace `<repo>`, `<pkg>`.

- **Step a — Branch.**

```bash
cd $ROOT/<repo>
git switch -c docs/uniform-readme
```

- **Step b — Edit the README.** Open the README file (`README.md`, or `readme.md` for templates — preserve existing casing). Replace the header region (everything from the start of the file down to and including the last badge line / the line just before the first prose paragraph or first `##` body section) with the resolved header block named in the task. Then replace the footer region with the resolved footer block. Apply the task's conditionals (drop Context7 / Documentation / PyPI lines as instructed by Task 1's results).

- **Step c — Verify badges resolve.** Run the link checker; every line must print `200` (3xx is fine for redirects — `-L` follows them). Investigate any `4xx`/`5xx`.

```bash
README=$(ls README.md readme.md 2>/dev/null | head -1)
grep -oE 'https?://[^) ]+' "$README" | sort -u | while read -r u; do
  code=$(curl -s -o /dev/null -w '%{http_code}' -L --max-time 20 "$u")
  printf '%s %s\n' "$code" "$u"
done
```

Expected: all `200`. A `404` on the Context7 URL means the repo is not indexed → remove the Context7 badge (this should already be handled by Task 1's flags). A `404` on the docs URL means no docs site → remove the `## 📚 [Documentation]` line.

- **Step d — Visual check.** Run `gh markdown` preview or eyeball: title is `# <pkg>`, badges render in one block, footer ends with the "Part of `modern-python`" paragraph, no duplicated badge rows, body unchanged.

```bash
git diff -- "$README"   # confirm ONLY header + footer changed, body untouched
```

- **Step e — Commit.**

```bash
git add "$README"
git commit -m "docs: standardize README header and footer

Aligns with the modern-python uniform-README standard.
See planning/specs/2026-06-13-uniform-readme-design.md in lite-bootstrap.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

- **Step f — Push + open PR.**

```bash
git push -u origin docs/uniform-readme
gh pr create --title "docs: standardize README header and footer" --body "$(cat <<'EOF'
Standardizes this repo's README header (title + badge block) and footer
(documentation / PyPI / license links + "Part of \`modern-python\`") to the
org-wide uniform-README standard. Body content is unchanged.

Standard: lowercase ATX title, badge block (PyPI version · Python versions ·
downloads · coverage · CI · license · GitHub stars · Context7 · uv/ruff/ty),
and the shared "Part of \`modern-python\`" footer.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Task 1: Preflight — resolve per-repo conditionals

**Files:** none committed; produces a scratch table the later tasks read.

- [ ] **Step 1: Verify Context7 indexing for all 17 repos.**

```bash
for r in db-retry eof-fixer faststream-concurrent-aiokafka faststream-outbox \
  faststream-redis-timers httpware lite-bootstrap modern-di modern-di-fastapi \
  modern-di-faststream modern-di-litestar modern-di-pytest modern-di-typer \
  that-depends autosemver fastapi-sqlalchemy-template litestar-sqlalchemy-template; do
  code=$(curl -s -o /dev/null -w '%{http_code}' -L --max-time 20 "https://context7.com/modern-python/$r")
  printf '%s context7 %s\n' "$code" "$r"
done
```

Expected: `200` = indexed (keep Context7 badge); `404` = not indexed (drop Context7 badge for that repo). Record the list of NOT-indexed repos.

- [ ] **Step 2: Verify docs sites for all repos.**

```bash
for r in db-retry eof-fixer faststream-concurrent-aiokafka faststream-outbox \
  faststream-redis-timers httpware lite-bootstrap modern-di modern-di-fastapi \
  modern-di-faststream modern-di-litestar modern-di-pytest modern-di-typer \
  that-depends autosemver fastapi-sqlalchemy-template litestar-sqlalchemy-template; do
  code=$(curl -s -o /dev/null -w '%{http_code}' -L --max-time 20 "https://$r.modern-python.org")
  printf '%s docs %s\n' "$code" "$r"
done
```

Expected: `200` = live docs site (keep `## 📚 [Documentation]` line); other = no site (drop the line). Known-live from spec: `autosemver`, `faststream-outbox`, `faststream-redis-timers`, `httpware`, `lite-bootstrap`, `modern-di`, `that-depends`.

- [ ] **Step 3: Confirm each repo is on a clean default branch.**

```bash
for r in ~/src/pypi/{db-retry,eof-fixer,faststream-concurrent-aiokafka,faststream-outbox,faststream-redis-timers,httpware,lite-bootstrap,modern-di,modern-di-fastapi,modern-di-faststream,modern-di-litestar,modern-di-pytest,modern-di-typer,that-depends,autosemver} ~/src/{fastapi-sqlalchemy-template,litestar-sqlalchemy-template}; do
  printf '%s ' "$r"; git -C "$r" status --porcelain=v1 | head -1; git -C "$r" rev-parse --abbrev-ref HEAD
done
```

Expected: each repo clean (no output from `--porcelain`) and on its default branch. If any repo is dirty, stop and surface it.

- [ ] **Step 4: Record results.** Write the NOT-indexed-on-Context7 list and the no-docs-site list into this plan's checkboxes (or a scratch note) so Tasks 2–18 know which conditional lines to drop.

---

## Task 2: `lite-bootstrap` (archetype A — worked example)

**Files:** Modify `~/src/pypi/lite-bootstrap/README.md`

- [ ] **Step 1:** Run per-repo procedure Step a (branch) with `<repo>=lite-bootstrap`.
- [ ] **Step 2:** Apply **REFERENCE: Header A** with `<pkg>=lite-bootstrap`, `<repo>=lite-bootstrap`. Context7 = keep (indexed, confirmed). The resolved header is:

```markdown
# lite-bootstrap

[![PyPI version](https://img.shields.io/pypi/v/lite-bootstrap.svg)](https://pypi.org/project/lite-bootstrap/)
[![Supported Python versions](https://img.shields.io/pypi/pyversions/lite-bootstrap.svg)](https://pypi.org/project/lite-bootstrap/)
[![Downloads](https://img.shields.io/pypi/dm/lite-bootstrap.svg)](https://pypistats.org/packages/lite-bootstrap)
[![Coverage](https://img.shields.io/badge/coverage-100%25-brightgreen.svg)](https://github.com/modern-python/lite-bootstrap/actions/workflows/ci.yml)
[![CI](https://github.com/modern-python/lite-bootstrap/actions/workflows/ci.yml/badge.svg)](https://github.com/modern-python/lite-bootstrap/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/modern-python/lite-bootstrap.svg)](https://github.com/modern-python/lite-bootstrap/blob/main/LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/modern-python/lite-bootstrap)](https://github.com/modern-python/lite-bootstrap/stargazers)
[![Context7](https://img.shields.io/badge/Context7-docs-blue)](https://context7.com/modern-python/lite-bootstrap)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![ty](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ty/main/assets/badge/v0.json)](https://github.com/astral-sh/ty)
```

Replace existing lines 1–6 (`Lite-Bootstrap\n==` + the 4 old badges). Keep the `## Lifecycle constraints`, usage examples, and `## Acknowledgements` body sections.

- [ ] **Step 3:** Apply **REFERENCE: Footer** with `<repo>=lite-bootstrap`, `<pkg>=lite-bootstrap`, Documentation line kept (docs site live). Replace the existing `## 📚` / `## 📦` / `## 📝` / `## Part of modern-python` tail. Keep `## Acknowledgements` above the footer.
- [ ] **Step 4:** Run per-repo procedure Steps c (verify badges), d (visual + `git diff`).
- [ ] **Step 5:** Run per-repo procedure Steps e (commit), f (push + PR).

---

## Tasks 3–13: archetype A standard libraries

For each repo below, follow the **per-repo procedure** Steps a–f, applying **REFERENCE: Header A** and **REFERENCE: Footer** with the listed `<pkg>`/`<repo>` (here `<pkg>` == `<repo>`), and applying Task 1's Context7 / Documentation conditionals.

- [ ] **Task 3: `db-retry`** — `<repo>=<pkg>=db-retry`. Docs line: drop unless Task 1 found a live site.
- [ ] **Task 4: `eof-fixer`** — `<repo>=<pkg>=eof-fixer`. Docs line: drop unless Task 1 found a live site. (Body has a large Features/Usage section — leave intact.)
- [ ] **Task 5: `faststream-concurrent-aiokafka`** — `<repo>=<pkg>=faststream-concurrent-aiokafka`. Docs line: drop unless live.
- [ ] **Task 6: `faststream-outbox`** — `<repo>=<pkg>=faststream-outbox`. Docs line: keep (docs.yml present).
- [ ] **Task 7: `faststream-redis-timers`** — `<repo>=<pkg>=faststream-redis-timers`. Docs line: keep (docs.yml present).
- [ ] **Task 8: `httpware`** — `<repo>=<pkg>=httpware`. Docs line: keep (docs.yml present). (Body has detailed Install/Quickstart — leave intact; replace only the current top 4 badges.)
- [ ] **Task 9: `modern-di-fastapi`** — `<repo>=<pkg>=modern-di-fastapi`. Docs line: drop unless live.
- [ ] **Task 10: `modern-di-faststream`** — `<repo>=<pkg>=modern-di-faststream`. Docs line: drop unless live.
- [ ] **Task 11: `modern-di-litestar`** — `<repo>=<pkg>=modern-di-litestar`. Docs line: drop unless live.
- [ ] **Task 12: `modern-di-pytest`** — `<repo>=<pkg>=modern-di-pytest`. Docs line: drop unless live.
- [ ] **Task 13: `modern-di-typer`** — `<repo>=<pkg>=modern-di-typer`. Docs line: drop unless live.

Each task's checklist: a) branch · b) apply Header A + Footer (resolved) · c) verify badges · d) visual + diff · e) commit · f) push + PR.

---

## Task 14: `autosemver` (archetype B — pkg ≠ repo)

**Files:** Modify `~/src/pypi/autosemver/README.md`

- [ ] **Step 1:** Branch (Step a), `<repo>=autosemver`.
- [ ] **Step 2:** Apply **REFERENCE: Header A** with `<pkg>=semvertag` and `<repo>=autosemver`. Note the split: PyPI/downloads badges use `semvertag`; GitHub/CI/Context7 use `autosemver`. Resolved header:

```markdown
# semvertag

[![PyPI version](https://img.shields.io/pypi/v/semvertag.svg)](https://pypi.org/project/semvertag/)
[![Supported Python versions](https://img.shields.io/pypi/pyversions/semvertag.svg)](https://pypi.org/project/semvertag/)
[![Downloads](https://img.shields.io/pypi/dm/semvertag.svg)](https://pypistats.org/packages/semvertag)
[![Coverage](https://img.shields.io/badge/coverage-100%25-brightgreen.svg)](https://github.com/modern-python/autosemver/actions/workflows/ci.yml)
[![CI](https://github.com/modern-python/autosemver/actions/workflows/ci.yml/badge.svg)](https://github.com/modern-python/autosemver/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/modern-python/autosemver.svg)](https://github.com/modern-python/autosemver/blob/main/LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/modern-python/autosemver)](https://github.com/modern-python/autosemver/stargazers)
[![Context7](https://img.shields.io/badge/Context7-docs-blue)](https://context7.com/modern-python/autosemver)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![ty](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ty/main/assets/badge/v0.json)](https://github.com/astral-sh/ty)
```

Drop the Context7 line if Task 1 marked `autosemver` NOT-indexed.

- [ ] **Step 3:** Apply **REFERENCE: Footer** with `<repo>=autosemver`, `<pkg>=semvertag`. Docs line: keep (docs.yml present).
- [ ] **Step 4:** Steps c, d.
- [ ] **Step 5:** Steps e, f.

---

## Task 15: `modern-di` (archetype C — keep the table)

**Files:** Modify `~/src/pypi/modern-di/README.md`

- [ ] **Step 1:** Branch (Step a), `<repo>=modern-di`.
- [ ] **Step 2:** Change the title to lowercase ATX `# modern-di` (currently `"Modern-DI"\n==`). **Keep the existing per-package badge table unchanged.**
- [ ] **Step 3:** Insert the **REFERENCE: Header C** flat badge row between the `# modern-di` title and the table (drop Context7 line if Task 1 marked NOT-indexed):

```markdown
# modern-di

[![Context7](https://img.shields.io/badge/Context7-docs-blue)](https://context7.com/modern-python/modern-di)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![ty](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ty/main/assets/badge/v0.json)](https://github.com/astral-sh/ty)

| Project | Badges |
... (existing table unchanged) ...
```

- [ ] **Step 4:** Apply **REFERENCE: Footer** with `<repo>=modern-di`, `<pkg>=modern-di`. Docs line: keep (docs.yml present). Replace the existing footer tail.
- [ ] **Step 5:** Steps c, d (confirm the table is intact and unmodified in the diff).
- [ ] **Step 6:** Steps e, f.

---

## Task 16: `that-depends` (archetype D — showcase)

**Files:** Modify `~/src/pypi/that-depends/README.md`

- [ ] **Step 1:** Branch (Step a), `<repo>=that-depends`.
- [ ] **Step 2:** Replace the existing title + badge block (lines 1–9) with **REFERENCE: Header D** verbatim. Keep the `> Starting a new project?` callout and `## Ecosystem` body intact below.
- [ ] **Step 3:** Apply **REFERENCE: Footer** with `<repo>=that-depends`, `<pkg>=that-depends`. Docs line: keep (docs site live).
- [ ] **Step 4:** Steps c, d. Note: codecov, libs.tech, pyrefly, llms.txt badge URLs are expected `200`; if libs.tech returns non-200, keep it (its project-id badge can rate-limit) but flag.
- [ ] **Step 5:** Steps e, f.

---

## Task 17: `fastapi-sqlalchemy-template` (archetype E)

**Files:** Modify `~/src/fastapi-sqlalchemy-template/readme.md` (lowercase — preserve casing)

- [ ] **Step 1:** Branch (Step a), `$ROOT=~/src`, `<repo>=fastapi-sqlalchemy-template`.
- [ ] **Step 2:** Apply **REFERENCE: Header E** with `<repo>=fastapi-sqlalchemy-template`. Title `# fastapi-sqlalchemy-template`; keep the existing tagline `Production-ready dockerized async REST API on FastAPI with SQLAlchemy and PostgreSQL` as the first body line. **Drop** the existing `Test Coverage` (codecov), `GitHub issues`, and `GitHub forks` badges. Drop Context7 line if Task 1 marked NOT-indexed. Resolved badge block:

```markdown
# fastapi-sqlalchemy-template

Production-ready dockerized async REST API on FastAPI with SQLAlchemy and PostgreSQL.

[![Coverage](https://img.shields.io/badge/coverage-100%25-brightgreen.svg)](https://github.com/modern-python/fastapi-sqlalchemy-template/actions/workflows/ci.yml)
[![CI](https://github.com/modern-python/fastapi-sqlalchemy-template/actions/workflows/ci.yml/badge.svg)](https://github.com/modern-python/fastapi-sqlalchemy-template/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/modern-python/fastapi-sqlalchemy-template.svg)](https://github.com/modern-python/fastapi-sqlalchemy-template/blob/main/LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/modern-python/fastapi-sqlalchemy-template)](https://github.com/modern-python/fastapi-sqlalchemy-template/stargazers)
[![Context7](https://img.shields.io/badge/Context7-docs-blue)](https://context7.com/modern-python/fastapi-sqlalchemy-template)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![ty](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ty/main/assets/badge/v0.json)](https://github.com/astral-sh/ty)
```

Keep the existing `## Key Features` and other body sections, including the existing `## Part of modern-python` block (it will be normalized by the footer step).

- [ ] **Step 3:** Apply **REFERENCE: Footer** with `<repo>=fastapi-sqlalchemy-template`. **Drop the `## 📦 [PyPI]` line** (template, not on PyPI). Docs line: drop unless Task 1 found a live site. The existing README already ends with a `## Part of modern-python` block — replace it with the footer block (without the PyPI line).
- [ ] **Step 4:** Verify the CI workflow filename is `ci.yml` for this repo before committing:

```bash
ls ~/src/fastapi-sqlalchemy-template/.github/workflows/
```

Expected: includes `ci.yml`. If the CI workflow has a different name, substitute it in the Coverage + CI badge URLs.

- [ ] **Step 5:** Steps c, d.
- [ ] **Step 6:** Steps e, f.

---

## Task 18: `litestar-sqlalchemy-template` (archetype E)

**Files:** Modify `~/src/litestar-sqlalchemy-template/readme.md` (lowercase — preserve casing)

- [ ] **Step 1:** Branch (Step a), `$ROOT=~/src`, `<repo>=litestar-sqlalchemy-template`.
- [ ] **Step 2:** Apply **REFERENCE: Header E** with `<repo>=litestar-sqlalchemy-template`. Title `# litestar-sqlalchemy-template`; keep the existing tagline as the first body line. **Drop** the existing codecov/issues/forks badges. Drop Context7 line if Task 1 marked NOT-indexed. Resolved badge block:

```markdown
# litestar-sqlalchemy-template

Production-ready dockerized async REST API on LiteStar with SQLAlchemy and PostgreSQL.

[![Coverage](https://img.shields.io/badge/coverage-100%25-brightgreen.svg)](https://github.com/modern-python/litestar-sqlalchemy-template/actions/workflows/ci.yml)
[![CI](https://github.com/modern-python/litestar-sqlalchemy-template/actions/workflows/ci.yml/badge.svg)](https://github.com/modern-python/litestar-sqlalchemy-template/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/modern-python/litestar-sqlalchemy-template.svg)](https://github.com/modern-python/litestar-sqlalchemy-template/blob/main/LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/modern-python/litestar-sqlalchemy-template)](https://github.com/modern-python/litestar-sqlalchemy-template/stargazers)
[![Context7](https://img.shields.io/badge/Context7-docs-blue)](https://context7.com/modern-python/litestar-sqlalchemy-template)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![ty](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ty/main/assets/badge/v0.json)](https://github.com/astral-sh/ty)
```

- [ ] **Step 3:** Apply **REFERENCE: Footer** with `<repo>=litestar-sqlalchemy-template`. **Drop the `## 📦 [PyPI]` line.** Docs line: drop unless live.
- [ ] **Step 4:** Verify CI workflow filename is `ci.yml` (`ls ~/src/litestar-sqlalchemy-template/.github/workflows/`); substitute if different.
- [ ] **Step 5:** Steps c, d.
- [ ] **Step 6:** Steps e, f.

---

## Task 19: Final sweep

- [ ] **Step 1:** List all opened PRs to confirm 17 exist.

```bash
for r in ~/src/pypi/{db-retry,eof-fixer,faststream-concurrent-aiokafka,faststream-outbox,faststream-redis-timers,httpware,lite-bootstrap,modern-di,modern-di-fastapi,modern-di-faststream,modern-di-litestar,modern-di-pytest,modern-di-typer,that-depends,autosemver} ~/src/{fastapi-sqlalchemy-template,litestar-sqlalchemy-template}; do
  printf '%s ' "$(basename "$r")"; gh -R "modern-python/$(basename "$r")" pr list --head docs/uniform-readme --json url --jq '.[0].url // "MISSING"'
done
```

Expected: 17 PR URLs, none `MISSING`.

- [ ] **Step 2:** Spot-check the GitHub-rendered README of 3 PRs (one archetype A, `modern-di`, one template) to confirm badges render and bodies are unchanged.

---

## Notes / known facts (from spec + investigation)

- CI workflow filename is `ci.yml` in every library repo (verified). Templates verified per-task (Tasks 17/18 Step 4).
- Coverage guard `cov-fail-under=100` present in all repos **except `that-depends`** → `that-depends` is the only repo keeping a live codecov badge instead of the static 100% badge.
- `autosemver` repo publishes to PyPI as `semvertag`.
- Astral trio (uv/ruff/ty) on every repo **except `that-depends`**.
- `modern-di` keeps its sub-package badge table; do not flatten it.
- Each repo is a separate git remote → 17 independent PRs; there is no way to batch them into one PR.
