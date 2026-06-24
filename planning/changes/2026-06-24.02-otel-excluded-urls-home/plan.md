---
status: shipped
date: 2026-06-24
slug: otel-excluded-urls-home
spec: otel-excluded-urls-home
pr: 132
---

# otel-excluded-urls-home — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps
> use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move `opentelemetry_excluded_urls` onto `OpenTelemetryConfig` (typed
access, one declaration), and pin the genuine cross-instrument exclusion reads
(`prometheus_metrics_path` / `health_checks_path`) with a regression test.

**Spec:** [`design.md`](./design.md)

**Branch:** `feat/otel-excluded-urls-home`

**Commit strategy:** Per-task commits (each task leaves the suite green).

---

### Task 1: Pin the genuine-sibling exclusions (B) — regression net first

**Files:**
- Modify: `tests/test_faststream_bootstrap.py`

Lock the cross-config exclusion behaviour that is currently untested, before
touching any config. This test passes against the current code (it characterises
existing behaviour) and guards the policy thereafter.

- [ ] **Step 1: Add the cross-config exclusion test.**

  Beside `test_faststream_opentelemetry_excluded_urls_in_built_set`
  (`test_faststream_bootstrap.py:225`), add a test that builds a config composing
  Prometheus + HealthChecks (via `build_faststream_config` + `dataclasses.replace`),
  constructs `FastStreamOpenTelemetryInstrument`, and asserts on `_build_excluded_urls()`:
  - prometheus metrics path is always in the set;
  - health-checks path is in the set when `opentelemetry_generate_health_check_spans=False`;
  - health-checks path is **not** in the set when it is `True`.

  Run `just test -- -k excluded` → green (behaviour already exists).

- [ ] **Step 2: Commit.**

  ```bash
  git add tests/test_faststream_bootstrap.py
  git commit -m "test: pin OTel cross-config metrics/health URL exclusion

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 2: Move `opentelemetry_excluded_urls` onto `OpenTelemetryConfig` (A)

**Files:**
- Modify: `lite_bootstrap/instruments/opentelemetry_instrument.py`
- Modify: `lite_bootstrap/bootstrappers/fastapi_bootstrapper.py`
- Modify: `lite_bootstrap/bootstrappers/litestar_bootstrapper.py`
- Modify: `lite_bootstrap/bootstrappers/faststream_bootstrapper.py`

Field goes home; the read becomes typed. Guarded by the existing passthrough test
(`test_faststream_opentelemetry_excluded_urls_in_built_set`) and Task 1's net.

- [ ] **Step 1: Add the field to `OpenTelemetryConfig`.**

  `opentelemetry_excluded_urls: list[str] = dataclasses.field(default_factory=list)`
  on `OpenTelemetryConfig` (the main config, alongside the other `opentelemetry_*`
  fields).

- [ ] **Step 2: Remove the three framework-config declarations.**

  Delete the `opentelemetry_excluded_urls` line from `FastAPIConfig` (`:53`),
  `LitestarConfig` (`:120`), `FastStreamConfig` (`:69`). They now inherit it.

- [ ] **Step 3: Make the read typed.**

  In `_build_excluded_urls`, replace
  `set(getattr(self.bootstrap_config, "opentelemetry_excluded_urls", []))` with
  `set(self.bootstrap_config.opentelemetry_excluded_urls)`. Leave the
  `prometheus_metrics_path` / `health_checks_path` getattrs unchanged.

  Run `just test` (full suite) → green. Confirm
  `test_faststream_opentelemetry_excluded_urls_in_built_set` and Task 1's test pass.

- [ ] **Step 4: Commit.**

  ```bash
  git add lite_bootstrap/instruments/opentelemetry_instrument.py \
          lite_bootstrap/bootstrappers/fastapi_bootstrapper.py \
          lite_bootstrap/bootstrappers/litestar_bootstrapper.py \
          lite_bootstrap/bootstrappers/faststream_bootstrapper.py
  git commit -m "refactor: move opentelemetry_excluded_urls onto OpenTelemetryConfig

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```

---

### Task 3: Docs + frontmatter + index

**Files:**
- Modify: `docs/introduction/configuration.md`
- Modify: `planning/changes/2026-06-24.02-otel-excluded-urls-home/design.md` (frontmatter)

- [ ] **Step 1: Update `docs/introduction/configuration.md`.**

  Read the `opentelemetry_excluded_urls` reference; if it is documented under a
  framework-specific section, move/note it as an `OpenTelemetryConfig` field (it now
  applies wherever OTel is configured). Keep it minimal — usage is unchanged.

- [ ] **Step 2: Fill design frontmatter + regenerate index.**

  Set `summary`; set `status` per merge state (candidate-1/2 precedent: `approved`
  until a PR exists, `shipped` + `pr` at PR time). Run `just index`.

- [ ] **Step 3: Final verification.**

  `just lint-ci` clean (incl. `ty`), `just test` green at 100%. Spot-check:
  `FreeConfig(opentelemetry_excluded_urls=["/x"])` constructs without error (field
  now inherited).

- [ ] **Step 4: Commit.**

  ```bash
  git add docs/introduction/configuration.md \
          planning/changes/2026-06-24.02-otel-excluded-urls-home/ planning/
  git commit -m "docs: note opentelemetry_excluded_urls moved to OpenTelemetryConfig

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  ```
