# 01.03-deferred-refactors — implementation plan

> Multi-PR plan: this change shipped as a sequence of PRs. Each section below was an independent per-PR plan; they are preserved verbatim here as the bundle's single `plan.md` (the spec is [`design.md`](./design.md)).


---

# PR8: Sentry Micro-Fixes (LOW-1 + LOW-2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two small idiom/typing fixes in `sentry_instrument.py`:
- LOW-1: Replace `if not callback:` (sloppy callable truthiness check) with `if callback is None:` in `wrap_before_send_callbacks`.
- LOW-2: Replace `SentryConfig.sentry_before_send`'s degenerate `Callable[[Any, Any], Any | None] | None` annotation with the proper `sentry_types.EventProcessor | None`.

Both are tiny; no behavior change.

**Architecture:** Single-file edit. Two unrelated micro-fixes bundled because both touch the same module and reviewing them separately would cost more than reviewing them together.

**Tech Stack:** Python 3.10+, sentry_sdk types (`sentry_sdk._types.EventProcessor`).

**Parent spec:** `docs/superpowers/specs/2026-06-01-deferred-refactors-sequencing.md` (PR8 section).
**Parent audit:** `docs/superpowers/specs/2026-05-31-bug-refactor-audit.md` (LOW-1, LOW-2).

---

## File Structure

One file modified.

- Modify: `lite_bootstrap/instruments/sentry_instrument.py` — two changes (lines 36 and 81-82).

---

## Locked decisions

- **No new tests.** Existing Sentry tests (`tests/instruments/test_sentry_instrument.py`) cover the affected code paths. LOW-1 is an idiom change with identical runtime behavior for the only realistic input (callables and `None`); LOW-2 is type-only.

---

## Task 1: Create branch

**Files:** (no files; git only)

- [ ] **Step 1: Branch off `main`**

```bash
git checkout main
git pull --ff-only origin main
git checkout -b fix/low-1-2-sentry-micro
```

Expected: `Switched to a new branch 'fix/low-1-2-sentry-micro'`.

---

## Task 2: Apply two micro-fixes, verify, commit

### Step 1: Fix LOW-2 (`sentry_before_send` typing)

**File:** `lite_bootstrap/instruments/sentry_instrument.py:36`

Current line:

```python
    sentry_before_send: typing.Callable[[typing.Any, typing.Any], typing.Any | None] | None = None
```

This annotation is degenerate: `typing.Any | None` collapses to `typing.Any` (since `Any` is the top type for type-checking purposes), so the outer `| None` is the only meaningful nullability. Functionally the annotation reduces to `Callable[..., Any] | None`.

The file already imports the proper type under `TYPE_CHECKING` at lines 10-12:

```python
if typing.TYPE_CHECKING:
    from sentry_sdk import _types as sentry_types
    from sentry_sdk.integrations import Integration
```

And `wrap_before_send_callbacks` (later in the same file) already uses `"sentry_types.EventProcessor"` in its own signature:

```python
def wrap_before_send_callbacks(
    *callbacks: typing.Optional["sentry_types.EventProcessor"],
) -> "sentry_types.EventProcessor":
```

So `sentry_types.EventProcessor` is already in scope. Replace line 36 with:

```python
    sentry_before_send: "sentry_types.EventProcessor | None" = None
```

The string annotation form avoids a `NameError` at runtime when `sentry_sdk` isn't installed (since `sentry_types` lives under the `TYPE_CHECKING` block).

### Step 2: Fix LOW-1 (`if not callback:` → `if callback is None:`)

**File:** `lite_bootstrap/instruments/sentry_instrument.py:80-82`

Current code:

```python
    def run_before_send(
        event: "sentry_types.Event", hint: "sentry_types.Hint"
    ) -> typing.Optional["sentry_types.Event"]:
        for callback in callbacks:
            if not callback:
                continue

            temp_event = callback(event, hint)
            ...
```

The `if not callback:` is checking truthiness, but Python callables are always truthy unless they define a custom `__bool__`. The intent is clearly "skip None entries." Replace `if not callback:` with `if callback is None:` to match the intent:

```python
    def run_before_send(
        event: "sentry_types.Event", hint: "sentry_types.Hint"
    ) -> typing.Optional["sentry_types.Event"]:
        for callback in callbacks:
            if callback is None:
                continue

            temp_event = callback(event, hint)
            ...
```

Only the conditional changes; the rest of the function is unchanged.

### Step 3: Run the Sentry test file

```bash
just test -- tests/instruments/test_sentry_instrument.py -v
```

Expected: all tests PASS. The existing tests cover both `enrich_sentry_event_from_structlog_log` (which goes through `wrap_before_send_callbacks`) and the `SentryInstrument.bootstrap()` path that uses `sentry_before_send`.

### Step 4: Run the full test suite

```bash
just test
```

Expected: 89/89 (or whatever the current count is after PR7 — should be 89). No behavior change should affect any test.

### Step 5: Run lint

```bash
just lint
```

Expected: clean. The `# ty: ignore` removal opportunity (if the original line had one — check during implementation) should also clear without warnings.

### Step 6: Commit

Stage the single modified file:

```bash
git add lite_bootstrap/instruments/sentry_instrument.py
git commit -m "$(cat <<'EOF'
fix: tighten Sentry idiom and typing micro-issues

LOW-1: wrap_before_send_callbacks used `if not callback:` to skip None
entries in *callbacks. Callables are always truthy unless they define
__bool__, so the truthiness check is semantically wrong even if it
happens to work. Use `if callback is None:` to match the intent.

LOW-2: SentryConfig.sentry_before_send was annotated
`Callable[[Any, Any], Any | None] | None`. The inner `Any | None`
collapses to `Any`, so the annotation reduces to
`Callable[..., Any] | None` — the union adds nothing. Use the proper
`sentry_types.EventProcessor | None` instead (already imported under
TYPE_CHECKING in the same file).

No behavior change.

Closes LOW-1 and LOW-2 from the audit.
EOF
)"
```

---

## Task 3: Push and open PR

- [ ] **Step 1: Push the branch**

```bash
git push -u origin fix/low-1-2-sentry-micro
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --title "fix: tighten Sentry idiom and typing micro-issues" --body "$(cat <<'EOF'
## Summary
Two micro-fixes in \`sentry_instrument.py\`:

- **LOW-1:** \`wrap_before_send_callbacks\` used \`if not callback:\` to skip \`None\` entries. Callables are always truthy unless they define \`__bool__\`, so the truthiness check is semantically wrong (happens to work, but obscures the intent). Use \`if callback is None:\` instead.
- **LOW-2:** \`SentryConfig.sentry_before_send\` was annotated \`Callable[[Any, Any], Any | None] | None\`. The inner \`Any | None\` collapses to \`Any\`, so the annotation reduces to \`Callable[..., Any] | None\` — the union adds nothing. Use the proper \`sentry_types.EventProcessor | None\` (already imported under \`TYPE_CHECKING\` in the same file).

No behavior change. No new tests — existing Sentry tests cover both paths.

Closes LOW-1 and LOW-2 from an internal audit.

## Test plan
- [x] \`just test -- tests/instruments/test_sentry_instrument.py -v\` — pass.
- [x] \`just test\` — full suite passes.
- [x] \`just lint\` — clean.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review

**Spec coverage check** against the sequencing spec (PR8 section) and audit (LOW-1, LOW-2):

| Spec item | Task |
|-----------|------|
| LOW-1: `if not callback:` → `if callback is None:` | Task 2, Step 2 |
| LOW-2: `sentry_before_send` typing → `sentry_types.EventProcessor \| None` | Task 2, Step 1 |
| Branch name `fix/low-1-2-sentry-micro` | Task 1, Step 1 |
| Verification: `just test` + `just lint` clean | Task 2, Steps 3-5 |
| Single-file diff | Task 2, Step 6 |

All spec items covered. No placeholders. Smallest PR in the deferred-refactors sequence; both edits are pre-existing patterns already used elsewhere in the same file (string-quoted forward reference for the type; explicit `is None` checks in other modules).


---

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


---

# PR10: Test Gap Fill (TEST-4 + TEST-7)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add standalone test files for the four instruments that today are only covered transitively via bootstrapper integration tests (`CorsInstrument`, `HealthChecksInstrument`, `PrometheusInstrument`, `SwaggerInstrument`) and add negative tests for `helpers.path.is_valid_path`. Pure additions; zero production code changes.

**Architecture:** 5 new test files, no production changes.

**Tech Stack:** Python 3.10+, pytest, parametrized tests.

**Parent spec:** `docs/superpowers/specs/2026-06-01-deferred-refactors-sequencing.md` (PR10 section).
**Parent audit:** `docs/superpowers/specs/2026-05-31-bug-refactor-audit.md` (TEST-4, TEST-7).

---

## File Structure

5 new test files. No existing files modified.

- Create: `tests/instruments/test_cors_instrument.py`
- Create: `tests/instruments/test_healthchecks_instrument.py`
- Create: `tests/instruments/test_prometheus_instrument.py`
- Create: `tests/instruments/test_swagger_instrument.py`
- Create: `tests/test_path.py`

---

## Locked decisions

- **Pure additions:** No production code changes. The existing transitive coverage via bootstrapper integration tests is fine; standalone tests just localize regression diagnosis.
- **Test style:** Match the existing simple-function test style in `tests/instruments/test_pyroscope_instrument.py` and `test_opentelemetry_instrument.py` (no fixtures, no shared setup, one function per behavior).

---

## Task 1: Create branch

**Files:** (no files; git only)

- [ ] **Step 1: Branch off `main`**

```bash
git checkout main
git pull --ff-only origin main
git checkout -b fix/test-4-7-gaps
```

Expected: `Switched to a new branch 'fix/test-4-7-gaps'`.

---

## Task 2: Create the five test files, verify, commit

### Step 1: Create `tests/instruments/test_cors_instrument.py`

```python
from lite_bootstrap.instruments.cors_instrument import CorsConfig, CorsInstrument


def test_cors_instrument_not_ready_without_origins_or_regex() -> None:
    instrument = CorsInstrument(bootstrap_config=CorsConfig())
    assert not instrument.is_ready()
    assert instrument.not_ready_message == "cors_allowed_origins or cors_allowed_origin_regex must be provided"


def test_cors_instrument_ready_with_origins() -> None:
    instrument = CorsInstrument(bootstrap_config=CorsConfig(cors_allowed_origins=["http://test"]))
    assert instrument.is_ready()


def test_cors_instrument_ready_with_regex() -> None:
    instrument = CorsInstrument(bootstrap_config=CorsConfig(cors_allowed_origin_regex=r"https?://.*"))
    assert instrument.is_ready()


def test_cors_instrument_ready_with_both() -> None:
    instrument = CorsInstrument(
        bootstrap_config=CorsConfig(
            cors_allowed_origins=["http://test"],
            cors_allowed_origin_regex=r"https?://.*",
        ),
    )
    assert instrument.is_ready()


def test_cors_instrument_config_defaults() -> None:
    config = CorsConfig()
    assert config.cors_allowed_origins == []
    assert config.cors_allowed_methods == []
    assert config.cors_allowed_headers == []
    assert config.cors_exposed_headers == []
    assert config.cors_allowed_credentials is False
    assert config.cors_allowed_origin_regex is None
    assert config.cors_max_age == 600


def test_cors_check_dependencies() -> None:
    assert CorsInstrument.check_dependencies() is True
```

### Step 2: Create `tests/instruments/test_healthchecks_instrument.py`

```python
from lite_bootstrap.instruments.healthchecks_instrument import HealthChecksConfig, HealthChecksInstrument


def test_healthchecks_instrument_ready_by_default() -> None:
    instrument = HealthChecksInstrument(bootstrap_config=HealthChecksConfig())
    assert instrument.is_ready()


def test_healthchecks_instrument_not_ready_when_disabled() -> None:
    instrument = HealthChecksInstrument(bootstrap_config=HealthChecksConfig(health_checks_enabled=False))
    assert not instrument.is_ready()
    assert instrument.not_ready_message == "health_checks_enabled is False"


def test_healthchecks_render_data_default() -> None:
    instrument = HealthChecksInstrument(bootstrap_config=HealthChecksConfig())
    data = instrument.render_health_check_data()
    assert data == {
        "service_version": "1.0.0",
        "service_name": "micro-service",
        "health_status": True,
    }


def test_healthchecks_render_data_custom() -> None:
    instrument = HealthChecksInstrument(
        bootstrap_config=HealthChecksConfig(service_name="my-svc", service_version="2.0.0"),
    )
    data = instrument.render_health_check_data()
    assert data == {
        "service_version": "2.0.0",
        "service_name": "my-svc",
        "health_status": True,
    }


def test_healthchecks_config_defaults() -> None:
    config = HealthChecksConfig()
    assert config.health_checks_enabled is True
    assert config.health_checks_path == "/health/"
    assert config.health_checks_include_in_schema is False


def test_healthchecks_check_dependencies() -> None:
    assert HealthChecksInstrument.check_dependencies() is True
```

### Step 3: Create `tests/instruments/test_prometheus_instrument.py`

```python
from lite_bootstrap.instruments.prometheus_instrument import PrometheusConfig, PrometheusInstrument


def test_prometheus_instrument_ready_with_default_path() -> None:
    instrument = PrometheusInstrument(bootstrap_config=PrometheusConfig())
    assert instrument.is_ready()


def test_prometheus_instrument_not_ready_with_empty_path() -> None:
    instrument = PrometheusInstrument(bootstrap_config=PrometheusConfig(prometheus_metrics_path=""))
    assert not instrument.is_ready()
    assert instrument.not_ready_message == "prometheus_metrics_path is empty or not valid"


def test_prometheus_instrument_not_ready_with_invalid_path() -> None:
    # No leading slash → invalid per is_valid_path regex.
    instrument = PrometheusInstrument(bootstrap_config=PrometheusConfig(prometheus_metrics_path="metrics"))
    assert not instrument.is_ready()


def test_prometheus_instrument_ready_with_custom_valid_path() -> None:
    instrument = PrometheusInstrument(
        bootstrap_config=PrometheusConfig(prometheus_metrics_path="/custom-metrics/"),
    )
    assert instrument.is_ready()


def test_prometheus_config_defaults() -> None:
    config = PrometheusConfig()
    assert config.prometheus_metrics_path == "/metrics"
    assert config.prometheus_metrics_include_in_schema is False


def test_prometheus_check_dependencies() -> None:
    assert PrometheusInstrument.check_dependencies() is True
```

### Step 4: Create `tests/instruments/test_swagger_instrument.py`

```python
from lite_bootstrap.instruments.swagger_instrument import SwaggerConfig, SwaggerInstrument


