# PR9: OTel Instrument Touch-Ups (REF-1 + LOW-3 + LOW-5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Three small OTel-area cleanups:
- **REF-1**: Hoist the identical `_build_excluded_urls()` method from `FastAPIOpenTelemetryInstrument` and `LitestarOpenTelemetryInstrument` (character-for-character duplicates) to the base `OpenTelemetryInstrument`. Use `getattr` with safe defaults so the method works even when the base instrument runs against a config without the framework-specific fields.
- **LOW-3**: Change `_format_span`'s line terminator from `os.linesep` to literal `"\n"` (OTel SDK convention; `os.linesep` produces `\r\n` on Windows).
- **LOW-5**: Add a one-line comment on `LitestarOpenTelemetryInstrumentationMiddleware._otel_apps` explaining the `id(next_app)` cache assumption.

**Architecture:** Three independent micro-changes, all in OTel-area files. No new tests; existing framework integration tests verify the hoist's behavior preservation.

**Tech Stack:** Python 3.10+, OpenTelemetry SDK.

**Parent spec:** `docs/superpowers/specs/2026-06-01-deferred-refactors-sequencing.md` (PR9 section).
**Parent audit:** `docs/superpowers/specs/2026-05-31-bug-refactor-audit.md` (REF-1, LOW-3, LOW-5).

---

## File Structure

Three files modified.

- Modify: `lite_bootstrap/instruments/opentelemetry_instrument.py` — add `_build_excluded_urls` to the base `OpenTelemetryInstrument`; change `os.linesep` → `"\n"`.
- Modify: `lite_bootstrap/bootstrappers/fastapi_bootstrapper.py` — delete the now-redundant `_build_excluded_urls` override.
- Modify: `lite_bootstrap/bootstrappers/litestar_bootstrapper.py` — delete the now-redundant `_build_excluded_urls` override; add a one-line comment on `_otel_apps`.

---

## Locked decisions (from sequencing spec)

- **REF-1 resolution:** `_build_excluded_urls` becomes a method on the base `OpenTelemetryInstrument` and reads via `getattr` with safe defaults. Framework subclasses no longer override it.
- **No new tests:** The framework integration tests (`test_fastapi_bootstrap`, `test_litestar_bootstrap`) exercise `_build_excluded_urls` via the `OpenTelemetryInstrument.bootstrap()` → instrumentor middleware chain. Hoisting + getattr is a behavior-preserving move.

---

## Task 1: Create branch

**Files:** (no files; git only)

- [ ] **Step 1: Branch off `main`**

```bash
git checkout main
git pull --ff-only origin main
git checkout -b refactor/ref-1-otel-touch-ups
```

Expected: `Switched to a new branch 'refactor/ref-1-otel-touch-ups'`.

---

## Task 2: Apply the three changes, verify, commit

### Step 1: REF-1 — hoist `_build_excluded_urls` to the base

**File:** `lite_bootstrap/instruments/opentelemetry_instrument.py`

Locate the `OpenTelemetryInstrument` class (around lines 77-145 after PR7 + PR3 + PR2 landed). Add the `_build_excluded_urls` method to the class body. The natural place is after `check_dependencies()` and before `bootstrap()`. Insert:

```python
    def _build_excluded_urls(self) -> set[str]:
        excluded_urls: set[str] = set(getattr(self.bootstrap_config, "opentelemetry_excluded_urls", []))
        prometheus_path = getattr(self.bootstrap_config, "prometheus_metrics_path", None)
        if prometheus_path:
            excluded_urls.add(prometheus_path)
        if not self.bootstrap_config.opentelemetry_generate_health_check_spans:
            health_path = getattr(self.bootstrap_config, "health_checks_path", None)
            if health_path:
                excluded_urls.add(health_path)
        return excluded_urls
```

Notes on the `getattr` defaults:
- `opentelemetry_excluded_urls` lives on `FastAPIConfig` and `LitestarConfig` (framework-specific). Default `[]` so the set construction is a no-op when the field is absent.
- `prometheus_metrics_path` lives on `PrometheusConfig` (inherited by FastAPI/Litestar but not by `FreeBootstrapperConfig`). Default `None`; the `if prometheus_path:` guard skips the add when absent.
- `health_checks_path` lives on `HealthChecksConfig` (same inheritance pattern). Default `None`; same guard.
- `opentelemetry_generate_health_check_spans` is on the base `OpentelemetryConfig` (always present); no getattr needed.

This matches the existing FastAPI/Litestar override behavior exactly when the framework fields are present, and produces a safe empty set when they're absent.

### Step 2: Delete `_build_excluded_urls` override from `FastAPIOpenTelemetryInstrument`

**File:** `lite_bootstrap/bootstrappers/fastapi_bootstrapper.py:120-126`

Locate `FastAPIOpenTelemetryInstrument`. The class currently looks like:

