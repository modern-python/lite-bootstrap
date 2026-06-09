# MkDocs GitHub Actions Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Read the Docs with GitHub Actions → GitHub Pages docs deployment, mirroring the modern-di sibling project's setup.

**Architecture:** A push to `main` that touches docs files triggers `.github/workflows/docs.yml`, which runs `just docs-deploy`. The recipe invokes `uvx --with-requirements docs/requirements.txt mkdocs gh-deploy --force`, force-pushing the built site to the `gh-pages` branch. GitHub Pages serves `gh-pages` under the custom subdomain `lite-bootstrap.modern-python.org` (set via `docs/CNAME`).

**Tech Stack:** MkDocs + mkdocs-material, GitHub Actions, GitHub Pages, `uv`/`uvx`, `just`.

**Spec:** `planning/specs/2026-06-09-mkdocs-github-actions-design.md`

---

## File-level overview

| File | Action | Responsibility |
|---|---|---|
| `.github/workflows/docs.yml` | Create | CI workflow that deploys docs on push to `main` |
| `Justfile` | Modify (append recipe) | `docs-deploy` recipe invoked by CI |
| `mkdocs.yml` | Modify (add `site_url`) | Canonical site URL for sitemap and Material theme |
| `docs/CNAME` | Create | Custom domain tag read by GitHub Pages from `gh-pages` |
| `pyproject.toml` | Modify (add `docs` URL) | PyPI "Documentation" link |
| `.readthedocs.yaml` | Delete | Remove RTD trigger in the same PR |

Order of tasks: lowest-risk first (`Justfile`, `mkdocs.yml`, `CNAME`, `pyproject.toml`), then the workflow, then RTD removal, then integration verification.

---

## Pre-flight

- [ ] **Step 1: Confirm working tree clean and on a fresh branch**

```bash
git status
git checkout -b docs/migrate-to-github-actions
```

Expected: clean working tree, new branch checked out.

- [ ] **Step 2: Confirm `uvx` is available and docs deps install cleanly (no changes yet)**

```bash
uvx --with-requirements docs/requirements.txt mkdocs --version
```

Expected: prints an mkdocs version string (e.g. `mkdocs, version 1.6.x`) without errors. This proves the docs toolchain works before we wire it into CI.

---

## Task 1: Add `docs-deploy` recipe to `Justfile`

**Files:**
- Modify: `Justfile` (append to end)

**Context:** Modern-di's `Justfile` ends with this exact recipe. The two-line comment is intentional — it documents the foot-gun that running this locally from a stale checkout will roll the live site backward. CI is the only intended caller.

- [ ] **Step 1: Append the recipe**

Append to `Justfile`:

```
# Force-pushes built site to gh-pages; CI runs this on push to main.
# Manual invocation from a stale checkout will roll the live site back.
docs-deploy:
    uvx --with-requirements docs/requirements.txt mkdocs gh-deploy --force
```

- [ ] **Step 2: Confirm `just` recognises the recipe**

Run: `just --list`
Expected output includes a line containing `docs-deploy`.

- [ ] **Step 3: Verify the recipe text by inspecting `just`'s view of it**

Run: `just --show docs-deploy`
Expected: prints the recipe body exactly as written above.

**Do NOT run `just docs-deploy` locally** — it would force-push the current checkout's build to `gh-pages`, which only exists once GitHub Pages is set up. CI will be the first caller.

- [ ] **Step 4: Commit**

```bash
git add Justfile
git commit -m "build: add docs-deploy Justfile recipe

Mirrors the modern-di pattern; intended to be invoked from CI on push to
main. Local invocation force-pushes from the current checkout, so the
recipe carries an inline warning about stale checkouts."
```

---

## Task 2: Add `site_url` to `mkdocs.yml`

**Files:**
- Modify: `mkdocs.yml:2` (insert new line under `site_name`)

**Context:** Without `site_url`, the generated `sitemap.xml` contains relative URLs, the canonical `<link>` tag is missing from `<head>`, and Material theme features that need an absolute base URL silently degrade. Adding it now keeps the first deploy clean.

- [ ] **Step 1: Edit `mkdocs.yml`**