def test_swagger_instrument_ready_by_default() -> None:
    instrument = SwaggerInstrument(bootstrap_config=SwaggerConfig())
    assert instrument.is_ready()


def test_swagger_config_defaults() -> None:
    config = SwaggerConfig()
    assert config.swagger_static_path == "/static"
    assert config.swagger_path == "/docs"
    assert config.swagger_offline_docs is False


def test_swagger_check_dependencies() -> None:
    assert SwaggerInstrument.check_dependencies() is True
```

### Step 5: Create `tests/test_path.py`

```python
import pytest

from lite_bootstrap.helpers.path import is_valid_path


@pytest.mark.parametrize(
    "path",
    [
        "/metrics",
        "/health/",
        "/api/v1/users",
        "/foo.bar",
        "/foo_bar",
        "/foo-bar",
        "/a",
        "/a/",
    ],
)
def test_is_valid_path_accepts_valid(path: str) -> None:
    assert is_valid_path(path) is True


@pytest.mark.parametrize(
    "path",
    [
        "",
        "foo",
        "foo/",
        "/foo bar",
        "/foo?bar",
        "/foo#bar",
        "/",
        "//foo",
        "/foo//bar",
    ],
)
def test_is_valid_path_rejects_invalid(path: str) -> None:
    assert is_valid_path(path) is False
```

Notes on the rejected cases:
- `""` — empty string fails the `^(/...)+/?$` pattern.
- `"foo"`, `"foo/"` — no leading `/`.
- `"/foo bar"` — space is not in `[a-zA-Z0-9._-]`.
- `"/foo?bar"`, `"/foo#bar"` — `?` and `#` are not in the charset.
- `"/"` — no segment after the slash; the regex requires `[a-zA-Z0-9._-]+`.
- `"//foo"`, `"/foo//bar"` — empty segments not allowed by the `+` quantifier.

The regex DOES accept `/..` and `/../foo` because `.` is in the charset; the `is_valid_path` function does not block path traversal. That's a pre-existing design decision (out of scope here).

### Step 6: Run the new test files

```bash
just test -- tests/instruments/test_cors_instrument.py tests/instruments/test_healthchecks_instrument.py tests/instruments/test_prometheus_instrument.py tests/instruments/test_swagger_instrument.py tests/test_path.py -v
```

Expected: all new tests PASS on first run. They're pure additions verifying current behavior.

If any test fails, investigate before continuing. The most likely cause is a wrong assertion (e.g., default value), not a real bug.

### Step 7: Run the full test suite

```bash
just test
```

Expected: total count goes from 89 to roughly 89 + (6+6+6+3+17) = ~127. All pass.

Approximate breakdown of new tests:
- `test_cors_instrument.py`: 6 tests
- `test_healthchecks_instrument.py`: 6 tests
- `test_prometheus_instrument.py`: 6 tests
- `test_swagger_instrument.py`: 3 tests
- `test_path.py`: 17 parametrized cases across 2 functions

### Step 8: Run lint

```bash
just lint
```

Expected: clean. No production changes mean no lint-rule complications.

### Step 9: Commit

Stage exactly the five new files:

```bash
git add \
  tests/instruments/test_cors_instrument.py \
  tests/instruments/test_healthchecks_instrument.py \
  tests/instruments/test_prometheus_instrument.py \
  tests/instruments/test_swagger_instrument.py \
  tests/test_path.py
git commit -m "$(cat <<'EOF'
test: add standalone instrument tests and is_valid_path negative tests

TEST-4: Add tests/instruments/test_{cors,healthchecks,prometheus,swagger}_instrument.py
covering is_ready() across valid/invalid configurations,
not_ready_message content, render_health_check_data output shape,
config defaults, and check_dependencies. These instruments were
previously only covered transitively via bootstrapper integration
tests, which made regressions noisier to diagnose.

TEST-7: Add tests/test_path.py with parametrized cases for
helpers.path.is_valid_path — both valid forms (default paths used by
the prometheus/swagger/healthchecks instruments) and invalid forms
(empty, no leading slash, spaces, special chars, empty segments).

Closes TEST-4 and TEST-7 from the audit. Pure additions; no production
code changed.
EOF
)"
```

---

## Task 3: Push and open PR

- [ ] **Step 1: Push the branch**

```bash
git push -u origin fix/test-4-7-gaps
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --title "test: add standalone instrument tests and is_valid_path negative tests" --body "$(cat <<'EOF'
## Summary
Pure test additions; no production changes.

- **TEST-4:** Standalone test files for the four instruments previously only covered transitively via bootstrapper integration tests:
  - \`tests/instruments/test_cors_instrument.py\` — \`is_ready\` matrix (origins-only, regex-only, both, neither), \`not_ready_message\`, config defaults, \`check_dependencies\`.
  - \`tests/instruments/test_healthchecks_instrument.py\` — enabled/disabled, \`render_health_check_data\` output shape, defaults.
  - \`tests/instruments/test_prometheus_instrument.py\` — valid/invalid/empty paths, defaults.
  - \`tests/instruments/test_swagger_instrument.py\` — instantiation, defaults.
- **TEST-7:** \`tests/test_path.py\` — parametrized cases for \`is_valid_path\` covering valid forms (\`/metrics\`, \`/health/\`, multi-segment, special chars in the allowed set) and invalid forms (empty, no leading slash, spaces, \`?\`/\`#\`, empty segments).

Closes TEST-4 and TEST-7 from an internal audit.

## Test plan
- [x] \`just test\` — full suite passes (89 prior + ~37 new ≈ 126).
- [x] \`just lint\` — clean.
- [ ] Reviewer: confirm the rejected-path list in \`test_path.py\` matches the intended contract. (The regex DOES accept \`/..\` because \`.\` is in the allowed charset — pre-existing design decision; not tested as a "valid" or "invalid" case.)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review

**Spec coverage check** against the sequencing spec (PR10 section) and audit (TEST-4, TEST-7):

| Spec item | Task |
|-----------|------|
| `tests/instruments/test_cors_instrument.py` | Task 2, Step 1 |
| `tests/instruments/test_healthchecks_instrument.py` | Task 2, Step 2 |
| `tests/instruments/test_prometheus_instrument.py` | Task 2, Step 3 |
| `tests/instruments/test_swagger_instrument.py` | Task 2, Step 4 |
| `tests/test_path.py` with negative cases | Task 2, Step 5 |
| Branch name `fix/test-4-7-gaps` | Task 1, Step 1 |
| Verification: `just test` + `just lint` clean | Task 2, Steps 6-8 |

All spec items covered. No placeholders. Test code matches the existing simple-function style in the codebase. The Prometheus test uses both the default `/metrics` path (valid) and `"metrics"` (invalid — no leading slash) to exercise both branches of `is_valid_path`'s logic without depending on `tests/test_path.py`.


---

# PR11: Logging Cleanup + Lifecycle Test (REF-4 + REF-2 + LOW-6 + LOW-8 + LOW-9 + TEST-8)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The biggest PR of the deferred-refactors sequence. Bundles six logging-area items:
- **REF-4**: Split `logging_instrument.py` (212 lines) into a new `logging_factory.py` (factory + serializer + protocols) plus a slimmer `logging_instrument.py` (config + instrument + tracer injection).
- **REF-2**: Delete the dead `if import_checker.is_structlog_installed and import_checker.is_litestar_installed:` defensive check in `LitestarLoggingInstrument.bootstrap()`.
- **LOW-6**: Wrap `MemoryLoggerFactory`'s 4 logging-config kwargs into an internal `_MemoryLoggerFactoryConfig` dataclass.
- **LOW-8**: Add a docstring to `LoggingInstrument._unset_handlers` documenting that the mutation is permanent.
- **LOW-9**: Add a docstring to `LoggingInstrument.teardown()` documenting that root logger level is unconditionally reset to WARNING.
- **TEST-8**: Add a bootstrap→teardown→bootstrap→teardown lifecycle replay test.

**Architecture:** One new module file, one production refactor (the split), one cross-file dead-code removal, two docstring additions, one test update, one new test. Backward compatibility is preserved by re-exporting moved symbols from `logging_instrument.py`.

**Tech Stack:** Python 3.10+ dataclasses, structlog, pytest.

**Parent spec:** `docs/superpowers/specs/2026-06-01-deferred-refactors-sequencing.md` (PR11 section).
**Parent audit:** `docs/superpowers/specs/2026-05-31-bug-refactor-audit.md` (REF-2, REF-4, LOW-6, LOW-8, LOW-9, TEST-8).

---

## File Structure

5 files touched.

- Create: `lite_bootstrap/instruments/logging_factory.py` — `MemoryLoggerFactory`, `_MemoryLoggerFactoryConfig`, `_serialize_log_with_orjson_to_string`, `AddressProtocol`, `RequestProtocol`, `ScopeType`.
- Modify: `lite_bootstrap/instruments/logging_instrument.py` — slim to `LoggingConfig`, `LoggingInstrument`, `tracer_injection`; re-import the moved symbols for backward compat; add LOW-8 / LOW-9 docstrings.
- Modify: `lite_bootstrap/bootstrappers/litestar_bootstrapper.py` — REF-2: delete the dead defensive check, unindent the body.
- Modify: `tests/instruments/test_logging_instrument.py` — update `MemoryLoggerFactory` instantiations to use `_MemoryLoggerFactoryConfig`; add `test_logging_instrument_lifecycle_replay`.

---

## Locked decisions (from sequencing spec)

- **Internal config dataclass for `MemoryLoggerFactory`:** Prefix `_MemoryLoggerFactoryConfig` (underscore = internal). Not exported from `__init__.py`. Tests import it via the underscore-prefixed name.
- **Backward compat for moved symbols:** `MemoryLoggerFactory`, `AddressProtocol`, `RequestProtocol`, `ScopeType` are re-imported into `logging_instrument.py` so existing `from lite_bootstrap.instruments.logging_instrument import MemoryLoggerFactory` imports continue to work.
- **No PLR2004 noqa for magic-value test assertions.** If ruff complains about a numeric literal in a test assertion (e.g., `assert config.x == 10`), extract the value to a named local variable. See PR10's `expected_max_age = 600` pattern.

---

## Task 1: Create branch

**Files:** (no files; git only)

- [ ] **Step 1: Branch off `main`**

```bash
git checkout main
git pull --ff-only origin main
git checkout -b refactor/ref-4-logging-cleanup
```

Expected: `Switched to a new branch 'refactor/ref-4-logging-cleanup'`.

---

## Task 2: Apply all six changes, verify, commit

The order of steps below is important — start with the file split (steps 1-3), then dead code removal (step 4), then docstrings (step 5), then test updates (steps 6-7), then verify.

### Step 1: Create `lite_bootstrap/instruments/logging_factory.py`

New file with full contents:

```python
import dataclasses
import logging
import logging.handlers
import sys
import typing

import orjson

from lite_bootstrap import import_checker


ScopeType = typing.MutableMapping[str, typing.Any]


class AddressProtocol(typing.Protocol):
    host: str
    port: int


class RequestProtocol(typing.Protocol):
    client: AddressProtocol
    scope: ScopeType
    method: str


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class _MemoryLoggerFactoryConfig:
    logging_buffer_capacity: int
    logging_flush_level: int
    logging_log_level: int
    log_stream: typing.Any = sys.stdout  # noqa: ANN401


def _serialize_log_with_orjson_to_string(value: typing.Any, **kwargs: typing.Any) -> str:  # noqa: ANN401
    return orjson.dumps(value, **kwargs).decode()


if import_checker.is_structlog_installed:
    import structlog

    class MemoryLoggerFactory(structlog.stdlib.LoggerFactory):
        def __init__(
            self,
            *args: typing.Any,  # noqa: ANN401
            config: "_MemoryLoggerFactoryConfig",
            **kwargs: typing.Any,  # noqa: ANN401
        ) -> None:
            super().__init__(*args, **kwargs)
            self.config = config
            self._created_handlers: list[tuple[logging.Logger, logging.handlers.MemoryHandler]] = []

        def __call__(self, *args: typing.Any) -> logging.Logger:  # noqa: ANN401
            logger: typing.Final = super().__call__(*args)
            stream_handler: typing.Final = logging.StreamHandler(stream=self.config.log_stream)
            handler: typing.Final = logging.handlers.MemoryHandler(
                capacity=self.config.logging_buffer_capacity,
                flushLevel=self.config.logging_flush_level,
                target=stream_handler,
            )
            logger.addHandler(handler)
            logger.setLevel(self.config.logging_log_level)
            logger.propagate = False
            self._created_handlers.append((logger, handler))
            return logger

        def close_handlers(self) -> None:
            for created_logger, handler in self._created_handlers:
                created_logger.removeHandler(handler)
                created_logger.propagate = True
                target = handler.target
                handler.close()
                if target is not None:
                    target.close()
            self._created_handlers.clear()
```

Notes on the structlog gate:
- `MemoryLoggerFactory` MUST be inside the gate because it inherits from `structlog.stdlib.LoggerFactory`.
- `_MemoryLoggerFactoryConfig` and `_serialize_log_with_orjson_to_string` are OUTSIDE the gate — they have no structlog dependency (just stdlib + orjson, both unconditional). This matters because `logging_instrument.py` imports them at module top; if they were gated, the import would fail when structlog isn't installed.
- `ScopeType`, `AddressProtocol`, `RequestProtocol` are unconditional (no structlog dependency).

### Step 2: Rewrite `lite_bootstrap/instruments/logging_instrument.py`

Replace the full file contents with:

```python
import dataclasses
import logging
import logging.handlers
import sys
import typing

from lite_bootstrap import import_checker
from lite_bootstrap.instruments.base import BaseConfig, BaseInstrument
from lite_bootstrap.instruments.logging_factory import (
    AddressProtocol,
    RequestProtocol,
    ScopeType,
    _MemoryLoggerFactoryConfig,
    _serialize_log_with_orjson_to_string,
)


if typing.TYPE_CHECKING:
    from lite_bootstrap.instruments.logging_factory import MemoryLoggerFactory
    from structlog.typing import EventDict, WrappedLogger


if import_checker.is_structlog_installed:
    import structlog

    from lite_bootstrap.instruments.logging_factory import MemoryLoggerFactory


if import_checker.is_opentelemetry_installed:
    from opentelemetry import trace

    def tracer_injection(_: "WrappedLogger", __: str, event_dict: "EventDict") -> "EventDict":
        current_span = trace.get_current_span()
        if not current_span.is_recording():
            event_dict["tracing"] = {}
            return event_dict

        current_span_context = current_span.get_span_context()
        event_dict["tracing"] = {
            "span_id": trace.format_span_id(current_span_context.span_id),
            "trace_id": trace.format_trace_id(current_span_context.trace_id),
        }
        return event_dict