```python
@dataclasses.dataclass(kw_only=True, frozen=True)
class FastAPIOpenTelemetryInstrument(OpenTelemetryInstrument):
    bootstrap_config: FastAPIConfig

    def _build_excluded_urls(self) -> set[str]:
        excluded_urls = set(self.bootstrap_config.opentelemetry_excluded_urls)
        excluded_urls.add(self.bootstrap_config.prometheus_metrics_path)
        if not self.bootstrap_config.opentelemetry_generate_health_check_spans:
            excluded_urls.add(self.bootstrap_config.health_checks_path)

        return excluded_urls

    def bootstrap(self) -> None:
        super().bootstrap()
        FastAPIInstrumentor.instrument_app(
            app=self.bootstrap_config.application,
            tracer_provider=get_tracer_provider(),
            excluded_urls=",".join(self._build_excluded_urls()),
        )

    def teardown(self) -> None:
        FastAPIInstrumentor.uninstrument_app(self.bootstrap_config.application)
        super().teardown()
```

Delete the `_build_excluded_urls` method body (lines 120-126 in the original layout — exact line numbers may have shifted after PR7). The class becomes:

```python
@dataclasses.dataclass(kw_only=True, frozen=True)
class FastAPIOpenTelemetryInstrument(OpenTelemetryInstrument):
    bootstrap_config: FastAPIConfig

    def bootstrap(self) -> None:
        super().bootstrap()
        FastAPIInstrumentor.instrument_app(
            app=self.bootstrap_config.application,
            tracer_provider=get_tracer_provider(),
            excluded_urls=",".join(self._build_excluded_urls()),
        )

    def teardown(self) -> None:
        FastAPIInstrumentor.uninstrument_app(self.bootstrap_config.application)
        super().teardown()
```

`self._build_excluded_urls()` now resolves to the inherited base method.

### Step 3: Delete `_build_excluded_urls` override from `LitestarOpenTelemetryInstrument`

**File:** `lite_bootstrap/bootstrappers/litestar_bootstrapper.py:181-187`

Locate `LitestarOpenTelemetryInstrument`. The class currently has:

```python
@dataclasses.dataclass(kw_only=True, frozen=True)
class LitestarOpenTelemetryInstrument(OpenTelemetryInstrument):
    bootstrap_config: LitestarConfig

    def _build_excluded_urls(self) -> set[str]:
        excluded_urls = set(self.bootstrap_config.opentelemetry_excluded_urls)
        excluded_urls.add(self.bootstrap_config.prometheus_metrics_path)
        if not self.bootstrap_config.opentelemetry_generate_health_check_spans:
            excluded_urls.add(self.bootstrap_config.health_checks_path)

        return excluded_urls

    def bootstrap(self) -> None:
        super().bootstrap()
        self.bootstrap_config.application_config.middleware.append(
            LitestarOpenTelemetryInstrumentationMiddleware(
                tracer_provider=get_tracer_provider(),
                excluded_urls=self._build_excluded_urls(),
            )
        )
```

Delete the `_build_excluded_urls` method body. The class becomes:

```python
@dataclasses.dataclass(kw_only=True, frozen=True)
class LitestarOpenTelemetryInstrument(OpenTelemetryInstrument):
    bootstrap_config: LitestarConfig

    def bootstrap(self) -> None:
        super().bootstrap()
        self.bootstrap_config.application_config.middleware.append(
            LitestarOpenTelemetryInstrumentationMiddleware(
                tracer_provider=get_tracer_provider(),
                excluded_urls=self._build_excluded_urls(),
            )
        )
```

### Step 4: LOW-3 — change `os.linesep` to `"\n"`

**File:** `lite_bootstrap/instruments/opentelemetry_instrument.py:25-26`

Current `_format_span`:

```python
def _format_span(readable_span: "ReadableSpan") -> str:
    return typing.cast("str", readable_span.to_json(indent=None)) + os.linesep
```

Replace `os.linesep` with `"\n"`:

```python
def _format_span(readable_span: "ReadableSpan") -> str:
    return typing.cast("str", readable_span.to_json(indent=None)) + "\n"
```

**Important:** Do NOT remove the `import os` at the top of the file. `os.environ.get("HOSTNAME")` is still used in the `opentelemetry_container_name` default_factory.

### Step 5: LOW-5 — add comment on `_otel_apps` cache

**File:** `lite_bootstrap/bootstrappers/litestar_bootstrapper.py`

Locate the `LitestarOpenTelemetryInstrumentationMiddleware.__init__` (around lines 76-79):

```python
class LitestarOpenTelemetryInstrumentationMiddleware(ASGIMiddleware):
    def __init__(self, tracer_provider: "TracerProvider", excluded_urls: set[str]) -> None:
        self._tracer_provider = tracer_provider
        self._excluded_urls = ",".join(excluded_urls)
        self._otel_apps: dict[int, ASGIApp] = {}
```

Add a comment on the `_otel_apps` line:

```python
class LitestarOpenTelemetryInstrumentationMiddleware(ASGIMiddleware):
    def __init__(self, tracer_provider: "TracerProvider", excluded_urls: set[str]) -> None:
        self._tracer_provider = tracer_provider
        self._excluded_urls = ",".join(excluded_urls)
        # Cache keyed by id(next_app); Litestar's ASGI app instances are stable for
        # the middleware lifetime, so id-reuse-after-GC isn't a concern.
        self._otel_apps: dict[int, ASGIApp] = {}
```