Find:
```yaml
site_name: lite-bootstrap
repo_url: https://github.com/modern-python/lite-bootstrap
```

Replace with:
```yaml
site_name: lite-bootstrap
site_url: https://lite-bootstrap.modern-python.org
repo_url: https://github.com/modern-python/lite-bootstrap
```

- [ ] **Step 2: Verify the docs still build with `--strict`**

Run:
```bash
uvx --with-requirements docs/requirements.txt mkdocs build --strict --site-dir /tmp/lite-bootstrap-docs-build
```

Expected: exits 0. `--strict` upgrades warnings (broken links, dangling nav entries) to errors; this is the strongest local check available short of deploying. Clean up after: `rm -rf /tmp/lite-bootstrap-docs-build`.

- [ ] **Step 3: Confirm `site_url` reached the rendered HTML**

```bash
uvx --with-requirements docs/requirements.txt mkdocs build --site-dir /tmp/lite-bootstrap-docs-build
grep -c 'lite-bootstrap.modern-python.org' /tmp/lite-bootstrap-docs-build/sitemap.xml
rm -rf /tmp/lite-bootstrap-docs-build
```

Expected: `grep -c` prints a positive integer (≥1) — the canonical hostname appears in the sitemap.

- [ ] **Step 4: Commit**

```bash
git add mkdocs.yml
git commit -m "docs: set site_url for github-pages deployment

site_url is required for canonical URLs in <head>, sitemap.xml, and any
Material theme feature that needs an absolute base URL."
```

---

## Task 3: Create `docs/CNAME`

**Files:**
- Create: `docs/CNAME`

**Context:** `mkdocs gh-deploy` copies files from `docs/` (and other configured directories) into the built site. GitHub Pages then reads `CNAME` from the `gh-pages` branch root to bind the custom domain. Single line, no extension, no trailing whitespace, exactly one newline at end-of-file (the repo uses `eof-fixer` in `lint`; an empty final line is required).

- [ ] **Step 1: Create the file**

Create `docs/CNAME` with exactly this content (one line plus terminating newline):

```
lite-bootstrap.modern-python.org
```

- [ ] **Step 2: Verify file shape**

```bash
wc -l docs/CNAME
xxd docs/CNAME | tail -1
```

Expected: `wc -l` reports `1` (one line). `xxd` tail shows the final byte is `0a` (newline), no carriage returns, no trailing spaces.

- [ ] **Step 3: Verify `eof-fixer` is happy**

```bash
uv run eof-fixer docs/CNAME --check
```

Expected: exits 0 with no output.

- [ ] **Step 4: Confirm `mkdocs build` copies `CNAME` into the site**

```bash
uvx --with-requirements docs/requirements.txt mkdocs build --site-dir /tmp/lite-bootstrap-docs-build
cat /tmp/lite-bootstrap-docs-build/CNAME
rm -rf /tmp/lite-bootstrap-docs-build
```

Expected: prints `lite-bootstrap.modern-python.org`. If the file is absent from the built site, mkdocs may need an `extra_files` directive — this is not the case for default mkdocs because it copies all non-markdown files from `docs/` automatically, but verify here so we catch any version-specific surprise before merging.

- [ ] **Step 5: Commit**

```bash
git add docs/CNAME
git commit -m "docs: add CNAME for lite-bootstrap.modern-python.org

GitHub Pages reads this from the gh-pages branch root to bind the
custom subdomain. mkdocs copies it into the built site automatically."
```

---

## Task 4: Update `[project.urls]` in `pyproject.toml`

**Files:**
- Modify: `pyproject.toml:37-39`

**Context:** The PyPI page renders `[project.urls]` entries as named links. Currently only `repository` is set; adding `docs` makes the docs link appear on PyPI on the next release. Modern-di's order is `repository` then `docs` — match.

- [ ] **Step 1: Edit `pyproject.toml`**

Find:
```toml
[project.urls]
repository = "https://github.com/modern-python/lite-bootstrap"
```

Replace with:
```toml
[project.urls]
repository = "https://github.com/modern-python/lite-bootstrap"
docs = "https://lite-bootstrap.modern-python.org"
```

- [ ] **Step 2: Verify TOML still parses and lockfile is unchanged**

