---
status: approved
date: 2026-06-23
slug: structured-log-payload
spec: structured-log-payload
pr: null
---

# structured-log-payload — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps
> use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the structlog log-line contract into a `StructuredLogPayload`
value object in `logging_factory.py`, shrinking the Sentry instrument to
orchestration and closing the meta-key drift failure mode.

**Spec:** [`design.md`](./design.md)

**Branch:** `feat/structured-log-payload`

**Commit strategy:** Per-task commits (each task leaves the suite green).

TDD throughout: write the failing test first, watch it fail for the right
reason, then implement to green.

---

### Task 1: `StructuredLogPayload` + `STRUCTLOG_META_KEYS` in `logging_factory.py` (red → green)

**Files:**
- Modify: `lite_bootstrap/instruments/logging_factory.py`
- Modify: `tests/instruments/test_logging_instrument.py` (or new
  `tests/instruments/test_structured_log_payload.py` — match where factory tests
  already live)

Introduce the value object and the meta-key vocabulary it owns; prove `parse`
against a table before implementing it.

- [ ] **Step 1: Write the `parse` table, red.**

  Cases (raw JSON string in → assert on `message` / `extra` / `skip_sentry`):
  - non-JSON string (`"plain message"`) → `None`
  - JSON non-dict (`"[1, 2]"`) → `None`
  - malformed JSON starting with `{` → `None`
  - dict without `event` → `payload.message is None`
  - normal line (`event` + meta-keys + user kwargs) → `extra` has user kwargs
    only, all `STRUCTLOG_META_KEYS` stripped
  - `skip_sentry: true` → `payload.skip_sentry is True`
  - **DES-4**: `skip_sentry: false` present → stripped from `extra`
    (add comment: `# DES-4 (planning/audits/2026-06-05-bug-audit-v2.md): falsy
    skip_sentry must not leak into extra`)

  Run `just test -- -k structured_log` → fails (symbol does not exist yet).

- [ ] **Step 2: Implement `STRUCTLOG_META_KEYS` + `StructuredLogPayload`.**

  Move the frozenset out of `sentry_instrument.py`, rename to
  `STRUCTLOG_META_KEYS`, place beside `_serialize_log_with_orjson_to_string`.
  Implement `parse` owning all guards (`startswith("{")`, `JSONDecodeError`,
  non-dict) and the meta-strip. `message`, `extra`, `skip_sentry` fields; no
  `serialize()`; no Sentry-event knowledge.

  Run `just test -- -k structured_log` → green.

- [ ] **Step 3: Add the round-trip test (drift net), red → green.**

  Build a representative `event_dict` (the keys the producer chain emits) →
  `_serialize_log_with_orjson_to_string(event_dict)` → `StructuredLogPayload.parse`
  → assert `message` / `extra` (meta stripped) / `skip_sentry`. Green once Step 2
  lands.

- [ ] **Step 4: Cross-reference comment at the chain.**

  In `logging_instrument.py`, at `tracer_injection` / the processor chain, add a
  one-line comment: any new top-level meta-key must be added to
  `STRUCTLOG_META_KEYS` in `logging_factory.py`.

- [ ] **Step 5: Commit.**

  ```bash
  git add lite_bootstrap/instruments/logging_factory.py \
          lite_bootstrap/instruments/logging_instrument.py \
          tests/instruments/
  git commit -m "feat: add StructuredLogPayload value object owning log-line parse

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 2: Shrink the Sentry instrument to orchestration

**Files:**
- Modify: `lite_bootstrap/instruments/sentry_instrument.py`
- Modify: `tests/instruments/test_sentry_instrument.py`

Rewrite `enrich_sentry_event_from_structlog_log` to call `parse`, leave the
back-compat alias, slim the tests to the three mapping outcomes.

- [ ] **Step 1: Slim the Sentry tests, keeping behavior pins.**

  Reduce the existing parametrized cases to three orchestration outcomes:
  drop (`skip_sentry` truthy), modify+attach (normal), passthrough
  (non-structlog / `event`-less). Add an explicit case: `skip_sentry` truthy +
  no `event` key still returns `None` (ordering pin). Remove the shape-detail
  assertions now covered at the value-object layer (DES-4 relocated in Task 1).

  Run `just test -- -k sentry` → fails against the current implementation only
  where the slimmed expectations differ; confirm the failures are the expected
  shape before proceeding.

- [ ] **Step 2: Rewrite `enrich_sentry_event_from_structlog_log`.**

  Replace the inline sniff/parse/strip with the orchestration from the spec
  (`parse → None passthrough → skip_sentry drop → no-message passthrough →
  replace formatted + attach extra`). Import `StructuredLogPayload` from
  `logging_factory`. Leave `wrap_before_send_callbacks` untouched.

- [ ] **Step 3: Add the back-compat alias.**

  At module level in `sentry_instrument.py`:
  `IGNORED_STRUCTLOG_ATTRIBUTES = STRUCTLOG_META_KEYS  # back-compat alias`
  (import `STRUCTLOG_META_KEYS` from `logging_factory`). Keep a one-line comment
  naming the rename.

  Run `just test` (full suite) → green.

- [ ] **Step 4: Commit.**

  ```bash
  git add lite_bootstrap/instruments/sentry_instrument.py \
          tests/instruments/test_sentry_instrument.py
  git commit -m "refactor: route Sentry enrichment through StructuredLogPayload

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 3: Ship-time docs + index

**Files:**
- Modify: `architecture/instruments.md`
- Modify: `CLAUDE.md`
- Modify: `planning/changes/2026-06-23.01-structured-log-payload/design.md`
  (frontmatter)

Promote the conclusions into the living architecture doc and close out the
bundle.

- [ ] **Step 1: Update `architecture/instruments.md:70-72`.**

  Name the `StructuredLogPayload` seam: the logging instrument emits the rendered
  structlog line; `StructuredLogPayload.parse` (in `logging_factory`) owns the
  meta-key vocabulary (`STRUCTLOG_META_KEYS`) and the skip/extra interpretation;
  the Sentry instrument maps the parsed payload onto the Sentry event.

- [ ] **Step 2: Update `CLAUDE.md:49`.**

  Adjust the Logging↔Sentry bullet to reference `StructuredLogPayload` /
  `STRUCTLOG_META_KEYS` and their `logging_factory` home (replacing the
  `IGNORED_STRUCTLOG_ATTRIBUTES`-in-`sentry_instrument` description).

- [ ] **Step 3: Fill design frontmatter + regenerate index.**

  Set `status: shipped`, fill `summary`, `pr`, `outcome` in `design.md`. Run
  `just index`.

- [ ] **Step 4: Final verification.**

  `just lint-ci` clean (incl. `ty`), `just test` green. Confirm the alias keeps
  `from lite_bootstrap.instruments.sentry_instrument import IGNORED_STRUCTLOG_ATTRIBUTES`
  importable.

- [ ] **Step 5: Commit.**

  ```bash
  git add architecture/instruments.md CLAUDE.md \
          planning/changes/2026-06-23.01-structured-log-payload/ planning/
  git commit -m "docs: record StructuredLogPayload seam in architecture + CLAUDE

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```