### Step 6: Verify with the OTel + framework test files

```bash
just test -- tests/instruments/test_opentelemetry_instrument.py tests/test_fastapi_bootstrap.py tests/test_litestar_bootstrap.py -v
```

Expected: all pass. Particularly watch the FastAPI/Litestar bootstrap tests — they exercise the full bootstrap chain that calls `_build_excluded_urls`.

### Step 7: Run the full test suite

```bash
just test
```

Expected: 89/89 PASS. No behavior change.

### Step 8: Run lint

```bash
just lint
```

Expected: clean. Watch for:
- F401 unused import warnings if `os` somehow appears unused (it shouldn't — verify).
- Any ruff complaint about the new base-class method.

### Step 9: Commit

Stage exactly the three modified files:

```bash
git add \
  lite_bootstrap/instruments/opentelemetry_instrument.py \
  lite_bootstrap/bootstrappers/fastapi_bootstrapper.py \
  lite_bootstrap/bootstrappers/litestar_bootstrapper.py
git commit -m "$(cat <<'EOF'
refactor: OTel instrument touch-ups (REF-1, LOW-3, LOW-5)

REF-1: _build_excluded_urls() was character-for-character identical in
FastAPIOpenTelemetryInstrument and LitestarOpenTelemetryInstrument.
Hoist to the base OpenTelemetryInstrument and use getattr with safe
defaults so the method works when the base instrument runs against a
config without the framework-specific fields (opentelemetry_excluded_urls,
prometheus_metrics_path, health_checks_path).

LOW-3: _format_span used os.linesep, which produces \r\n on Windows.
The OTel SDK convention is plain \n; change to a literal.

LOW-5: Add a one-line comment on
LitestarOpenTelemetryInstrumentationMiddleware._otel_apps documenting
the id(next_app) cache assumption (ASGI app instances are stable for
the middleware lifetime).

No behavior change.

Closes REF-1, LOW-3, LOW-5 from the audit.
EOF
)"
```

---

## Task 3: Push and open PR

- [ ] **Step 1: Push the branch**

```bash
git push -u origin refactor/ref-1-otel-touch-ups
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --title "refactor: OTel instrument touch-ups (REF-1, LOW-3, LOW-5)" --body "$(cat <<'EOF'
## Summary
Three small OTel-area cleanups:

- **REF-1:** \`_build_excluded_urls()\` was character-for-character identical in \`FastAPIOpenTelemetryInstrument\` and \`LitestarOpenTelemetryInstrument\`. Hoist to the base \`OpenTelemetryInstrument\` and use \`getattr\` with safe defaults so the method works when the base instrument runs against a config without the framework-specific fields (\`opentelemetry_excluded_urls\`, \`prometheus_metrics_path\`, \`health_checks_path\`).
- **LOW-3:** \`_format_span\` used \`os.linesep\` (produces \`\\r\\n\` on Windows). OTel SDK convention is plain \`\\n\`; switched to a literal.
- **LOW-5:** Added a one-line comment on \`LitestarOpenTelemetryInstrumentationMiddleware._otel_apps\` documenting the \`id(next_app)\` cache assumption.

No behavior change. No new tests — existing framework integration tests verify the hoist's behavior preservation.

Closes REF-1, LOW-3, LOW-5 from an internal audit.

## Test plan
- [x] \`just test -- tests/instruments/test_opentelemetry_instrument.py tests/test_fastapi_bootstrap.py tests/test_litestar_bootstrap.py -v\` — pass.
- [x] \`just test\` — 89/89.
- [x] \`just lint\` — clean.
- [ ] Reviewer: confirm the \`getattr\` defaults in the hoisted \`_build_excluded_urls\` match the pre-hoist behavior for FastAPI/Litestar (\`opentelemetry_excluded_urls\` default \`[]\`, paths default \`None\` with truthy guard).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review

**Spec coverage check** against the sequencing spec (PR9 section) and audit (REF-1, LOW-3, LOW-5):

| Spec item | Task |
|-----------|------|
| Hoist `_build_excluded_urls` to base with getattr defaults | Task 2, Step 1 |
| Delete `_build_excluded_urls` override from FastAPI | Task 2, Step 2 |
| Delete `_build_excluded_urls` override from Litestar | Task 2, Step 3 |
| `_format_span` newline change | Task 2, Step 4 |
| `_otel_apps` id() cache comment | Task 2, Step 5 |
| Branch name `refactor/ref-1-otel-touch-ups` | Task 1, Step 1 |
| Verification: `just test` + `just lint` clean | Task 2, Steps 6-8 |

All spec items covered. No placeholders. The hoisted `_build_excluded_urls`'s `getattr` defaults match the pre-hoist behavior:

- `opentelemetry_excluded_urls` default `[]` → `set([])` → empty set (same as the original `set(...)` over the empty list when the field has a default).
- `prometheus_metrics_path` truthy check ensures `None` is not added; `set.add(None)` would be a real bug.
- `health_checks_path` same truthy check.