```bash
uv lock --check
```

Expected: exits 0 (lockfile up-to-date; the URLs section does not affect the dependency graph, so no relock needed).

- [ ] **Step 3: Run lint to ensure no formatting drift**

```bash
just lint-ci
```

Expected: exits 0 (eof-fixer, ruff format check, ruff check, ty check all pass).

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "build: add docs URL to project.urls

PyPI renders this as the 'Documentation' link on the project page."
```

---

## Task 5: Create `.github/workflows/docs.yml`

**Files:**
- Create: `.github/workflows/docs.yml`

**Context:** Verbatim from `../modern-di/.github/workflows/docs.yml`. Each design choice is load-bearing — read the inline notes below before editing.

- [ ] **Step 1: Create the workflow file**

Create `.github/workflows/docs.yml`:

```yaml
name: Deploy Docs

on:
  push:
    branches: [main]
    paths:
      - "docs/**"
      - "mkdocs.yml"
      - ".github/workflows/docs.yml"
  workflow_dispatch:

concurrency:
  group: docs-deploy
  cancel-in-progress: true

permissions:
  contents: write

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
        with:
          fetch-depth: 0
      - uses: extractions/setup-just@v4
      - uses: astral-sh/setup-uv@v8.2.0
      - run: just docs-deploy
```

Design notes (for the engineer reviewing this — do **not** weaken any of these):

- `paths:` filter — prevents redeploys on commits that only change `src/` or tests. The list intentionally includes `.github/workflows/docs.yml` so workflow edits trigger a redeploy too.
- `concurrency: docs-deploy` + `cancel-in-progress: true` — if two pushes land near-simultaneously, the older one is cancelled before it can force-push a stale build over the newer one.
- `permissions: contents: write` — required for `mkdocs gh-deploy --force` to push to `gh-pages`. The default `GITHUB_TOKEN` would be read-only without this.
- `fetch-depth: 0` — `mkdocs gh-deploy` updates the `gh-pages` branch via git, which fails on a shallow clone. Do not remove.
- Action versions match modern-di. The lite-bootstrap `ci.yml` is older (`checkout@v4`, `setup-just@v2`, `setup-uv@v3`); leave those alone — out of scope.

- [ ] **Step 2: Validate YAML syntax**

```bash
uvx --from yamllint yamllint -d '{extends: relaxed, rules: {line-length: disable}}' .github/workflows/docs.yml
```

Expected: exits 0 with no output. (yamllint catches typos, indentation errors, duplicate keys.)

- [ ] **Step 3: Optional — schema-validate with `actionlint`**

```bash
# only if actionlint is installed locally; skip otherwise
command -v actionlint && actionlint .github/workflows/docs.yml || echo "actionlint not installed — relying on GitHub-side validation post-push"
```

Expected: if `actionlint` is installed, exits 0 with no output. If not installed, prints the fallback message; GitHub will validate on push.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/docs.yml
git commit -m "ci: add docs deployment workflow

Builds the mkdocs site and force-pushes to gh-pages on push to main when
docs files change. Mirrors modern-di's pattern: paths filter, deploy
concurrency group, contents: write permission, fetch-depth: 0."
```

---

## Task 6: Delete `.readthedocs.yaml`

**Files:**
- Delete: `.readthedocs.yaml`

**Context:** Once this file is removed, Read the Docs stops triggering builds on push (RTD still serves the *last* successful build, but the project is dormant from a build-pipeline perspective). The RTD project record on readthedocs.io is not affected and should be archived manually after the new site is verified live (operator follow-up, post-merge).

- [ ] **Step 1: Remove the file**

```bash
git rm .readthedocs.yaml
```

Expected: file deleted from working tree and staged for commit.

- [ ] **Step 2: Confirm no other files reference it**

```bash
grep -rn '\.readthedocs\.yaml\|readthedocs\.io' . --include='*.md' --include='*.yml' --include='*.yaml' --include='*.toml' --exclude-dir=.git --exclude-dir=.venv --exclude-dir=planning
```

Expected: no matches. (`planning/` is excluded because the design spec legitimately references the RTD URL and the file being deleted.) If any match appears outside of `planning/`, update it to point at the new domain.

