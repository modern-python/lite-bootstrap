# Uniform README header + footer across modern-python org

**Date:** 2026-06-13
**Status:** Design — approved pending spec review
**Scope:** Standardize the **header (title + badge block)** and **footer (links + "Part of modern-python")** of every README across the `modern-python` org. Each repo's hand-written body is left untouched.

## Goal

Give every `modern-python` repo a consistent, recognizable README header and footer: a uniform title style, a standardized ordered badge block, and a uniform footer with documentation/PyPI/license links and a "Part of `modern-python`" pointer. Bodies (features, quickstart, usage prose, design notes) stay as their authors wrote them.

## Scope

### In scope — 17 repos

**15 libraries** (`github.com/modern-python`):
`autosemver`, `db-retry`, `eof-fixer`, `faststream-concurrent-aiokafka`, `faststream-outbox`, `faststream-redis-timers`, `httpware`, `lite-bootstrap`, `modern-di`, `modern-di-fastapi`, `modern-di-faststream`, `modern-di-litestar`, `modern-di-pytest`, `modern-di-typer`, `that-depends`.

**2 templates** (`github.com/modern-python`, located in `~/src/`):
`fastapi-sqlalchemy-template`, `litestar-sqlalchemy-template`.

### Out of scope

Repos present locally under `~/src/pypi/` but owned by other orgs:
`aiokafka` & `faststream` (`lesnik512`), `base-client` & `stompman` (`community-of-python`), `dishka` (`reagento`).

Only the header and footer change. No body rewrites, no section reshaping, no unrelated refactoring.

## Decisions

| Topic | Decision |
|-------|----------|
| **Uniformity scope** | Header (title + badges) and footer only. Bodies untouched. |
| **Title style** | Lowercase ATX `# <package-name>` for libraries (clickable anchor, matches `pip install`). Templates have no package → keep a descriptive ATX `#` H1. |
| **Standard badges** | PyPI version · Supported Python versions · Downloads (pypistats) · Coverage · CI · License · GitHub stars. |
| **Downloads source** | Standardized on **pypistats** (`img.shields.io/pypi/dm`) everywhere, including `that-depends` (currently pepy). |
| **CI badge** | `ci.yml` is the universal workflow filename across all repos. |
| **Coverage badge** | Static `coverage-100%` shields badge for repos enforcing `cov-fail-under=100` (all 14 libs except `that-depends`, plus both templates). `that-depends` (no guard) keeps its live **codecov** badge. |
| **Astral toolchain badges** | uv + Ruff + ty trio on **all repos except `that-depends`** (libraries + templates). |
| **Context7 badge** | Static link badge on every repo, pointing to its own `context7.com/modern-python/<repo>` page. Skipped per-repo if that page is not indexed. |
| **`that-depends` (showcase)** | The **only** repo with type-checker (mypy-strict, pyrefly), `llms.txt`, and `libs.tech` badges. Keeps codecov (live). No uv/ruff/ty trio. Add missing core badges (PyPI version, CI, License) + Context7. |
| **`modern-di` (exception)** | Keeps its existing **sub-package badge table** as the primary badge presentation (the matrix of `modern-di` + integration packages). Standardized footer + Context7/toolchain badges still applied; the table is not flattened into a plain row. |
| **Templates** | Not on PyPI → no version/pyversions/downloads/PyPI-link badges. Get: static 100% coverage, CI, License, GitHub stars, Context7 (if indexed), uv/ruff/ty. **Drop** current GitHub issues/forks badges. |
| **Delivery** | One PR per repo (17 total), branch `docs/uniform-readme`. |

## Canonical templates

### Library header (14 standard libs, all except `that-depends`)

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

`<pkg>` = PyPI name, `<repo>` = GitHub repo slug. They differ only for `autosemver` (repo) → `semvertag` (pkg).

### `that-depends` header (showcase)

Retains its existing rich badge set, normalized order, with these changes:
- Add: PyPI version, CI (`ci.yml`), License, Context7 (`context7.com/modern-python/that-depends`).
- Keep: codecov (live), mypy-strict, pyrefly, Python versions, downloads (switch pepy → pypistats), GitHub stars, `libs.tech`, `llms.txt`.
- Do **not** add the uv/ruff/ty trio and do **not** add the static 100% badge.

### `modern-di` header (table exception)

Keep the existing per-package badge **table** (rows: `common`, `modern-di`, `modern-di-fastapi`, `modern-di-faststream`, `modern-di-litestar`, `modern-di-pytest`, `modern-di-typer`). Add the Context7 + uv/ruff/ty badges as a flat row beneath the title (above the table), apply the standardized footer. Do not flatten the table.