else:  # pragma: no cover

    def tracer_injection(_: "WrappedLogger", __: str, event_dict: "EventDict") -> "EventDict":
        return event_dict


__all__ = [
    "AddressProtocol",
    "LoggingConfig",
    "LoggingInstrument",
    "MemoryLoggerFactory",
    "RequestProtocol",
    "ScopeType",
    "tracer_injection",
]


@dataclasses.dataclass(kw_only=True, frozen=True)
class LoggingConfig(BaseConfig):
    logging_log_level: int = logging.INFO
    logging_flush_level: int = logging.ERROR
    logging_buffer_capacity: int = 10
    logging_extra_processors: list[typing.Any] = dataclasses.field(default_factory=list)
    logging_unset_handlers: list[str] = dataclasses.field(
        default_factory=list,
    )
    logging_time_stamper: "structlog.processors.TimeStamper | None" = None
    logging_enabled: bool = True


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class LoggingInstrument(BaseInstrument[LoggingConfig]):
    not_ready_message = "logging_enabled is False"
    missing_dependency_message = "structlog is not installed"
    _logger_factory: "MemoryLoggerFactory | None" = dataclasses.field(
        default_factory=lambda: None, init=False, repr=False, compare=False
    )

    @property
    def structlog_pre_chain_processors(self) -> list[typing.Any]:
        return [
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            tracer_injection,
            structlog.stdlib.PositionalArgumentsFormatter(),
            self.bootstrap_config.logging_time_stamper or structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
        ]

    def is_ready(self) -> bool:
        return self.bootstrap_config.logging_enabled

    @staticmethod
    def check_dependencies() -> bool:
        return import_checker.is_structlog_installed

    def _unset_handlers(self) -> None:
        """Clear handlers on the named loggers. Mutation is permanent; teardown() does not restore."""
        for unset_handlers_logger in self.bootstrap_config.logging_unset_handlers:
            logging.getLogger(unset_handlers_logger).handlers = []

    @property
    def structlog_processors(self) -> list[typing.Any]:
        return [
            structlog.stdlib.filter_by_level,
            *self.structlog_pre_chain_processors,
            *self.bootstrap_config.logging_extra_processors,
            structlog.processors.JSONRenderer(serializer=_serialize_log_with_orjson_to_string),
        ]

    @property
    def memory_logger_factory(self) -> "MemoryLoggerFactory":
        cached: MemoryLoggerFactory | None = self._logger_factory
        if cached is None:
            cached = MemoryLoggerFactory(
                config=_MemoryLoggerFactoryConfig(
                    logging_buffer_capacity=self.bootstrap_config.logging_buffer_capacity,
                    logging_flush_level=self.bootstrap_config.logging_flush_level,
                    logging_log_level=self.bootstrap_config.logging_log_level,
                ),
            )
            object.__setattr__(self, "_logger_factory", cached)
        return cached

    def _configure_structlog_loggers(self) -> None:
        structlog.configure(
            processors=self.structlog_processors,
            context_class=dict,
            logger_factory=self.memory_logger_factory,
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=True,
        )

    def _configure_foreign_loggers(self) -> None:
        root_logger: typing.Final = logging.getLogger()
        stream_handler: typing.Final = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(
            structlog.stdlib.ProcessorFormatter(
                foreign_pre_chain=self.structlog_pre_chain_processors,
                processors=[
                    structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                    *self.bootstrap_config.logging_extra_processors,
                    structlog.processors.JSONRenderer(serializer=_serialize_log_with_orjson_to_string),
                ],
                logger=root_logger,
            )
        )
        root_logger.addHandler(stream_handler)
        root_logger.setLevel(self.bootstrap_config.logging_log_level)

    def bootstrap(self) -> None:
        self._unset_handlers()
        self._configure_structlog_loggers()
        self._configure_foreign_loggers()

    def teardown(self) -> None:
        """Reset structlog and root logger. Root logger level is unconditionally set to WARNING; pre-existing user configuration is overwritten."""
        structlog.reset_defaults()
        root_logger = logging.getLogger()
        for h in root_logger.handlers[:]:
            root_logger.removeHandler(h)
            h.close()
        root_logger.setLevel(logging.WARNING)
        if self._logger_factory is not None:
            try:
                self._logger_factory.close_handlers()
            finally:
                object.__setattr__(self, "_logger_factory", None)
```

Key differences from the original:
- Module-top imports from `logging_factory`: `AddressProtocol`, `RequestProtocol`, `ScopeType`, `_MemoryLoggerFactoryConfig`, `_serialize_log_with_orjson_to_string` (all unconditional, no structlog dependency).
- `MemoryLoggerFactory` import is gated — at module top in `TYPE_CHECKING` block (for annotations) and inside `if import_checker.is_structlog_installed:` (for runtime use). This mirrors the original module's lazy-resolution pattern: `MemoryLoggerFactory` is only referenced at runtime when structlog is installed.
- `__all__` explicitly re-exports the moved public symbols (`AddressProtocol`, `MemoryLoggerFactory`, `RequestProtocol`, `ScopeType`) for backward compatibility. Consumers who try to access `MemoryLoggerFactory` without structlog will get `AttributeError` — same behavior as the original module.
- `_unset_handlers` and `teardown` now have one-line docstrings (LOW-8, LOW-9).
- `memory_logger_factory` property constructs `MemoryLoggerFactory` with a `_MemoryLoggerFactoryConfig` (LOW-6).
- All `MemoryLoggerFactory`/factory-internal code is gone — sourced from the new module.

### Step 3: Verify the split with a quick smoke test

```bash
just test -- tests/instruments/test_logging_instrument.py -v
```

Expected: existing tests may fail because they construct `MemoryLoggerFactory(logging_buffer_capacity=..., ...)` with the old signature. We'll fix those in Step 6 below. For now, just verify that imports resolve cleanly (no `ImportError`).

If you see `ImportError`, the file split is broken — investigate before proceeding.

### Step 4: REF-2 — delete dead defensive check in `LitestarLoggingInstrument.bootstrap`

**File:** `lite_bootstrap/bootstrappers/litestar_bootstrapper.py`

Locate `LitestarLoggingInstrument.bootstrap`. Current:

```python
    def bootstrap(self) -> None:
        self._unset_handlers()
        if import_checker.is_structlog_installed and import_checker.is_litestar_installed:
            self.bootstrap_config.application_config.plugins.append(
                StructlogPlugin(
                    config=StructlogConfig(
                        structlog_logging_config=StructLoggingConfig(
                            processors=self.structlog_processors,
                            logger_factory=self.memory_logger_factory,
                            wrapper_class=structlog.stdlib.BoundLogger,
                            cache_logger_on_first_use=True,
                            pretty_print_tty=False,
                            standard_lib_logging_config=None,
                        ),
                    ),
                )
            )
            self._configure_foreign_loggers()
```

Replace with (delete the `if` line and the matching dedent — the body unindents one level):

```python
    def bootstrap(self) -> None:
        self._unset_handlers()
        self.bootstrap_config.application_config.plugins.append(
            StructlogPlugin(
                config=StructlogConfig(
                    structlog_logging_config=StructLoggingConfig(
                        processors=self.structlog_processors,
                        logger_factory=self.memory_logger_factory,
                        wrapper_class=structlog.stdlib.BoundLogger,
                        cache_logger_on_first_use=True,
                        pretty_print_tty=False,
                        standard_lib_logging_config=None,
                    ),
                ),
            )
        )
        self._configure_foreign_loggers()
```

The `if import_checker.is_structlog_installed and import_checker.is_litestar_installed:` check is dead — the instrument couldn't have been registered without both packages installed.

### Step 5: Update tests to use `_MemoryLoggerFactoryConfig`

**File:** `tests/instruments/test_logging_instrument.py`

There are two tests (`test_memory_logger_factory_info`, `test_memory_logger_factory_error`) that instantiate `MemoryLoggerFactory` directly. Both need to be updated to use the new config-based API.

Locate the top-of-file imports. The current imports look like:

```python
import logging
from io import StringIO

import structlog
from opentelemetry.trace import get_tracer

from lite_bootstrap.instruments.logging_instrument import LoggingConfig, LoggingInstrument, MemoryLoggerFactory
from lite_bootstrap.instruments.opentelemetry_instrument import OpentelemetryConfig, OpenTelemetryInstrument
from tests.conftest import LoggingMock
```

(After PR3 the file also has `from unittest.mock import patch` and `import pytest`; preserve those.)

Add `_MemoryLoggerFactoryConfig` to the imports. Either import from `logging_factory` directly (more explicit) or from `logging_instrument` (which already re-imports it). Use the direct path for clarity:

```python
from lite_bootstrap.instruments.logging_factory import _MemoryLoggerFactoryConfig
```

Place this after the `from lite_bootstrap.instruments.logging_instrument import ...` line.

Locate `test_memory_logger_factory_info`. Current:

```python
def test_memory_logger_factory_info() -> None:
    test_capacity = 10
    test_flush_level = logging.ERROR
    test_stream = StringIO()

    logger_factory = MemoryLoggerFactory(
        logging_buffer_capacity=test_capacity,
        logging_flush_level=test_flush_level,
        logging_log_level=logging.INFO,
        log_stream=test_stream,
    )
    ...
```

Replace the `MemoryLoggerFactory(...)` call with:

```python
    logger_factory = MemoryLoggerFactory(
        config=_MemoryLoggerFactoryConfig(
            logging_buffer_capacity=test_capacity,
            logging_flush_level=test_flush_level,
            logging_log_level=logging.INFO,
            log_stream=test_stream,
        ),
    )
```

Do the same in `test_memory_logger_factory_error`.

### Step 6: Add lifecycle replay test (TEST-8)

In the same file, append a new test:

```python
def test_logging_instrument_lifecycle_replay(logging_mock: LoggingMock) -> None:
    instrument = LoggingInstrument(
        bootstrap_config=LoggingConfig(
            logging_buffer_capacity=0,
            logging_extra_processors=[logging_mock],
        ),
    )
    try:
        instrument.bootstrap()
        instrument.teardown()
        instrument.bootstrap()
        logger = structlog.getLogger(__name__)
        logger.info("after replay")
        assert any(e.get("event") == "after replay" for e in logging_mock.entries)
    finally:
        instrument.teardown()
```

Contract: bootstrap → teardown → bootstrap must succeed without raising. After the second bootstrap, the instrument is functional (new logger entries flow through `logging_mock`). The final `teardown()` in `finally` ensures global state is cleaned up regardless of test outcome.

### Step 7: Run the full logging test file

```bash
just test -- tests/instruments/test_logging_instrument.py -v
```

Expected: all tests PASS, including the two updated factory tests and the new lifecycle replay test.

If any test fails, investigate. The most likely cause is a typo in the `_MemoryLoggerFactoryConfig` construction.

### Step 8: Run the full test suite

```bash
just test
```

Expected: 127/127 PASS (after PR10 brought the total to 127, this PR adds 1 test → 128). Watch for failures in the framework integration tests — particularly `test_fastapi_bootstrap`, `test_litestar_bootstrap`, `test_faststream_bootstrap` — which exercise the full logging instrument lifecycle.

### Step 9: Run lint

```bash
just lint
```

Expected: clean. The file split and dataclass-config refactor shouldn't introduce lint issues.

**Important — PLR2004 policy:** If ruff flags any numeric literal in test assertions with PLR2004 (magic value), DO NOT add `# noqa: PLR2004`. Extract the value to a named local variable. Example: `expected_capacity = 10; assert factory.config.logging_buffer_capacity == expected_capacity`.

### Step 10: Commit

Stage all five touched files:

```bash
git add \
  lite_bootstrap/instruments/logging_factory.py \
  lite_bootstrap/instruments/logging_instrument.py \
  lite_bootstrap/bootstrappers/litestar_bootstrapper.py \
  tests/instruments/test_logging_instrument.py
git commit -m "$(cat <<'EOF'
refactor: split logging module + cleanup + lifecycle test

REF-4: Split lite_bootstrap/instruments/logging_instrument.py (212
lines, four concerns) into:
- logging_factory.py: MemoryLoggerFactory, _MemoryLoggerFactoryConfig,
  _serialize_log_with_orjson_to_string, AddressProtocol,
  RequestProtocol, ScopeType. Single structlog-conditional gate at
  module top.
- logging_instrument.py: LoggingConfig, LoggingInstrument,
  tracer_injection. Re-imports the moved public symbols
  (MemoryLoggerFactory, AddressProtocol, RequestProtocol, ScopeType)
  for backward compatibility — existing imports from
  lite_bootstrap.instruments.logging_instrument continue to work.

LOW-6: MemoryLoggerFactory.__init__ now takes a single
_MemoryLoggerFactoryConfig dataclass instead of four logging-config
kwargs. The dataclass is underscore-prefixed (internal); tests import
it explicitly when constructing the factory directly.

REF-2: Delete the dead `if import_checker.is_structlog_installed and
import_checker.is_litestar_installed:` defensive check in
LitestarLoggingInstrument.bootstrap. The check is unreachable —
the instrument couldn't have been registered without both packages
installed.

LOW-8: Add a docstring to LoggingInstrument._unset_handlers documenting
that the mutation is permanent (teardown does not restore handlers).

LOW-9: Add a docstring to LoggingInstrument.teardown documenting that
root logger level is unconditionally reset to WARNING.

TEST-8: Add test_logging_instrument_lifecycle_replay exercising
bootstrap → teardown → bootstrap → teardown and verifying the
instrument is functional after the second bootstrap.

No external behavior change. Updated factory tests to use the new
config-based constructor.

Closes REF-2, REF-4, LOW-6, LOW-8, LOW-9, TEST-8 from the audit.
EOF
)"
```

---

## Task 3: Push and open PR

- [ ] **Step 1: Push the branch**