- [ ] **Step 3: Commit**

```bash
git commit -m "ci: remove read-the-docs config

Docs now deploy via GitHub Actions to gh-pages. RTD project will be
archived on readthedocs.io after the new site is verified live."
```

---

## Task 7: Final integration verification

**Files:** none (verification only)

- [ ] **Step 1: Re-run lint and tests**

```bash
just lint-ci
just test
```

Expected: both exit 0. Confirms none of the config/URL edits broke anything checked by the existing CI.

- [ ] **Step 2: One more `--strict` docs build with all changes in place**

```bash
uvx --with-requirements docs/requirements.txt mkdocs build --strict --site-dir /tmp/lite-bootstrap-docs-final
test -f /tmp/lite-bootstrap-docs-final/CNAME && echo "CNAME present"
grep -q 'lite-bootstrap.modern-python.org' /tmp/lite-bootstrap-docs-final/sitemap.xml && echo "site_url present in sitemap"
rm -rf /tmp/lite-bootstrap-docs-final
```

Expected: build exits 0; both echo lines print.

- [ ] **Step 3: Review the staged commits**

```bash
git log --oneline origin/main..HEAD
```

Expected: 6 commits (Justfile, mkdocs.yml, CNAME, pyproject.toml, workflow, RTD removal). Order is fine for review either way.

---

## Task 8: Push branch and open PR

**Files:** none (git/gh operations only)

- [ ] **Step 1: Push branch**

```bash
git push -u origin docs/migrate-to-github-actions
```

- [ ] **Step 2: Open PR with operator follow-up checklist**

The operator follow-ups from the spec ("Out of repo scope") must appear in the PR body so the reviewer / merger does not miss them.

```bash
gh pr create --title "docs: migrate from Read the Docs to GitHub Actions + Pages" --body "$(cat <<'EOF'
## Summary

- Replaces Read the Docs with a GitHub Actions workflow that force-pushes the built site to `gh-pages` on push to `main`.
- GitHub Pages serves `gh-pages` under `lite-bootstrap.modern-python.org` (`docs/CNAME`).
- Mirrors the sibling [`modern-di`](https://github.com/modern-python/modern-di) project's docs deployment pattern verbatim.

Spec: `planning/specs/2026-06-09-mkdocs-github-actions-design.md`
Plan: `planning/plans/2026-06-09-mkdocs-github-actions-plan.md`

## Operator follow-ups (post-merge)

These actions happen outside the repo and must be performed in order after merging:

1. **DNS** — on the `modern-python.org` zone, add a `CNAME` record: `lite-bootstrap` → `modern-python.github.io`. (Same as the existing `modern-di.modern-python.org` record.)
2. **Trigger first deploy** — either let the merge commit trigger it (if it touches docs files) or run the workflow manually via `Actions → Deploy Docs → Run workflow`. First run creates the `gh-pages` branch.
3. **Enable GitHub Pages** — repo Settings → Pages → Source: 'Deploy from a branch' → `gh-pages` / `(root)`. Custom domain auto-populates from `CNAME`.
4. **Update repo homepage** — `gh repo edit modern-python/lite-bootstrap --homepage https://lite-bootstrap.modern-python.org`
5. **Archive RTD project** — on readthedocs.io, mark the project archived once the new site is verified live.

## Test plan

- [ ] CI green on PR (`main` workflow runs lint + pytest as today; docs workflow does not run on PRs by design).
- [ ] After merge: `Deploy Docs` workflow runs green on the merge commit.
- [ ] `gh-pages` branch is created and contains the built site + `CNAME`.
- [ ] Once DNS and Pages are configured: https://lite-bootstrap.modern-python.org serves the site.
- [ ] PyPI 'Documentation' link points to the new domain on the next release.

EOF
)"
```

Expected: PR URL printed.

---

## Done

After merging:

1. Watch the first run of `Deploy Docs` (it will only trigger if the merge commit touches docs files — otherwise dispatch manually via `Actions → Deploy Docs → Run workflow`).
2. Walk the operator-follow-up checklist from the PR body in order.
3. Verify the live site, then archive the RTD project.