### Template header (2 templates, not on PyPI)

```markdown
# <repo>

<one-line tagline as body, not title>

[![Coverage](https://img.shields.io/badge/coverage-100%25-brightgreen.svg)](https://github.com/modern-python/<repo>/actions/workflows/ci.yml)
[![CI](https://github.com/modern-python/<repo>/actions/workflows/ci.yml/badge.svg)](https://github.com/modern-python/<repo>/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/modern-python/<repo>.svg)](https://github.com/modern-python/<repo>/blob/main/LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/modern-python/<repo>)](https://github.com/modern-python/<repo>/stargazers)
[![Context7](https://img.shields.io/badge/Context7-docs-blue)](https://context7.com/modern-python/<repo>)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![ty](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ty/main/assets/badge/v0.json)](https://github.com/astral-sh/ty)
```

Drop the existing `GitHub issues` and `GitHub forks` badges. Note: template READMEs are currently named `readme.md` (lowercase) — preserve the existing filename casing per repo.

### Footer (all repos)

```markdown
## 📚 [Documentation](https://<repo>.modern-python.org)
## 📦 [PyPI](https://pypi.org/project/<pkg>)
## 📝 [License](LICENSE)

## Part of `modern-python`

Browse the full list of templates and libraries in
[`modern-python`](https://github.com/modern-python) — see the org profile for the categorized index.
```

- `📚 Documentation` line: included only where a live `<repo>.modern-python.org` site exists.
- `📦 PyPI` line: libraries only; omitted for templates.

## Per-repo resolution table

Resolved during implementation; `?` = verify per-repo (Context7 indexing, docs site).

| repo | pkg | 100% guard | coverage badge | docs site | astral trio | context7 |
|------|-----|:--:|--------|:--:|:--:|:--:|
| autosemver | **semvertag** | ✔ | static 100% | ✔ (docs.yml) | ✔ | ? |
| db-retry | db-retry | ✔ | static 100% | ? | ✔ | ? |
| eof-fixer | eof-fixer | ✔ | static 100% | ? | ✔ | ? |
| faststream-concurrent-aiokafka | (same) | ✔ | static 100% | ? | ✔ | ? |
| faststream-outbox | (same) | ✔ | static 100% | ✔ (docs.yml) | ✔ | ? |
| faststream-redis-timers | (same) | ✔ | static 100% | ✔ (docs.yml) | ✔ | ? |
| httpware | httpware | ✔ | static 100% | ✔ (docs.yml) | ✔ | ? |
| lite-bootstrap | lite-bootstrap | ✔ | static 100% | ✔ | ✔ | ✔ |
| modern-di | modern-di | ✔ | (table) | ✔ (docs.yml) | ✔ | ? |
| modern-di-fastapi | (same) | ✔ | static 100% | ? | ✔ | ? |
| modern-di-faststream | (same) | ✔ | static 100% | ? | ✔ | ? |
| modern-di-litestar | (same) | ✔ | static 100% | ? | ✔ | ? |
| modern-di-pytest | (same) | ✔ | static 100% | ? | ✔ | ? |
| modern-di-typer | (same) | ✔ | static 100% | ? | ✔ | ? |
| that-depends | that-depends | ✘ | **codecov (live)** | ✔ | ✘ | ✔ |
| fastapi-sqlalchemy-template | — | ✔ | static 100% | ? | ✔ | ? |
| litestar-sqlalchemy-template | — | ✔ | static 100% | ? | ✔ | ? |

## Rollout

One PR per repo (17 total). Per repo:

1. Branch `docs/uniform-readme` from the default branch.
2. Edit only the header (title + badge block) and footer; leave the body intact.
3. Resolve per-repo variables: PyPI name, docs-site presence, Context7 indexing.
4. Verify every badge URL resolves (HTTP 200 / valid SVG); skip Context7 badge if the page is not indexed.
5. Commit, push, open a PR with a shared body explaining the org-wide README standardization and linking back to this spec.

## Risks / notes

- **Static 100% badge** asserts a value, not a live measurement. It is truthful because `cov-fail-under=100` is enforced in CI; if a repo later drops the guard, the badge must be revisited.
- **Context7 indexing** is verified per-repo; some smaller repos may not be indexed yet, in which case the badge is omitted.
- **Docs sites** are verified per-repo; the `📚 Documentation` line is omitted where no live site exists.
- **`modern-di` table** is deliberately preserved; do not normalize it into the flat badge row.
- **Template filename casing** (`readme.md`) is preserved per repo.
