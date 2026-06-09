# Migrate docs from Read the Docs to GitHub Actions + Pages

Date: 2026-06-09
Status: Approved (pending written-spec review)

## Goal

Replace the current Read the Docs build pipeline with a GitHub Actions workflow that builds the MkDocs site and deploys it to `gh-pages`, served by GitHub Pages under the custom subdomain `lite-bootstrap.modern-python.org`. Mirror the setup already in use in the sibling `modern-di` project so both repos in the `modern-python` org share one deployment pattern.

## Current state

- `.readthedocs.yaml` at repo root drives RTD builds. RTD installs `docs/requirements.txt` and runs `mkdocs build` against `mkdocs.yml`.
- Site is served at `lite-bootstrap.readthedocs.io` (set as the GitHub repo `homepageUrl`).
- `mkdocs.yml` has no `site_url`. No `CNAME` file. No `[project.urls] docs` entry.
- No GitHub Actions workflow for docs. `ci.yml` only runs lint + pytest.

## Reference

`modern-di` (sibling repo at `../modern-di/`) already runs this pattern:

- `.github/workflows/docs.yml` — push-to-main + `workflow_dispatch`, paths-filtered to docs files.
- `Justfile` recipe `docs-deploy` — `uvx --with-requirements docs/requirements.txt mkdocs gh-deploy --force`.
- `mkdocs.yml` — `site_url: https://modern-di.modern-python.org`.
- `docs/CNAME` — single line `modern-di.modern-python.org`.
- `pyproject.toml` — `[project.urls] docs = "https://modern-di.modern-python.org"`.

This spec copies that pattern with names changed for lite-bootstrap.

## Changes

### 1. `.github/workflows/docs.yml` (new)

Verbatim from `modern-di/.github/workflows/docs.yml`:

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

Notes:

- `paths` filter prevents redeploys on unrelated commits.
- `concurrency: docs-deploy` + `cancel-in-progress: true` prevents stale-checkout overwrites if two pushes land near-simultaneously.
- `permissions: contents: write` is required for `mkdocs gh-deploy --force` to push to `gh-pages`.
- `fetch-depth: 0` is required by `mkdocs gh-deploy` to update the `gh-pages` branch (shallow clone would fail).
- Action versions (`checkout@v6`, `setup-just@v4`, `setup-uv@v8.2.0`) match modern-di. The lite-bootstrap `ci.yml` uses older versions; that stays unchanged here.

### 2. `Justfile` — append `docs-deploy` recipe

```
# Force-pushes built site to gh-pages; CI runs this on push to main.
# Manual invocation from a stale checkout will roll the live site back.
docs-deploy:
    uvx --with-requirements docs/requirements.txt mkdocs gh-deploy --force
```

Identical to modern-di. `uvx --with-requirements docs/requirements.txt` keeps docs dependencies isolated from the main project lockfile (mkdocs is not declared in `pyproject.toml`).

### 3. `mkdocs.yml` — add `site_url`

Insert immediately under `site_name`:

```yaml
site_url: https://lite-bootstrap.modern-python.org
```

Needed for canonical URLs in `<head>`, the generated `sitemap.xml`, and Material theme features that depend on absolute URLs.

### 4. `docs/CNAME` (new)

Single line:

```
lite-bootstrap.modern-python.org
```

`mkdocs gh-deploy` copies the file into the built site root; GitHub Pages reads it from the `gh-pages` branch to serve the custom domain.

### 5. `pyproject.toml` — add `docs` URL

Update `[project.urls]`:

```toml
[project.urls]
repository = "https://github.com/modern-python/lite-bootstrap"
docs = "https://lite-bootstrap.modern-python.org"
```

This becomes the PyPI "Documentation" link on the next release.

### 6. `.readthedocs.yaml` — delete

Once removed, RTD will stop triggering builds on push. The RTD project record on readthedocs.io is unchanged by this PR and should be archived manually post-cutover (see "Out of repo scope" below).

## Out of repo scope (operator follow-ups)

These actions happen outside the repo and are not part of the PR diff. They are listed here so the operator does not miss them:

1. **DNS** — add a `CNAME` record on the `modern-python.org` zone: `lite-bootstrap` → `modern-python.github.io`. Same setup as the existing `modern-di.modern-python.org` record.
2. **First workflow run** — first push to `main` after merge will create the `gh-pages` branch. The workflow uses `gh-deploy --force`, so the initial create is automatic.
3. **GitHub Pages enablement** — repo admin: Settings → Pages → Source: "Deploy from a branch" → `gh-pages` / `(root)`. The custom-domain field auto-populates from the `CNAME` file in the branch.
4. **GitHub repo homepage** — `gh repo edit --homepage https://lite-bootstrap.modern-python.org` (currently set to the RTD URL).
5. **Read the Docs project archival** — on the readthedocs.io dashboard, mark the project as archived after the new site is verified live. Not done in this PR so that RTD remains a fallback during cutover.

## Out of design scope (deliberate non-goals)

- **Action-version bumps in `ci.yml`** — modern-di uses `checkout@v6` / `setup-just@v4` / `setup-uv@v8.2.0` and split its workflow into a reusable `_checks.yml`. The lite-bootstrap `ci.yml` still uses `checkout@v4` / `setup-just@v2` / `setup-uv@v3` and is monolithic. Not touched here; the new `docs.yml` uses current versions because it is new code.
- **Build-on-PR check** — modern-di does not run `mkdocs build --strict` on PRs and neither will lite-bootstrap. Cheap to add later if broken docs slip through.
- **Doc content changes** — `nav`, theme, extensions are unchanged.

## Risk and rollback

- **First deploy failure** is harmless — the new domain has no users yet and RTD still works until `.readthedocs.yaml` is deleted (this happens in the same PR, so a failure on the first run leaves the site temporarily unbuilt until fixed; acceptable for a low-traffic library docs site).
- **Stale-checkout rollback** — `gh-deploy --force` overwrites `gh-pages` from whatever the checkout sees. The Justfile comment documents this. Manual invocation from an out-of-date local clone will roll the live site backward. CI is the only intended caller.
- **Reverting** — revert the PR; RTD config returns; RTD resumes building automatically. The RTD project remains linked to the repo until manually archived, so the fallback is always available.

## Acceptance criteria

- [ ] `docs.yml` workflow exists and runs on push to `main` when docs files change.
- [ ] `just docs-deploy` runs locally without error (Justfile recipe wired up; `uvx` reachable).
- [ ] `mkdocs.yml` declares `site_url: https://lite-bootstrap.modern-python.org`.
- [ ] `docs/CNAME` contains the custom domain on a single line, no trailing newline issues.
- [ ] `pyproject.toml` `[project.urls]` includes a `docs` key pointing at the custom domain.
- [ ] `.readthedocs.yaml` is removed.
- [ ] After merge: workflow runs green, `gh-pages` branch is created, GH Pages serves the site under the custom domain, repo homepage URL updated.