```bash
git push -u origin refactor/ref-4-logging-cleanup
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --title "refactor: split logging module + cleanup + lifecycle test" --body "$(cat <<'EOF'
## Summary
The biggest PR of the deferred-refactors sequence — six logging-area items bundled:

- **REF-4:** Split `logging_instrument.py` (212 lines, four concerns) into a new `logging_factory.py` (MemoryLoggerFactory + serializer + protocols + the new internal `_MemoryLoggerFactoryConfig`) and a slimmer `logging_instrument.py` (config + instrument + tracer injection). Single structlog-conditional gate at the new module's top, vs three separate gates in the old layout. Backward compatibility: the moved public symbols are re-imported into `logging_instrument.py`, so existing `from lite_bootstrap.instruments.logging_instrument import MemoryLoggerFactory` continues to work.
- **REF-2:** Deleted the dead `if import_checker.is_structlog_installed and import_checker.is_litestar_installed:` check in `LitestarLoggingInstrument.bootstrap()`. Unreachable code (the instrument couldn't have been registered without both packages installed).
- **LOW-6:** `MemoryLoggerFactory.__init__` now takes a single `_MemoryLoggerFactoryConfig` dataclass instead of four logging-config kwargs. Underscore-prefixed because it's internal; tests import it directly.
- **LOW-8:** Added a docstring to `LoggingInstrument._unset_handlers` documenting that the mutation is permanent — teardown does NOT restore handlers.
- **LOW-9:** Added a docstring to `LoggingInstrument.teardown()` documenting that root logger level is unconditionally reset to `WARNING`.
- **TEST-8:** New `test_logging_instrument_lifecycle_replay` exercises bootstrap → teardown → bootstrap → teardown and verifies the instrument is functional after the second bootstrap.

No external behavior change. Two existing factory tests updated to use the new config-based constructor.

Closes REF-2, REF-4, LOW-6, LOW-8, LOW-9, TEST-8 from an internal audit.

## Test plan
- [x] `just test -- tests/instruments/test_logging_instrument.py -v` — pass (including updated factory tests + new lifecycle replay).
- [x] `just test` — 128/128 (127 prior + 1 new).
- [x] `just lint` — clean.
- [ ] Reviewer: confirm the backward-compat re-imports in `logging_instrument.py` cover all the public symbols (MemoryLoggerFactory, AddressProtocol, RequestProtocol, ScopeType).
- [ ] Reviewer: confirm the test update for the new config-based `MemoryLoggerFactory` constructor is correct.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review

**Spec coverage check** against the sequencing spec (PR11 section) and audit:

| Spec item | Task |
|-----------|------|
| REF-4: Split `logging_instrument.py` into `logging_factory.py` + slimmer `logging_instrument.py` | Task 2, Steps 1-2 |
| REF-2: Delete dead defensive check in `LitestarLoggingInstrument.bootstrap` | Task 2, Step 4 |
| LOW-6: `MemoryLoggerFactory` takes `_MemoryLoggerFactoryConfig` | Task 2, Steps 1, 2, 5 |
| LOW-8: docstring on `_unset_handlers` | Task 2, Step 2 |
| LOW-9: docstring on `teardown` | Task 2, Step 2 |
| TEST-8: lifecycle replay test | Task 2, Step 6 |
| Branch name `refactor/ref-4-logging-cleanup` | Task 1, Step 1 |
| Verification: `just test` + `just lint` clean | Task 2, Steps 8-9 |
| PLR2004 noqa NOT used; extract constants instead | Task 2, Step 9 (callout) |

All spec items covered. No placeholders. Backward compatibility for moved public symbols is explicitly handled via re-imports in `logging_instrument.py` with `__all__` listing them.

**Risk notes:**
- The file split is the highest-risk change. If imports break anywhere in the codebase or tests, this PR's full suite run catches it.
- The MemoryLoggerFactory constructor change is API-breaking for direct users of `MemoryLoggerFactory(logging_buffer_capacity=..., ...)`. Since `MemoryLoggerFactory` is publicly exported but its internals are framework-level (users rarely construct it directly outside tests), the impact is small. Documented in the commit message.


---

# PR12: Base Layer Cleanup (REF-3 + REF-5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:**
- **REF-3**: Drop `abc.ABC` from `BaseInstrument`. After PR7 made the class generic and removed the `# noqa: B027` suppressions, the `abc.ABC` parent serves no purpose — all four methods (`bootstrap`, `teardown`, `is_ready`, `check_dependencies`) are concrete no-ops with sensible defaults. Removing it clarifies the class's role as a regular generic base.
- **REF-5**: Add a one-line module docstring to `swagger_instrument.py` and `prometheus_instrument.py` explaining that these files are config holders; framework-specific behavior lives in the bootstrapper subclasses. Per the locked decision in the sequencing spec, KEEP these files as separate modules (don't collapse).

**Architecture:** Three files, three small edits. No behavior change.

**Tech Stack:** Python 3.10+ dataclasses, generics.

**Parent spec:** `docs/superpowers/specs/2026-06-01-deferred-refactors-sequencing.md` (PR12 section).
**Parent audit:** `docs/superpowers/specs/2026-05-31-bug-refactor-audit.md` (REF-3, REF-5).

---

## File Structure

Three files modified.

- Modify: `lite_bootstrap/instruments/base.py` — drop `abc.ABC` from `BaseInstrument`; remove the `import abc`.
- Modify: `lite_bootstrap/instruments/swagger_instrument.py` — add module docstring.
- Modify: `lite_bootstrap/instruments/prometheus_instrument.py` — add module docstring.

---

## Locked decisions (from sequencing spec)

- **REF-3 scope:** Only `BaseInstrument` loses `abc.ABC`. `BaseBootstrapper` (in `lite_bootstrap/bootstrappers/base.py`) keeps `abc.ABC` because it HAS abstract methods (`not_ready_message`, `_prepare_application`, `is_ready`).
- **REF-5 scope:** Keep `swagger_instrument.py` and `prometheus_instrument.py` as separate files (don't collapse). Add module docstrings explaining the split.

---

## Task 1: Create branch

**Files:** (no files; git only)

- [ ] **Step 1: Branch off `main`**

```bash
git checkout main
git pull --ff-only origin main
git checkout -b refactor/ref-3-5-base-layer
```

Expected: `Switched to a new branch 'refactor/ref-3-5-base-layer'`.

---

## Task 2: Apply both changes, verify, commit

### Step 1: REF-3 — drop `abc.ABC` from `BaseInstrument`

**File:** `lite_bootstrap/instruments/base.py`

Current file:

```python
import abc
import dataclasses
import typing

import typing_extensions


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class BaseConfig:
    ...


ConfigT = typing.TypeVar("ConfigT", bound=BaseConfig)


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class BaseInstrument(abc.ABC, typing.Generic[ConfigT]):
    bootstrap_config: ConfigT
    not_ready_message = ""
    missing_dependency_message = ""

    def bootstrap(self) -> None: ...

    def teardown(self) -> None: ...

    def is_ready(self) -> bool:
        return True

    @staticmethod
    def check_dependencies() -> bool:
        return True
```

Two changes:

1. Remove `import abc` from the top (it's no longer used in this file).
2. Change `class BaseInstrument(abc.ABC, typing.Generic[ConfigT]):` to `class BaseInstrument(typing.Generic[ConfigT]):`.

After:

```python
import dataclasses
import typing

import typing_extensions


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class BaseConfig:
    ...


ConfigT = typing.TypeVar("ConfigT", bound=BaseConfig)


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class BaseInstrument(typing.Generic[ConfigT]):
    bootstrap_config: ConfigT
    not_ready_message = ""
    missing_dependency_message = ""

    def bootstrap(self) -> None: ...

    def teardown(self) -> None: ...

    def is_ready(self) -> bool:
        return True

    @staticmethod
    def check_dependencies() -> bool:
        return True
```

`BaseConfig` is preserved unchanged (it never used `abc.ABC`).

### Step 2: REF-5 — add docstring to `swagger_instrument.py`

**File:** `lite_bootstrap/instruments/swagger_instrument.py`

Current file:

```python
import dataclasses

from lite_bootstrap.instruments.base import BaseConfig, BaseInstrument


@dataclasses.dataclass(kw_only=True, frozen=True)
class SwaggerConfig(BaseConfig):
    swagger_static_path: str = "/static"
    swagger_path: str = "/docs"
    swagger_offline_docs: bool = False


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class SwaggerInstrument(BaseInstrument[SwaggerConfig]):
    pass
```

Add a module docstring at the top:

```python
"""Swagger config and minimal base instrument; framework-specific behavior lives in the bootstrapper subclasses."""

import dataclasses

from lite_bootstrap.instruments.base import BaseConfig, BaseInstrument


@dataclasses.dataclass(kw_only=True, frozen=True)
class SwaggerConfig(BaseConfig):
    swagger_static_path: str = "/static"
    swagger_path: str = "/docs"
    swagger_offline_docs: bool = False


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class SwaggerInstrument(BaseInstrument[SwaggerConfig]):
    pass
```

Single addition: the module docstring on line 1.

### Step 3: REF-5 — add docstring to `prometheus_instrument.py`

**File:** `lite_bootstrap/instruments/prometheus_instrument.py`

Current file:

```python
import dataclasses

from lite_bootstrap.helpers.path import is_valid_path
from lite_bootstrap.instruments.base import BaseConfig, BaseInstrument


@dataclasses.dataclass(kw_only=True, frozen=True)
class PrometheusConfig(BaseConfig):
    prometheus_metrics_path: str = "/metrics"
    prometheus_metrics_include_in_schema: bool = False


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class PrometheusInstrument(BaseInstrument[PrometheusConfig]):
    not_ready_message = "prometheus_metrics_path is empty or not valid"

    def is_ready(self) -> bool:
        return bool(self.bootstrap_config.prometheus_metrics_path) and is_valid_path(
            self.bootstrap_config.prometheus_metrics_path
        )
```

Add a module docstring:

```python
"""Prometheus config and readiness check; framework-specific bootstrap lives in the bootstrapper subclasses."""

import dataclasses

from lite_bootstrap.helpers.path import is_valid_path
from lite_bootstrap.instruments.base import BaseConfig, BaseInstrument


@dataclasses.dataclass(kw_only=True, frozen=True)
class PrometheusConfig(BaseConfig):
    ...
```

(Rest of the file unchanged.)

### Step 4: Run the full test suite

```bash
just test
```

Expected: 128/128 PASS. REF-3 is a metaclass/MRO change but `abc.ABC` was unused (no abstract methods); dropping it should be invisible at runtime. REF-5 is pure docstring additions.

Watch for surprises in:
- `tests/test_free_bootstrap.py` — exercises the base instrument lifecycle directly.
- Framework integration tests — instantiate instruments via the bootstrapper chain.

If anything fails, the most likely cause is some `isinstance(..., abc.ABC)` check somewhere, or a place that relies on the `abc.ABC` metaclass. Search the codebase: `grep -rn "abc\.ABC\|isinstance.*ABC" lite_bootstrap/ tests/`. If only `bootstrappers/base.py` matches (BaseBootstrapper still uses ABC), all good.

### Step 5: Run lint

```bash
just lint
```

Expected: clean. Watch for `F401` warning on the removed `import abc` — should not fire if the import was actually removed.

### Step 6: Commit

Stage exactly three files:

```bash
git add \
  lite_bootstrap/instruments/base.py \
  lite_bootstrap/instruments/swagger_instrument.py \
  lite_bootstrap/instruments/prometheus_instrument.py
git commit -m "$(cat <<'EOF'
refactor: drop unused abc.ABC from BaseInstrument; document config holders

REF-3: BaseInstrument inherited from abc.ABC but defined no abstract
methods. After PR7 made the class generic and removed the # noqa: B027
suppressions, abc.ABC serves no purpose — all four methods
(bootstrap, teardown, is_ready, check_dependencies) are concrete
no-ops with sensible defaults. Drop the abc.ABC parent and the now-
unused `import abc`.

BaseBootstrapper still uses abc.ABC (it has real abstract methods:
not_ready_message, _prepare_application, is_ready) and is unchanged.

REF-5: Add one-line module docstrings to swagger_instrument.py and
prometheus_instrument.py explaining that these files hold config and
minimal base logic; framework-specific bootstrap behavior lives in
the bootstrapper subclasses (FastAPISwaggerInstrument, etc.). These
files were left as separate modules per the locked decision in the
deferred-refactors sequencing spec.

No behavior change.

Closes REF-3 and REF-5 from the audit.
EOF
)"
```

---

## Task 3: Push and open PR

- [ ] **Step 1: Push the branch**

```bash
git push -u origin refactor/ref-3-5-base-layer
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --title "refactor: drop unused abc.ABC from BaseInstrument; document config holders" --body "$(cat <<'EOF'
## Summary
Two small base-layer cleanups:

- **REF-3:** `BaseInstrument` inherited from `abc.ABC` but defined no abstract methods. After PR7 made the class generic and removed the `# noqa: B027` suppressions, `abc.ABC` serves no purpose — all four methods (`bootstrap`, `teardown`, `is_ready`, `check_dependencies`) are concrete no-ops with sensible defaults. Drop the `abc.ABC` parent and the now-unused `import abc`. `BaseBootstrapper` still uses `abc.ABC` (it has real abstract methods) and is unchanged.
- **REF-5:** Added one-line module docstrings to `swagger_instrument.py` and `prometheus_instrument.py` explaining that these files hold config and minimal base logic; framework-specific bootstrap behavior lives in the bootstrapper subclasses. Kept as separate modules per the locked decision in the deferred-refactors sequencing spec.

No behavior change.

Closes REF-3 and REF-5 from an internal audit.

## Test plan
- [x] `just test` — 128/128.
- [x] `just lint` — clean.
- [ ] Reviewer: confirm no `isinstance(..., abc.ABC)` check anywhere in the codebase relies on `BaseInstrument`'s ABC parent.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review

**Spec coverage check** against the sequencing spec (PR12 section) and audit (REF-3, REF-5):

| Spec item | Task |
|-----------|------|
| REF-3: drop `abc.ABC` from `BaseInstrument`; drop unused `import abc` | Task 2, Step 1 |
| REF-3: keep `abc.ABC` on `BaseBootstrapper` (not touched) | Task 2, Step 1 (out of scope confirmation) |
| REF-5: docstring on `swagger_instrument.py` | Task 2, Step 2 |
| REF-5: docstring on `prometheus_instrument.py` | Task 2, Step 3 |
| REF-5: keep both files separate (don't collapse) | Locked decisions section |
| Branch name `refactor/ref-3-5-base-layer` | Task 1, Step 1 |
| Verification: `just test` + `just lint` clean | Task 2, Steps 4-5 |

All spec items covered. No placeholders.

**Risk:** Low. Both REF-3 and REF-5 are essentially metadata/documentation changes. The only theoretical risk is a downstream consumer relying on `isinstance(inst, abc.ABC)` checks on `BaseInstrument` instances — vanishingly unlikely in practice. The test suite catches it if anything's broken.


---

# PR13: Drop `frozen=True` From Instruments + FastAPIConfig Default Cleanup (REF-6 + LOW-4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two related-but-distinct cleanups.

- **REF-6**: Drop `frozen=True` from the instrument hierarchy. Python's dataclass rules force a cascade: dropping `frozen=True` from `LoggingInstrument` requires dropping it from `BaseInstrument`, which requires dropping it from every other instrument subclass. 23 dataclass declarations across 12 files lose `frozen=True`. In `LoggingInstrument` and `OpenTelemetryInstrument`, the four `object.__setattr__(self, "_x", value)` workarounds for cached runtime state become plain `self._x = value` assignments. **Configs stay frozen** — only instruments lose `frozen=True`.

- **LOW-4**: `FastAPIConfig.application` currently uses `default=None` + `# ty: ignore[invalid-assignment]` because the field is typed `fastapi.FastAPI` (non-Optional). Replace with a proper sentinel-type pattern: introduce `UnsetType` + `UNSET` in `lite_bootstrap/types.py` (a sentinel class with a singleton instance), type the field as `fastapi.FastAPI | UnsetType`, default to `UNSET`, and replace the truthiness check in `__post_init__` with `isinstance(self.application, UnsetType)`. Add a `_narrow_app(config)` helper at module scope that asserts the type and returns the narrowed value; FastAPI framework instruments call `_narrow_app(self.bootstrap_config)` instead of `self.bootstrap_config.application` directly. Drops the `# ty: ignore`. FastAPIConfig stays frozen — `object.__setattr__(self, "application", ...)` in `__post_init__` remains because the freeze bypass is the only way to mutate a frozen field after construction; a code comment documents the rationale.

**Architecture:** Largest mechanical refactor in the deferred-refactors sequence. The cascade is purely mechanical — every change is `frozen=True` → (delete). The setattr replacements and LOW-4 sentinel are the only meaningful diffs.

**Tech Stack:** Python 3.10+ dataclasses, frozen-inheritance rules.

**Parent spec:** `docs/superpowers/specs/2026-06-01-deferred-refactors-sequencing.md` (PR13 section).
**Parent audit:** `docs/superpowers/specs/2026-05-31-bug-refactor-audit.md` (REF-6, LOW-4).

---

## Important context: Why the cascade

Python's `@dataclasses.dataclass` enforces that **a non-frozen dataclass cannot inherit from a frozen one** (and vice versa). The check fires at class definition time as `TypeError`.

Today's instrument hierarchy:
- `BaseInstrument(frozen=True)`
- 8 base instrument subclasses, all `frozen=True`
- 15 framework instrument subclasses inheriting from the base instruments, all `frozen=True`

To drop `frozen=True` from `LoggingInstrument` (REF-6's stated target), `BaseInstrument` must also drop it, which forces every other subclass to drop it too. There's no surgical option.

The sequencing spec's PR13 section said "drop `frozen=True` from `LoggingInstrument` and `OpenTelemetryInstrument`" — that was incorrect; the cascade is required. This plan implements the cascade.

---

## File Structure

12 files modified.

**Instrument modules (9 files):**
- `lite_bootstrap/instruments/base.py` — `BaseInstrument` loses `frozen=True`.
- `lite_bootstrap/instruments/cors_instrument.py` — `CorsInstrument` loses `frozen=True`.
- `lite_bootstrap/instruments/healthchecks_instrument.py` — `HealthChecksInstrument` loses `frozen=True`.
- `lite_bootstrap/instruments/logging_instrument.py` — `LoggingInstrument` loses `frozen=True`; 2 `object.__setattr__` calls become direct assignment.
- `lite_bootstrap/instruments/opentelemetry_instrument.py` — `OpenTelemetryInstrument` loses `frozen=True`; 2 `object.__setattr__` calls become direct assignment.
- `lite_bootstrap/instruments/prometheus_instrument.py` — `PrometheusInstrument` loses `frozen=True`.
- `lite_bootstrap/instruments/pyroscope_instrument.py` — `PyroscopeInstrument` loses `frozen=True`.
- `lite_bootstrap/instruments/sentry_instrument.py` — `SentryInstrument` loses `frozen=True`.
- `lite_bootstrap/instruments/swagger_instrument.py` — `SwaggerInstrument` loses `frozen=True`.

**Bootstrapper modules (3 files):**
- `lite_bootstrap/bootstrappers/fastapi_bootstrapper.py` — 5 framework instruments lose `frozen=True` + LOW-4 sentinel-type pattern on `FastAPIConfig.application` + `_narrow_app` helper + every FastAPI instrument bootstrap calls `_narrow_app(self.bootstrap_config)` for the app reference.
- `lite_bootstrap/bootstrappers/litestar_bootstrapper.py` — 6 framework instruments lose `frozen=True`.
- `lite_bootstrap/bootstrappers/faststream_bootstrapper.py` — 4 framework instruments lose `frozen=True`.

**Shared types (1 file):**
- `lite_bootstrap/types.py` — add `UnsetType` class + `UNSET: typing.Final[UnsetType]` singleton. Reusable sentinel for fields that distinguish "not passed" from "explicitly None".

---

## Locked decisions

- **Cascade scope:** Drop `frozen=True` from `BaseInstrument` and ALL 22 instrument subclasses. Configs stay frozen. Confirmed by the user after the constraint surfaced.
- **LOW-4 pattern:** Proper `UnsetType` sentinel class in `lite_bootstrap/types.py`, used via `isinstance(value, UnsetType)`. Honest to the type checker (no `typing.cast` lie). Adds a `_narrow_app` helper that wraps the assert/return narrowing for callers. Revised from the original plan's `typing.cast("fastapi.FastAPI", object())` pattern — the spec was updated retroactively to match what was built.
- **`FastAPIConfig` stays frozen:** Confirmed by user. The `object.__setattr__(self, "application", ...)` in `__post_init__` remains; a one-line code comment documents the rationale (frozen for user-facing immutability; bypass needed because `application` is constructed using other config fields).
- **No new tests.** The full existing test suite verifies behavior preservation; pure-refactor changes should not affect runtime semantics other than enabling future direct mutation (which we don't exercise).

---

## Cascade list (23 dataclass declarations)

For traceability, every dataclass decorator changing from `@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)` to `@dataclasses.dataclass(kw_only=True, slots=True)` (or `@dataclasses.dataclass(kw_only=True, frozen=True)` to `@dataclasses.dataclass(kw_only=True)`):

| # | Class | File |
|---|-------|------|
| 1 | `BaseInstrument` | `instruments/base.py` |
| 2 | `CorsInstrument` | `instruments/cors_instrument.py` |
| 3 | `HealthChecksInstrument` | `instruments/healthchecks_instrument.py` |
| 4 | `LoggingInstrument` | `instruments/logging_instrument.py` |
| 5 | `OpenTelemetryInstrument` | `instruments/opentelemetry_instrument.py` |
| 6 | `PrometheusInstrument` | `instruments/prometheus_instrument.py` |
| 7 | `PyroscopeInstrument` | `instruments/pyroscope_instrument.py` |
| 8 | `SentryInstrument` | `instruments/sentry_instrument.py` |
| 9 | `SwaggerInstrument` | `instruments/swagger_instrument.py` |
| 10 | `FastAPICorsInstrument` | `bootstrappers/fastapi_bootstrapper.py` |
| 11 | `FastAPIHealthChecksInstrument` | `bootstrappers/fastapi_bootstrapper.py` |
| 12 | `FastAPIOpenTelemetryInstrument` | `bootstrappers/fastapi_bootstrapper.py` |
| 13 | `FastAPIPrometheusInstrument` | `bootstrappers/fastapi_bootstrapper.py` |
| 14 | `FastAPISwaggerInstrument` | `bootstrappers/fastapi_bootstrapper.py` |
| 15 | `LitestarCorsInstrument` | `bootstrappers/litestar_bootstrapper.py` |
| 16 | `LitestarHealthChecksInstrument` | `bootstrappers/litestar_bootstrapper.py` |
| 17 | `LitestarLoggingInstrument` | `bootstrappers/litestar_bootstrapper.py` |
| 18 | `LitestarOpenTelemetryInstrument` | `bootstrappers/litestar_bootstrapper.py` |
| 19 | `LitestarPrometheusInstrument` | `bootstrappers/litestar_bootstrapper.py` |
| 20 | `LitestarSwaggerInstrument` | `bootstrappers/litestar_bootstrapper.py` |
| 21 | `FastStreamHealthChecksInstrument` | `bootstrappers/faststream_bootstrapper.py` |
| 22 | `FastStreamLoggingInstrument` | `bootstrappers/faststream_bootstrapper.py` |
| 23 | `FastStreamOpenTelemetryInstrument` | `bootstrappers/faststream_bootstrapper.py` |
| 24 | `FastStreamPrometheusInstrument` | `bootstrappers/faststream_bootstrapper.py` |

(Yes, that's 24 — `LitestarSwaggerInstrument` is on the list because it inherits from `SwaggerInstrument`. All 24 actually need updating to keep the cascade consistent.)

**Configs are NOT in this list.** `BaseConfig`, `LoggingConfig`, `SentryConfig`, `OpentelemetryConfig`, `PyroscopeConfig`, `CorsConfig`, `HealthChecksConfig`, `PrometheusConfig`, `SwaggerConfig`, `OpenTelemetryServiceFieldsConfig`, `FastAPIConfig`, `LitestarConfig`, `FastStreamConfig`, `FreeBootstrapperConfig` — all stay frozen.

---

## Task 1: Create branch

**Files:** (no files; git only)

- [ ] **Step 1: Branch off `main`**

```bash
git checkout main
git pull --ff-only origin main
git checkout -b refactor/ref-6-frozen-setattr
```

Expected: `Switched to a new branch 'refactor/ref-6-frozen-setattr'`.

---

## Task 2: Drop `frozen=True` from the cascade

For each file below, the change pattern is identical: locate each instrument's `@dataclasses.dataclass(...)` decorator and remove `, frozen=True` (or `frozen=True,` if it's not last). Configs are untouched.

### Step 1: `lite_bootstrap/instruments/base.py`

Locate `BaseInstrument`. Change:

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class BaseInstrument(typing.Generic[ConfigT]):
```

to:

```python
@dataclasses.dataclass(kw_only=True, slots=True)
class BaseInstrument(typing.Generic[ConfigT]):
```

`BaseConfig` (above it) stays untouched — keep `frozen=True`.

### Step 2: `lite_bootstrap/instruments/cors_instrument.py`

`CorsInstrument` decorator: drop `frozen=True`.

### Step 3: `lite_bootstrap/instruments/healthchecks_instrument.py`

`HealthChecksInstrument` decorator: drop `frozen=True`.

### Step 4: `lite_bootstrap/instruments/logging_instrument.py`

`LoggingInstrument` decorator: drop `frozen=True`.

Then replace 2 `object.__setattr__` calls with direct assignment:

In `memory_logger_factory` property (around line 109):
```python
# Before:
object.__setattr__(self, "_logger_factory", cached)
# After:
self._logger_factory = cached
```

In `teardown` method:
```python
# Before:
try:
    self._logger_factory.close_handlers()
finally:
    object.__setattr__(self, "_logger_factory", None)

# After:
try:
    self._logger_factory.close_handlers()
finally:
    self._logger_factory = None
```

### Step 5: `lite_bootstrap/instruments/opentelemetry_instrument.py`

`OpenTelemetryInstrument` decorator: drop `frozen=True`.

Then replace 2 `object.__setattr__` calls:

In `bootstrap()`:
```python
# Before:
object.__setattr__(self, "_tracer_provider", tracer_provider)
# After:
self._tracer_provider = tracer_provider
```

In `teardown()`:
```python
# Before:
try:
    self._tracer_provider.shutdown()
finally:
    object.__setattr__(self, "_tracer_provider", None)

# After:
try:
    self._tracer_provider.shutdown()
finally:
    self._tracer_provider = None
```

### Step 6: `lite_bootstrap/instruments/prometheus_instrument.py`

`PrometheusInstrument` decorator: drop `frozen=True`.

### Step 7: `lite_bootstrap/instruments/pyroscope_instrument.py`

`PyroscopeInstrument` decorator: drop `frozen=True`.

### Step 8: `lite_bootstrap/instruments/sentry_instrument.py`

`SentryInstrument` decorator: drop `frozen=True`.

### Step 9: `lite_bootstrap/instruments/swagger_instrument.py`

`SwaggerInstrument` decorator: drop `frozen=True`.

### Step 10: `lite_bootstrap/bootstrappers/fastapi_bootstrapper.py` — 5 framework instruments

Drop `frozen=True` from the decorators of:
- `FastAPICorsInstrument`
- `FastAPIHealthChecksInstrument`
- `FastAPIOpenTelemetryInstrument`
- `FastAPIPrometheusInstrument`
- `FastAPISwaggerInstrument`

Each uses `@dataclasses.dataclass(kw_only=True, frozen=True)` (no `slots=True`). After: `@dataclasses.dataclass(kw_only=True)`.

`FastAPIConfig` stays untouched here (frozen). The LOW-4 sentinel change comes in Task 3.

### Step 11: `lite_bootstrap/bootstrappers/litestar_bootstrapper.py` — 6 framework instruments

Drop `frozen=True` from:
- `LitestarCorsInstrument`
- `LitestarHealthChecksInstrument`
- `LitestarLoggingInstrument`
- `LitestarOpenTelemetryInstrument`
- `LitestarPrometheusInstrument`
- `LitestarSwaggerInstrument`

`LitestarConfig` stays frozen.

### Step 12: `lite_bootstrap/bootstrappers/faststream_bootstrapper.py` — 4 framework instruments

Drop `frozen=True` from:
- `FastStreamHealthChecksInstrument`
- `FastStreamLoggingInstrument`
- `FastStreamOpenTelemetryInstrument`
- `FastStreamPrometheusInstrument`

`FastStreamConfig` stays frozen.

### Step 13: Quick verification

```bash
just test
```

Expected: 128/128 PASS. If anything fails, the most likely cause is a `frozen=True` left in one of the 24 classes (Python's TypeError surfaces immediately on import).

Run a sanity grep to confirm no instrument-class declaration still has `frozen=True`:

```bash
grep -rn "frozen=True" lite_bootstrap/instruments/ lite_bootstrap/bootstrappers/ | grep -v "Config"
```

Expected: zero matches. The `grep -v "Config"` filters out config classes (which should still have `frozen=True`).

---

## Task 3: LOW-4 — FastAPIConfig sentinel pattern

**File:** `lite_bootstrap/bootstrappers/fastapi_bootstrapper.py`

### Step 1: Add module-level sentinel and update `FastAPIConfig`

Locate the top of the file (after the conditional imports for fastapi). Add this constant right after the `if import_checker.is_fastapi_installed:` block:

```python
if import_checker.is_fastapi_installed:
    import fastapi
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.routing import _merge_lifespan_context

# ... other conditional imports stay as they are ...

_UNSET_FASTAPI_APP: typing.Final = typing.cast("fastapi.FastAPI", object())
```

`typing.cast(...)` is a runtime no-op (returns the second argument). The type checker sees `_UNSET_FASTAPI_APP` as `fastapi.FastAPI`; at runtime it's a unique `object()` sentinel. `typing.Final` prevents accidental reassignment.

The string-quoted `"fastapi.FastAPI"` in the cast lets the line evaluate even when `fastapi` isn't installed (cast doesn't look up the type at runtime).

### Step 2: Update `FastAPIConfig.application` field declaration and `__post_init__`

Locate `FastAPIConfig`. Current:

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class FastAPIConfig(
    CorsConfig,
    ...
):
    application: "fastapi.FastAPI" = dataclasses.field(default=None)  # ty: ignore[invalid-assignment]
    application_kwargs: dict[str, typing.Any] = dataclasses.field(default_factory=dict)
    ...

    def __post_init__(self) -> None:
        if not import_checker.is_fastapi_installed:
            msg = "fastapi is not installed"
            raise ConfigurationError(msg)

        if not self.application:
            object.__setattr__(
                self, "application", fastapi.FastAPI(docs_url=self.swagger_path, **self.application_kwargs)
            )
        elif self.application_kwargs:
            warnings.warn("application_kwargs must be used without application", stacklevel=2)

        self.application.title = self.service_name
        self.application.debug = self.service_debug
        self.application.version = self.service_version
```

Change two things:

1. Replace `application: "fastapi.FastAPI" = dataclasses.field(default=None)  # ty: ignore[invalid-assignment]` with `application: "fastapi.FastAPI" = _UNSET_FASTAPI_APP`. Drop the `# ty: ignore`.

2. In `__post_init__`, replace `if not self.application:` with `if self.application is _UNSET_FASTAPI_APP:`. Identity check instead of truthiness — clearer intent.

After:

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class FastAPIConfig(
    CorsConfig,
    ...
):
    application: "fastapi.FastAPI" = _UNSET_FASTAPI_APP
    application_kwargs: dict[str, typing.Any] = dataclasses.field(default_factory=dict)
    ...

    def __post_init__(self) -> None:
        if not import_checker.is_fastapi_installed:
            msg = "fastapi is not installed"
            raise ConfigurationError(msg)

        if self.application is _UNSET_FASTAPI_APP:
            object.__setattr__(
                self, "application", fastapi.FastAPI(docs_url=self.swagger_path, **self.application_kwargs)
            )
        elif self.application_kwargs:
            warnings.warn("application_kwargs must be used without application", stacklevel=2)

        self.application.title = self.service_name
        self.application.debug = self.service_debug
        self.application.version = self.service_version
```

The `object.__setattr__` for `self.application` stays — `FastAPIConfig` is still frozen.

The `self.application.title = ...` lines below also stay — they mutate the `fastapi.FastAPI` instance (which isn't frozen), not the `FastAPIConfig` dataclass.

---

## Task 4: Verify and commit

### Step 1: Run the full test suite

```bash
just test
```

Expected: 128/128 PASS. The cascade is mechanical and should not affect runtime behavior. Watch for surprises in:

- All framework integration tests (FastAPI, Litestar, FastStream, Free) — they exercise the full instrument lifecycle.
- `test_logging_instrument_lifecycle_replay` (from PR11) — confirms the `_logger_factory` direct-assignment doesn't break the replay cycle.
- `test_opentelemetry_instrument_teardown_shuts_down_tracer_provider` (from PR2) — confirms the `_tracer_provider` direct-assignment doesn't break shutdown.

If any test fails because something now mutates an instrument unexpectedly, that's a real bug surfaced by the refactor (frozen was masking it). Stop and investigate.

### Step 2: Run lint

```bash
just lint
```

Expected: clean. The `# ty: ignore[invalid-assignment]` is gone from `FastAPIConfig.application`. No new lint warnings should appear.

### Step 3: Verify the cascade

```bash
grep -n "frozen=True" lite_bootstrap/instruments/*.py lite_bootstrap/bootstrappers/*.py
```

Expected matches: ONLY on config classes (`BaseConfig`, `LoggingConfig`, `SentryConfig`, `OpentelemetryConfig`, `PyroscopeConfig`, `CorsConfig`, `HealthChecksConfig`, `PrometheusConfig`, `SwaggerConfig`, `OpenTelemetryServiceFieldsConfig`, `FastAPIConfig`, `LitestarConfig`, `FastStreamConfig`, `FreeBootstrapperConfig`).

No instrument class should match. If one does, that's a missed cascade entry — fix it before committing.

### Step 4: Commit

Stage exactly the 12 modified files:

```bash
git add \
  lite_bootstrap/instruments/base.py \
  lite_bootstrap/instruments/cors_instrument.py \
  lite_bootstrap/instruments/healthchecks_instrument.py \
  lite_bootstrap/instruments/logging_instrument.py \
  lite_bootstrap/instruments/opentelemetry_instrument.py \
  lite_bootstrap/instruments/prometheus_instrument.py \
  lite_bootstrap/instruments/pyroscope_instrument.py \
  lite_bootstrap/instruments/sentry_instrument.py \
  lite_bootstrap/instruments/swagger_instrument.py \
  lite_bootstrap/bootstrappers/fastapi_bootstrapper.py \
  lite_bootstrap/bootstrappers/litestar_bootstrapper.py \
  lite_bootstrap/bootstrappers/faststream_bootstrapper.py
git commit -m "$(cat <<'EOF'
refactor: drop frozen=True from instruments; sentinel for FastAPIConfig.application

REF-6: LoggingInstrument and OpenTelemetryInstrument cached mutable
runtime state (_logger_factory, _tracer_provider) via
object.__setattr__ workarounds because the instruments were declared
frozen=True. The frozen claim was partly false — those two fields
mutated freely under the hood.

Python's dataclass rules forbid surgically dropping frozen=True from
a subclass while the parent remains frozen (TypeError at class
definition). The fix cascades through BaseInstrument and all 22
instrument subclasses: drop frozen=True from each. Configs stay
frozen — only instruments lose immutability. The 4 object.__setattr__
call sites in LoggingInstrument and OpenTelemetryInstrument
(bootstrap-cache + teardown-reset for each) become plain self._x = ...
assignments.

LOW-4: FastAPIConfig.application declared default=None with a
# ty: ignore[invalid-assignment] because the field is typed
fastapi.FastAPI (non-Optional). Replace with a typed sentinel:
_UNSET_FASTAPI_APP: typing.Final = typing.cast("fastapi.FastAPI", object())
The cast suppresses the type lie; the sentinel makes __post_init__'s
identity check (is _UNSET_FASTAPI_APP) clearer than the prior
truthiness check (not self.application). FastAPIConfig stays frozen,
so the object.__setattr__(self, "application", ...) in __post_init__
remains — only the default and the check change.

No behavior change. 128/128 tests pass.

Closes REF-6 and LOW-4 from the audit.
EOF
)"
```

---

## Task 5: Push and open PR

- [ ] **Step 1: Push the branch**

```bash
git push -u origin refactor/ref-6-frozen-setattr
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --title "refactor: drop frozen=True from instruments; sentinel for FastAPIConfig.application" --body "$(cat <<'EOF'
## Summary
Two related cleanups in one PR:

- **REF-6 cascade:** `LoggingInstrument` and `OpenTelemetryInstrument` cached mutable runtime state via `object.__setattr__` workarounds because they were declared `frozen=True`. Python's dataclass rules forbid surgically dropping `frozen=True` from one subclass while the parent stays frozen — the cascade is required. `BaseInstrument` and all 22 instrument subclasses lose `frozen=True`. The 4 `object.__setattr__` call sites in `LoggingInstrument` and `OpenTelemetryInstrument` become plain `self._x = ...` assignments.
- **LOW-4:** `FastAPIConfig.application` used `default=None` with a `# ty: ignore`. Replaced with a typed sentinel `_UNSET_FASTAPI_APP: typing.Final = typing.cast("fastapi.FastAPI", object())`. The `__post_init__` check changes from `if not self.application:` to `if self.application is _UNSET_FASTAPI_APP:`. `FastAPIConfig` stays frozen — the existing `object.__setattr__(self, "application", ...)` in `__post_init__` remains.

**Configs are unchanged.** All `*Config` classes keep `frozen=True`. Only instrument classes lose immutability.

12 files modified; 24 dataclass declarations lose `frozen=True`; 4 `object.__setattr__` call sites simplified; 1 `# ty: ignore` removed.

No behavior change. 128/128 tests pass.

Closes REF-6 and LOW-4 from an internal audit.

## Test plan
- [x] `just test` — 128/128.
- [x] `just lint` — clean (no `# ty: ignore` left in FastAPIConfig).
- [x] `grep -n "frozen=True" lite_bootstrap/instruments/ lite_bootstrap/bootstrappers/` — only config classes match.
- [ ] Reviewer: confirm `LoggingInstrument`'s and `OpenTelemetryInstrument`'s direct assignments preserve the `try/finally` exception safety from PR3.

## Why the cascade
Python's `@dataclasses.dataclass` enforces that a non-frozen dataclass cannot inherit from a frozen one (and vice versa) — `TypeError` at class definition. To drop `frozen=True` from `LoggingInstrument` (REF-6's stated target), `BaseInstrument` must also drop it, which propagates to every other instrument subclass. The sequencing spec's PR13 section called for a surgical 2-class change; the actual cascade is 24 classes.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review

**Spec coverage check** against the sequencing spec (PR13 section) and audit (REF-6, LOW-4):

| Spec item | Task |
|-----------|------|
| Drop `frozen=True` from instrument hierarchy (cascade) | Task 2, Steps 1-12 |
| Replace `object.__setattr__` in `LoggingInstrument` with direct assignment | Task 2, Step 4 |
| Replace `object.__setattr__` in `OpenTelemetryInstrument` with direct assignment | Task 2, Step 5 |
| Configs stay frozen | Locked decisions + Task 4 Step 3 verification |
| LOW-4: replace `default=None` + `# ty: ignore` with sentinel | Task 3 |
| Branch name `refactor/ref-6-frozen-setattr` | Task 1, Step 1 |
| Verification: `just test` + `just lint` clean | Task 4, Steps 1-2 |

All spec items covered. No placeholders.

**Risk:** Medium. The cascade is mechanical but touches many classes. The chief risk is a missed entry — the verification grep at Task 4 Step 3 catches that.

The behavioral risk is essentially zero: nothing in the codebase currently mutates an instrument after construction except the 4 `object.__setattr__` calls being replaced. Tests verify the cycles still work.

**Deviation from sequencing spec:** Locked decision said "drop frozen=True from LoggingInstrument and OpenTelemetryInstrument" — implementation required the full 24-class cascade. Documented in the commit message and PR body. The sequencing spec should be updated retroactively (out of scope for this PR; can be a follow-up doc commit).


---

# PR14: Configurable FastStream Broker Health-Check Timeout (REF-7)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `FastStreamHealthChecksInstrument._define_health_status` calls `broker.ping(timeout=5)` with a hardcoded 5-second timeout. For users with slow brokers (large Redis clusters, message queues with cold connections), this is a footgun. Add a `faststream_health_check_broker_timeout: float = 5.0` field on `FastStreamConfig` and wire it through.

**Architecture:** Pure additive config change. New field with backward-compatible default; existing callers see no behavior difference. One new regression test.

**Tech Stack:** Python 3.10+ dataclasses, faststream, `unittest.mock.AsyncMock`.

**Parent spec:** `docs/superpowers/specs/2026-06-01-deferred-refactors-sequencing.md` (PR14 section).
**Parent audit:** `docs/superpowers/specs/2026-05-31-bug-refactor-audit.md` (REF-7).

---

## File Structure

Two files modified.

- Modify: `lite_bootstrap/bootstrappers/faststream_bootstrapper.py` — add `faststream_health_check_broker_timeout: float = 5.0` to `FastStreamConfig`; update `FastStreamHealthChecksInstrument._define_health_status` to use it.
- Modify: `tests/test_faststream_bootstrap.py` — add `test_faststream_health_check_uses_configured_broker_timeout` exercising a non-default timeout.

---

## Locked decisions (from sequencing spec)

- **Field placement:** `FastStreamConfig`, NOT shared `HealthChecksConfig`. The timeout is FastStream-shaped (it's specifically about a message broker ping), so it belongs on the FastStream-specific config alongside other FastStream-only fields (`faststream_log_level`, `opentelemetry_middleware_cls`, etc.). Putting it on `HealthChecksConfig` would pollute FastAPI/Litestar configs with an unused field.
- **Default `5.0`:** Preserves existing behavior. Users who don't set the field see no change.
- **Field name:** `faststream_health_check_broker_timeout`. Prefixed `faststream_` for consistency with the other FastStream-specific fields on this config.

---

## Task 1: Create branch

**Files:** (no files; git only)

- [ ] **Step 1: Branch off `main`**

```bash
git checkout main
git pull --ff-only origin main
git checkout -b fix/ref-7-faststream-timeout
```

Expected: `Switched to a new branch 'fix/ref-7-faststream-timeout'`.

---

## Task 2: Add the failing regression test

**File:** `tests/test_faststream_bootstrap.py`

The existing file uses `RedisBroker` fixtures and `TestClient` from starlette to exercise the health check. We'll spy on `broker.ping` to capture the timeout argument.

### Step 1: Update imports

Current top of file:

```python
import logging
import typing

import faststream.asgi
import pytest
import structlog
from faststream._internal.broker import BrokerUsecase
from faststream._internal.logger.params_storage import ManualLoggerStorage
from faststream.redis import RedisBroker, TestRedisBroker
...
```

Add `dataclasses` (stdlib) and `from unittest.mock import AsyncMock, patch` (stdlib). After:

```python
import dataclasses
import logging
import typing
from unittest.mock import AsyncMock, patch

import faststream.asgi
import pytest
import structlog
from faststream._internal.broker import BrokerUsecase
from faststream._internal.logger.params_storage import ManualLoggerStorage
from faststream.redis import RedisBroker, TestRedisBroker
...
```

(Preserve any existing imports between these — only adding the three new lines in the right import groups.)

### Step 2: Append the new test

At the end of the file, add:

```python
async def test_faststream_health_check_uses_configured_broker_timeout(broker: RedisBroker) -> None:
    expected_timeout = 12.5
    config = dataclasses.replace(
        build_faststream_config(broker=broker),
        faststream_health_check_broker_timeout=expected_timeout,
    )
    bootstrapper = FastStreamBootstrapper(bootstrap_config=config)
    application = bootstrapper.bootstrap()
    try:
        with (
            patch.object(broker, "ping", new=AsyncMock(return_value=True)) as mock_ping,
            TestClient(app=application) as test_client,
        ):
            response = test_client.get(config.health_checks_path)
            assert response.status_code == status.HTTP_200_OK
        mock_ping.assert_called_once_with(timeout=expected_timeout)
    finally:
        bootstrapper.teardown()
```

Contract:
- `dataclasses.replace` on a `FastStreamConfig` (still `frozen=True` post-PR13) creates a new instance overriding only the timeout.
- `patch.object(broker, "ping", new=AsyncMock(return_value=True))` replaces `broker.ping` with an async mock that returns `True` (healthy).
- `TestClient(app=application).get(config.health_checks_path)` triggers the health check, which calls `await broker.ping(timeout=...)`.
- `mock_ping.assert_called_once_with(timeout=expected_timeout)` asserts the configured value reached the broker.

Note: `expected_timeout = 12.5` extracts the magic value into a named local — per the no-`PLR2004`-noqa policy established in PR10.

### Step 3: Run the test and verify it FAILS

```bash
just test -- 'tests/test_faststream_bootstrap.py::test_faststream_health_check_uses_configured_broker_timeout' -v
```

Expected: **FAIL** in one of two ways:
- `AttributeError: 'FastStreamConfig' object has no attribute 'faststream_health_check_broker_timeout'` (the field doesn't exist yet on the config).
- Or: `AssertionError: expected call: ping(timeout=12.5)\nactual call: ping(timeout=5)` (if the field is somehow on the config but the instrument still hardcodes `5`).

Either way, the test should NOT pass before the fix. If it does, stop and investigate.

---

## Task 3: Implement the fix

**File:** `lite_bootstrap/bootstrappers/faststream_bootstrapper.py`

### Step 1: Add field to `FastStreamConfig`

Locate `FastStreamConfig`. Current:

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class FastStreamConfig(
    HealthChecksConfig, LoggingConfig, OpentelemetryConfig, PrometheusConfig, PyroscopeConfig, SentryConfig
):
    application: "AsgiFastStream" = dataclasses.field(default_factory=_make_asgi_faststream)
    opentelemetry_middleware_cls: type[FastStreamTelemetryMiddlewareProtocol] | None = None
    prometheus_middleware_cls: type[FastStreamPrometheusMiddlewareProtocol] | None = None
    faststream_log_level: int = logging.WARNING
```

Add the new field at the end of the body:

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class FastStreamConfig(
    HealthChecksConfig, LoggingConfig, OpentelemetryConfig, PrometheusConfig, PyroscopeConfig, SentryConfig
):
    application: "AsgiFastStream" = dataclasses.field(default_factory=_make_asgi_faststream)
    opentelemetry_middleware_cls: type[FastStreamTelemetryMiddlewareProtocol] | None = None
    prometheus_middleware_cls: type[FastStreamPrometheusMiddlewareProtocol] | None = None
    faststream_log_level: int = logging.WARNING
    faststream_health_check_broker_timeout: float = 5.0
```

Single additive change.

### Step 2: Use the field in `FastStreamHealthChecksInstrument._define_health_status`

Locate `_define_health_status`. Current:

```python
    async def _define_health_status(self) -> bool:
        if not self.bootstrap_config.application or not self.bootstrap_config.application.broker:
            return False

        return await self.bootstrap_config.application.broker.ping(timeout=5)
```

Replace the hardcoded `timeout=5` with `timeout=self.bootstrap_config.faststream_health_check_broker_timeout`:

```python
    async def _define_health_status(self) -> bool:
        if not self.bootstrap_config.application or not self.bootstrap_config.application.broker:
            return False

        return await self.bootstrap_config.application.broker.ping(
            timeout=self.bootstrap_config.faststream_health_check_broker_timeout,
        )
```

The expression is long enough that ruff will likely format it as multi-line (as shown). If ruff formats differently, accept its choice.

### Step 3: Run the new test, verify PASS

```bash
just test -- 'tests/test_faststream_bootstrap.py::test_faststream_health_check_uses_configured_broker_timeout' -v
```

Expected: PASS.

### Step 4: Run the full FastStream test file

```bash
just test -- tests/test_faststream_bootstrap.py -v
```

Expected: all tests PASS. Watch the existing `test_faststream_bootstrap` (which exercises the health check via a real broker connection) — the default `5.0` is identical to the prior hardcoded `5`, so behavior should be unchanged.

### Step 5: Run the full test suite

```bash
just test
```

Expected: 129/129 (128 prior + 1 new).

### Step 6: Run lint

```bash
just lint
```

Expected: clean. The new field's `: float = 5.0` annotation should not trigger any ruff complaints; the test's `expected_timeout = 12.5` named-local pattern avoids PLR2004.

### Step 7: Commit

Stage the two modified files explicitly:

```bash
git add \
  lite_bootstrap/bootstrappers/faststream_bootstrapper.py \
  tests/test_faststream_bootstrap.py
git commit -m "$(cat <<'EOF'
feat: configurable broker ping timeout for FastStream health check

FastStreamHealthChecksInstrument._define_health_status called
broker.ping(timeout=5) with a hardcoded 5-second timeout. For users
with slow brokers (large Redis clusters under load, message queues
with cold connections), this is a footgun.

Add faststream_health_check_broker_timeout: float = 5.0 to
FastStreamConfig. Default preserves the existing behavior; users can
now override.

The field lives on FastStreamConfig (not the shared HealthChecksConfig)
because the timeout is FastStream-shaped — it's specifically about a
message broker ping, not a generic concern that FastAPI/Litestar
health checks would share.

Regression test patches broker.ping to assert the configured timeout
value reaches it.

Closes REF-7 from the audit.
EOF
)"
```

---

## Task 4: Push and open PR

- [ ] **Step 1: Push the branch**

```bash
git push -u origin fix/ref-7-faststream-timeout
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --title "feat: configurable broker ping timeout for FastStream health check" --body "$(cat <<'EOF'
## Summary
- Added `faststream_health_check_broker_timeout: float = 5.0` to `FastStreamConfig`.
- `FastStreamHealthChecksInstrument._define_health_status` now reads from the config instead of the previously hardcoded `timeout=5`.
- New regression test patches `broker.ping` and asserts the configured value reaches it.

Default preserves existing behavior — pure-additive config option. Users with slow brokers can now bump the timeout without forking the library.

Closes REF-7 from an internal audit.

## Test plan
- [x] `just test -- 'tests/test_faststream_bootstrap.py::test_faststream_health_check_uses_configured_broker_timeout' -v` — pass.
- [x] `just test` — 129/129.
- [x] `just lint` — clean.
- [ ] Reviewer: confirm the field lives on `FastStreamConfig` (not `HealthChecksConfig`) — this was the locked decision in the sequencing spec because the timeout is FastStream-shaped.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review

**Spec coverage check** against the sequencing spec (PR14 section) and audit (REF-7):

| Spec item | Task |
|-----------|------|
| Add `faststream_health_check_broker_timeout: float = 5.0` to `FastStreamConfig` | Task 3, Step 1 |
| Update `_define_health_status` to use the field instead of hardcoded `5` | Task 3, Step 2 |
| Add a regression test asserting the configured timeout reaches `broker.ping` | Task 2, Step 2 |
| Field on `FastStreamConfig`, NOT `HealthChecksConfig` (locked decision Q5) | Task 3, Step 1 |
| Branch name `fix/ref-7-faststream-timeout` | Task 1, Step 1 |
| Verification: `just test` + `just lint` clean | Task 3, Steps 5-6 |
| `expected_timeout = 12.5` named local (no PLR2004 noqa) | Task 2, Step 2 |

All spec items covered. No placeholders. Risk: low — additive change with a backward-compatible default.


---

# PR15: Naming Pass — `Opentelemetry`→`OpenTelemetry` + `FreeBootstrapperConfig`→`FreeConfig`

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The final PR of the deferred-refactors sequence. Two API-surface renames with silent backward-compatibility aliases.

- **Bonus (Otel capitalization)**: `OpentelemetryConfig` → `OpenTelemetryConfig` to match `OpenTelemetryServiceFieldsConfig` (introduced in PR6) and conventional OpenTelemetry capitalization.
- **LOW-7**: `FreeBootstrapperConfig` → `FreeConfig` for consistency with sibling configs (`FastAPIConfig`, `LitestarConfig`, `FastStreamConfig` — none carry the `Bootstrapper` infix).

Backward compat: silent aliases (`OpentelemetryConfig = OpenTelemetryConfig`, `FreeBootstrapperConfig = FreeConfig`) at module level plus a `FreeBootstrapperConfig` re-export in `lite_bootstrap/__init__.py`. Existing user code that imports the old names continues to work unchanged.

**Architecture:** Mechanical renames across 11 files (7 production + 4 test). The aliases are simple assignments — same class object, so `isinstance(x, OldName)` and `isinstance(x, NewName)` are interchangeable.

**Tech Stack:** Python 3.10+ dataclasses, module-level aliases.

**Parent spec:** `docs/superpowers/specs/2026-06-01-deferred-refactors-sequencing.md` (PR15 section).
**Parent audit:** `docs/superpowers/specs/2026-05-31-bug-refactor-audit.md` (LOW-7).

---

## File Structure

11 files modified, no new files.

**Production (7 files):**
- `lite_bootstrap/instruments/opentelemetry_instrument.py` — rename `OpentelemetryConfig` → `OpenTelemetryConfig`; add silent alias.
- `lite_bootstrap/bootstrappers/free_bootstrapper.py` — rename `FreeBootstrapperConfig` → `FreeConfig`; add silent alias; update internal references.
- `lite_bootstrap/bootstrappers/fastapi_bootstrapper.py` — update import and inheritance to `OpenTelemetryConfig`.
- `lite_bootstrap/bootstrappers/litestar_bootstrapper.py` — same.
- `lite_bootstrap/bootstrappers/faststream_bootstrapper.py` — same.
- `lite_bootstrap/__init__.py` — export both `FreeConfig` (canonical) and `FreeBootstrapperConfig` (alias) in `__all__`.

**Tests (4 files):**
- `tests/test_free_bootstrap.py` — update internal usages to `FreeConfig`.
- `tests/instruments/test_opentelemetry_instrument.py` — update usages to `OpenTelemetryConfig`.
- `tests/instruments/test_logging_instrument.py` — update usages to `OpenTelemetryConfig`.
- `tests/instruments/test_pyroscope_instrument.py` — update usages to `FreeConfig`.

---

## Locked decisions (from sequencing spec, Q2 + Q7)

- **Silent aliases** (no warn-on-access). Library is small; warn-on-access is overkill for two renames.
- **Both names in `__init__.py`** for `FreeBootstrapperConfig`/`FreeConfig`. `OpentelemetryConfig` is not in `__init__.py` today, so the module-level alias suffices.
- **Update internal references and tests to the new names.** Aliases serve external users, not internal code. Aliases also exercise the new public API via tests.
- **Alias is a class assignment, not a subclass:** `OpentelemetryConfig = OpenTelemetryConfig` — same class object. `isinstance(x, OpentelemetryConfig) is isinstance(x, OpenTelemetryConfig)`. No `__init_subclass__` surprises, no MRO churn.

---

## Cross-cutting concerns

1. **Pickling.** Class identity is preserved by the alias (same object). New pickles use `OpenTelemetryConfig.__qualname__`. Old pickles (made before the rename, containing `OpentelemetryConfig` in their serialized form) still unpickle because the alias keeps the name resolvable in the module namespace. No data migration needed.

2. **Import ordering.** The alias line MUST come AFTER the class definition. Standard Python — but easy to get wrong if reordering imports.

3. **No PLR2004 noqa.** No new magic-value assertions in this PR.

---

## Task 1: Create branch

**Files:** (no files; git only)

- [ ] **Step 1: Branch off `main`**

```bash
git checkout main
git pull --ff-only origin main
git checkout -b refactor/low-7-naming
```

Expected: `Switched to a new branch 'refactor/low-7-naming'`.

---

## Task 2: Rename `OpentelemetryConfig` → `OpenTelemetryConfig`

### Step 1: Rename in `lite_bootstrap/instruments/opentelemetry_instrument.py`

Locate the class definition (after `OpenTelemetryServiceFieldsConfig` from PR6):

```python
@dataclasses.dataclass(kw_only=True, frozen=True)
class OpentelemetryConfig(OpenTelemetryServiceFieldsConfig):
    ...
```

Change `class OpentelemetryConfig` → `class OpenTelemetryConfig`.

Locate `OpenTelemetryInstrument`'s generic parameter:

```python
class OpenTelemetryInstrument(BaseInstrument[OpentelemetryConfig]):
```

Change to `BaseInstrument[OpenTelemetryConfig]`.

Locate any other reference to `OpentelemetryConfig` in the file (e.g., field type annotations, function signatures) — there shouldn't be many; the symbol mostly appears in the class definition and the instrument generic.

**Add the alias at the very end of the file**, after all class declarations:

```python
# Backward-compatible alias preserved for users importing the old (lowercase t) spelling.
OpentelemetryConfig = OpenTelemetryConfig
```

### Step 2: Update inheritance + imports in three framework bootstrappers

**File:** `lite_bootstrap/bootstrappers/fastapi_bootstrapper.py`

Locate the import line:

```python
from lite_bootstrap.instruments.opentelemetry_instrument import OpentelemetryConfig, OpenTelemetryInstrument
```

Change `OpentelemetryConfig` → `OpenTelemetryConfig`.

Locate `FastAPIConfig`'s inheritance:

```python
class FastAPIConfig(
    CorsConfig,
    HealthChecksConfig,
    LoggingConfig,
    OpentelemetryConfig,    # ← change to OpenTelemetryConfig
    ...
```

Change `OpentelemetryConfig` → `OpenTelemetryConfig`.

**File:** `lite_bootstrap/bootstrappers/litestar_bootstrapper.py` — same two changes.

**File:** `lite_bootstrap/bootstrappers/faststream_bootstrapper.py` — same two changes.

### Step 3: Update tests

**Files:** `tests/instruments/test_opentelemetry_instrument.py`, `tests/instruments/test_logging_instrument.py`

In each test file, change every `OpentelemetryConfig` reference (in imports and constructor calls) to `OpenTelemetryConfig`. Use Edit's `replace_all=true` for safety:

```python
# Before:
from lite_bootstrap.instruments.opentelemetry_instrument import OpentelemetryConfig, ...

# After:
from lite_bootstrap.instruments.opentelemetry_instrument import OpenTelemetryConfig, ...
```

And similarly for constructor calls like `OpentelemetryConfig(...)` → `OpenTelemetryConfig(...)`.

### Step 4: Smoke test after the Otel rename

```bash
just test -- tests/instruments/test_opentelemetry_instrument.py tests/instruments/test_logging_instrument.py -v
```

Expected: all PASS. If anything fails with `NameError`, check that all references were updated.

---

## Task 3: Rename `FreeBootstrapperConfig` → `FreeConfig`

### Step 1: Rename in `lite_bootstrap/bootstrappers/free_bootstrapper.py`

Current class:

```python
@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class FreeBootstrapperConfig(LoggingConfig, OpentelemetryConfig, PyroscopeConfig, SentryConfig): ...
```

Two changes here:
1. Rename to `class FreeConfig(LoggingConfig, OpenTelemetryConfig, PyroscopeConfig, SentryConfig): ...` (also picks up the Otel rename from Task 2).
2. Update the bootstrapper:

```python
class FreeBootstrapper(BaseBootstrapper[None]):
    ...
    instruments_types: typing.ClassVar = [...]
    bootstrap_config: FreeBootstrapperConfig    # ← change to FreeConfig
    not_ready_message = ""
    ...
    def __init__(self, bootstrap_config: FreeBootstrapperConfig) -> None:    # ← change to FreeConfig
        super().__init__(bootstrap_config)
```

Replace both `FreeBootstrapperConfig` occurrences with `FreeConfig`.

**Add the alias at the end of the file:**

```python
# Backward-compatible alias preserved for users importing the old name.
FreeBootstrapperConfig = FreeConfig
```

### Step 2: Update `lite_bootstrap/__init__.py`

Current:

```python
from lite_bootstrap.bootstrappers.free_bootstrapper import FreeBootstrapper, FreeBootstrapperConfig
...
__all__ = [
    ...
    "FreeBootstrapper",
    "FreeBootstrapperConfig",
    ...
]
```

Change to:

```python
from lite_bootstrap.bootstrappers.free_bootstrapper import FreeBootstrapper, FreeBootstrapperConfig, FreeConfig
...
__all__ = [
    ...
    "FreeBootstrapper",
    "FreeBootstrapperConfig",
    "FreeConfig",
    ...
]
```

Both names exported. Alphabetical order in `__all__` keeps `FreeBootstrapperConfig` before `FreeConfig`. Add `FreeConfig` after `FreeBootstrapperConfig`.

### Step 3: Update tests

**File:** `tests/test_free_bootstrap.py`

Change every `FreeBootstrapperConfig` → `FreeConfig` (in imports, fixture annotations, constructor calls). Use Edit's `replace_all=true`.

**File:** `tests/instruments/test_pyroscope_instrument.py`

The pyroscope tests use `FreeBootstrapperConfig` to exercise the inheritance-through-Free path. Change references to `FreeConfig`.

### Step 4: Smoke test after the Free rename

```bash
just test -- tests/test_free_bootstrap.py tests/instruments/test_pyroscope_instrument.py -v
```

Expected: all PASS.

---

## Task 4: Verify everything, commit

### Step 1: Run the full test suite

```bash
just test
```

Expected: 129/129 PASS. No behavior change; just symbol renames.

### Step 2: Verify the aliases work for external imports

```bash
uv run python -c "from lite_bootstrap import FreeBootstrapperConfig, FreeConfig; assert FreeBootstrapperConfig is FreeConfig; print('FreeConfig alias OK')"
uv run python -c "from lite_bootstrap.instruments.opentelemetry_instrument import OpentelemetryConfig, OpenTelemetryConfig; assert OpentelemetryConfig is OpenTelemetryConfig; print('OpenTelemetryConfig alias OK')"
```

Both should print `... OK`. If either fails, the alias is broken.

### Step 3: Run lint

```bash
just lint
```

Expected: clean. Watch for:
- `ruff format` may reorder imports — accept its formatting.
- `ty` should be happy with both names since they're the same class.

### Step 4: Sanity grep — verify no leftover old-name references in internal code

```bash
grep -rn "OpentelemetryConfig\|FreeBootstrapperConfig" lite_bootstrap/ tests/ --include="*.py" | grep -v "alias\|backward"
```

Expected: ONLY the two alias-definition lines (`OpentelemetryConfig = OpenTelemetryConfig` and `FreeBootstrapperConfig = FreeConfig`) PLUS the `__init__.py` import/export entries (3 matches total for `FreeBootstrapperConfig`: import line, `__all__` entry, alias line; 1 match total for `OpentelemetryConfig`: the alias line).

If any other `*.py` file has a reference to the old names outside these alias contexts, that's a missed update — fix it.

### Step 5: Commit

Stage all 11 files explicitly:

```bash
git add \
  lite_bootstrap/instruments/opentelemetry_instrument.py \
  lite_bootstrap/bootstrappers/free_bootstrapper.py \
  lite_bootstrap/bootstrappers/fastapi_bootstrapper.py \
  lite_bootstrap/bootstrappers/litestar_bootstrapper.py \
  lite_bootstrap/bootstrappers/faststream_bootstrapper.py \
  lite_bootstrap/__init__.py \
  tests/test_free_bootstrap.py \
  tests/instruments/test_opentelemetry_instrument.py \
  tests/instruments/test_logging_instrument.py \
  tests/instruments/test_pyroscope_instrument.py
git commit -m "$(cat <<'EOF'
refactor: rename OpentelemetryConfig → OpenTelemetryConfig; FreeBootstrapperConfig → FreeConfig

Two API-surface renames with silent backward-compatibility aliases.

OpentelemetryConfig → OpenTelemetryConfig: matches the conventional
OpenTelemetry capitalization and the OpenTelemetryServiceFieldsConfig
mixin introduced in PR6. Module-level alias `OpentelemetryConfig =
OpenTelemetryConfig` preserves existing imports. Not exported from
__init__.py (wasn't before either).

FreeBootstrapperConfig → FreeConfig: matches the sibling configs
(FastAPIConfig, LitestarConfig, FastStreamConfig — none carry the
"Bootstrapper" infix). Module-level alias plus `FreeBootstrapperConfig`
re-export in __init__.py preserves existing public imports.

Internal references and tests updated to the new canonical names.
Aliases are simple class assignments — same class object, so
isinstance(x, OldName) and isinstance(x, NewName) are interchangeable.
Old pickles continue to unpickle via the alias.

No behavior change. 129/129 tests pass.

Closes LOW-7 from the audit. Also closes the bonus Otel capitalization
item surfaced during PR6's code review.
EOF
)"
```

---

## Task 5: Push and open PR

- [ ] **Step 1: Push the branch**

```bash
git push -u origin refactor/low-7-naming
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --title "refactor: rename OpentelemetryConfig → OpenTelemetryConfig; FreeBootstrapperConfig → FreeConfig" --body "$(cat <<'EOF'
## Summary
The final PR of the deferred-refactors sequence. Two API-surface renames with silent backward-compatibility aliases:

- **`OpentelemetryConfig` → `OpenTelemetryConfig`** — matches the conventional OpenTelemetry capitalization and the `OpenTelemetryServiceFieldsConfig` mixin from PR6. Module-level alias preserves existing imports. Not exported from `__init__.py` (wasn't before).
- **`FreeBootstrapperConfig` → `FreeConfig`** — matches the sibling configs (`FastAPIConfig`, `LitestarConfig`, `FastStreamConfig` — none carry the `Bootstrapper` infix). Module-level alias plus `FreeBootstrapperConfig` re-export in `__init__.py` preserves existing public imports.

Internal references and tests updated to the new canonical names. Aliases are simple class assignments — same class object, so `isinstance(x, OldName)` and `isinstance(x, NewName)` are interchangeable. Old pickles continue to unpickle via the alias.

No behavior change. 129/129 tests pass.

Closes LOW-7 from an internal audit. Also closes the bonus Otel capitalization item surfaced during PR6's code review.

## Test plan
- [x] `just test` — 129/129.
- [x] `just lint` — clean.
- [x] Aliases verified working (`isinstance(x, OldName) is isinstance(x, NewName)` for both renames).
- [ ] Reviewer: confirm the aliases are simple class assignments (not subclasses), so isinstance behavior is fully preserved.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review

**Spec coverage check** against the sequencing spec (PR15 section) and audit (LOW-7):

| Spec item | Task |
|-----------|------|
| Rename `OpentelemetryConfig` → `OpenTelemetryConfig` | Task 2, Step 1 |
| Add silent alias `OpentelemetryConfig = OpenTelemetryConfig` | Task 2, Step 1 |
| Rename `FreeBootstrapperConfig` → `FreeConfig` | Task 3, Step 1 |
| Add silent alias `FreeBootstrapperConfig = FreeConfig` | Task 3, Step 1 |
| Export both names from `__init__.py` | Task 3, Step 2 |
| Update internal references in framework bootstrappers | Task 2, Step 2 |
| Update tests to use new canonical names | Tasks 2 Step 3 + 3 Step 3 |
| Verify aliases work (`is` identity) | Task 4, Step 2 |
| Sanity grep for missed references | Task 4, Step 4 |
| Branch name `refactor/low-7-naming` | Task 1, Step 1 |
| Verification: `just test` + `just lint` clean | Task 4, Steps 1, 3 |

All spec items covered. No placeholders.

**Risk:** Low. Aliases preserve every existing import. The mechanical rename is well-scoped (11 files, predictable changes). The sanity grep at Task 4 Step 4 catches any miss.

**Why this is the last PR:** With this merged, all 8 deferred-refactor PRs (PR8-15) close every audit finding except those explicitly marked out-of-scope in the sequencing spec. The audit becomes fully resolved.


---

# PR16: Post-Retro Hygiene (uv_build upper bound + Pyroscope endpoint assert)

**Goal:** Two small hygiene items surfaced during retrospective action-item work.

**Files:**
- `pyproject.toml` — add upper bound to `uv_build` to silence the every-`just lint` warning
- `lite_bootstrap/instruments/pyroscope_instrument.py` — add a runtime assert on `pyroscope_endpoint` to document the `is_ready()`-enforced invariant

**Parent docs:** Surfaced in the [audit retrospective](../../retros/2026-06-01-audit-implementation-retro.md). Neither is an audit finding; both noticed during the retro action-item work (`just lint` warning persistence + Pyright's `reportArgumentType` on pyroscope's `server_address`).

This is the first PR using the [lightweight plan template](../templates/lightweight-plan-template.md). Eat your own dog food.

---

## Diff

### `pyproject.toml`

```python
# Before:
[build-system]
requires = ["uv_build"]
build-backend = "uv_build"

# After:
[build-system]
requires = ["uv_build<0.12"]
build-backend = "uv_build"
```

The upper bound aligns with the warning's own suggestion (`Without bounding the uv_build version, the source distribution will break when a future, breaking version of uv_build is released. ...such as <0.12`). Pinning to <0.12 matches the major version we're on; the next breaking change is the next major.

### `lite_bootstrap/instruments/pyroscope_instrument.py`

In `PyroscopeInstrument.bootstrap()`, add an assert at the top documenting the precondition that `is_ready()` enforces:

```python
# Before:
def bootstrap(self) -> None:
    namespace = self.bootstrap_config.opentelemetry_namespace
    tags = ({"service_namespace": namespace} if namespace else {}) | self.bootstrap_config.pyroscope_tags
    pyroscope.configure(
        application_name=self.bootstrap_config.opentelemetry_service_name or self.bootstrap_config.service_name,
        server_address=self.bootstrap_config.pyroscope_endpoint,
        sample_rate=self.bootstrap_config.pyroscope_sample_rate,
        tags=tags,
        **self.bootstrap_config.pyroscope_additional_params,
    )

# After:
def bootstrap(self) -> None:
    # is_ready() guarantees pyroscope_endpoint is set; assert documents the precondition
    # for type narrowing and for direct callers that bypass the bootstrapper.
    assert self.bootstrap_config.pyroscope_endpoint is not None
    namespace = self.bootstrap_config.opentelemetry_namespace
    tags = ({"service_namespace": namespace} if namespace else {}) | self.bootstrap_config.pyroscope_tags
    pyroscope.configure(
        application_name=self.bootstrap_config.opentelemetry_service_name or self.bootstrap_config.service_name,
        server_address=self.bootstrap_config.pyroscope_endpoint,
        sample_rate=self.bootstrap_config.pyroscope_sample_rate,
        tags=tags,
        **self.bootstrap_config.pyroscope_additional_params,
    )
```

Why an assert (not a cast):
- The invariant is real: `is_ready()` returns `bool(self.bootstrap_config.pyroscope_endpoint)`, and `BaseBootstrapper._register_or_skip` doesn't call `bootstrap()` if `is_ready()` returned False.
- `assert` runs at runtime and catches direct-bypass callers (e.g., `PyroscopeInstrument(config).bootstrap()` without going through a bootstrapper) with a clear `AssertionError` instead of a confusing pyroscope-side TypeError.
- The project allows `assert` (S101 is in ruff ignores).
- `ty` and Pyright both narrow `str | None` → `str` after the assert.

No new test. The existing `test_pyroscope_instrument_bootstrap_and_teardown` covers the bootstrap path.

---

## Verification

1. `grep -n "uv_build" pyproject.toml` — confirm exactly one match, with `<0.12`.
2. `just lint` — the "missing upper bound on uv_build" warning should be gone. Lint stays clean otherwise.
3. `just test -- tests/instruments/test_pyroscope_instrument.py -v` — all pyroscope tests pass (the existing bootstrap test exercises the new assert path).
4. `just test` — full suite 129/129.

### Pre-flight grep (template requirement)

```bash
grep -rn "uv_build" pyproject.toml
grep -rn "self\.bootstrap_config\.pyroscope_endpoint" lite_bootstrap/instruments/pyroscope_instrument.py
```

Expected:
- `pyproject.toml` shows 2 matches (the `requires` line and `build-backend` line) — only the first changes.
- `pyroscope_instrument.py` shows 2 matches (the `is_ready` check at line ~28 and the `server_address` reference at line ~39); the assert addition is between them.

## Commit

```bash
git add pyproject.toml lite_bootstrap/instruments/pyroscope_instrument.py
git commit -m "$(cat <<'EOF'
chore: pin uv_build upper bound; assert pyroscope_endpoint precondition

uv_build: silence the `just lint` warning about missing upper bound by
pinning to <0.12 (matches the warning's own suggestion).

Pyroscope: add `assert self.bootstrap_config.pyroscope_endpoint is not None`
at the top of bootstrap(). This documents the precondition that is_ready()
already enforces and narrows the type for both ty and Pyright (was the
only remaining real Pyright complaint after the post-retro suppressions
landed). Direct callers that bypass the bootstrapper now get a clear
AssertionError instead of a TypeError from pyroscope.

Both items surfaced during retro action-item work. First PR using the
lightweight plan template.
EOF
)"
```

## PR

Branch: `chore/post-retro-hygiene`. Push, open via `gh pr create`. No reviewer asks beyond "diff looks right."
