# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Layout

Single-context, and flat:

```
/
├── CONTEXT.md
├── docs/adr/
│   ├── 0001-fastmcp-teardown-via-provider-lifespan.md
│   └── ...
└── lite_bootstrap/
```

There is no `CONTEXT-MAP.md` and no per-package `CONTEXT.md` or `docs/adr/`. If you are looking for
either, the answer is that this repo does not have them.

## Before exploring, read these

- **`CONTEXT.md`** at the repo root. It owns the vocabulary, and `AGENTS.md` requires reading it
  before naming a concept in code, a test name, or an issue title. The **configured** / **ready**
  split and the two kinds of **skip** are defined there and are load-bearing throughout.
- **`docs/adr/`**: read the ADRs that touch the area you are about to work in. They are an internal
  decision record, excluded from the published docs site, so an ADR is written for contributors
  rather than users.

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `CONTEXT.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal: either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0002 (keep the per-instrument axis), but worth reopening because…_
