# Bug Audit v2 — Implementation Sequencing

**Date:** 2026-06-05
**Parent spec:** [2026-06-05-bug-audit-v2.md](2026-06-05-bug-audit-v2.md)
**Scope:** All 26 new findings from the audit (5 UX · 9 logic · 5 security · 7 tests).
TEST-NEW-* items fold into their parent code-fix PR rather than getting their own.
**Deliverable:** 3 sequenced PRs grouped by theme. Sequencing rationale, per-PR scope,
locked decisions.

This is a coarser-grained sequencing than the prior 2026-05-31 plan (which used 7 PRs
for criticals). The audit has no CRIT items, so the work bundles cleanly into three
themed PRs without sacrificing reviewability.

---

## Sequencing rationale

Group by what a reviewer needs to hold in their head while reading the diff:

1. **PR1 — Internal lifecycle (teardown + invariants).** The reviewer is auditing
   `bootstrap → teardown` symmetry across instruments. One mental model.
2. **PR2 — External API surface (config UX + validation).** The reviewer is checking
   what the library exposes to users and how it validates inputs. Different mental
   model.
3. **PR3 — Hygiene (docs, warnings, CI).** Pure chore, no code paths to reason about.

Order is by review-fatigue: largest mental load first while reviewers are fresh,
chore last.

| # | PR | Findings | Risk | Diff size |
|---|-----|----------|------|-----------|
| 1 | Lifecycle & teardown correctness | LOG-1..9, SEC-4, TEST-NEW-2..5 | Medium | Medium |
| 2 | Config UX & security validation | UX-1, UX-2, UX-3, SEC-1, SEC-2, SEC-3, TEST-NEW-1, TEST-NEW-6 | Low–Medium | Medium |
| 3 | Hygiene + CI gate | UX-4, UX-5, SEC-5, TEST-NEW-7 | Very low | Tiny |

PR1 lands first because the re-bootstrap safety fix (LOG-7/LOG-8) interacts with the
OTel teardown fix (LOG-1) — easier to integrate them together than across PRs. PR2 and
PR3 are independent of PR1 and of each other; they can land in any order after PR1
(or in parallel branches).

Branch naming: `fix/bug-audit-v2-pr<N>-<slug>` to match the prior `2026-05-31-pr<N>-...`
convention used for the previous audit.

---

## PR1: Lifecycle & teardown correctness

**Branch:** `fix/bug-audit-v2-pr1-lifecycle`
**Findings:** LOG-1, LOG-2, LOG-3, LOG-4, LOG-5, LOG-6, LOG-7, LOG-8, LOG-9, SEC-4,
TEST-NEW-2, TEST-NEW-3, TEST-NEW-4, TEST-NEW-5

### Scope

Every fix in this PR is "bootstrap promised, teardown didn't deliver" or
"bootstrap-with-app-reuse breaks invariants". Bundled because:

- They share files (3 of the 6 instruments, 3 of the 4 bootstrappers).
- They share testing approach (drive lifecycle, snapshot global/instance state,
  assert restoration).
- The re-bootstrap fixes (LOG-7/LOG-8) need the OTel teardown reset (LOG-1) to be
  reliable; bundling avoids a phantom intermediate state on `main`.

#### Sub-section A — Type-narrowing invariants (LOG-5 / SEC-4)

Replace `assert`-based type narrowing with explicit raises so checks survive `python -O`:

- `lite_bootstrap/bootstrappers/fastapi_bootstrapper.py:78-80` (`_narrow_app`):

  ```python
  def _narrow_app(config: "FastAPIConfig") -> "fastapi.FastAPI":
      if isinstance(config.application, UnsetType):
          msg = "FastAPIConfig.application is UNSET; __post_init__ did not run"
          raise RuntimeError(msg)
      return config.application
  ```

- `lite_bootstrap/instruments/pyroscope_instrument.py:35-37` (precondition in
  `bootstrap()`): same shape — `if endpoint is None: raise RuntimeError(...)`.

Both bandit B101 findings disappear.

#### Sub-section B — OTel teardown completeness (LOG-1 / LOG-2)

In `lite_bootstrap/instruments/opentelemetry_instrument.py`:

- LOG-1: import `NoOpTracerProvider` from `opentelemetry.trace`. In `teardown()` after
  `self._tracer_provider.shutdown()` (lines 152-156), call
  `set_tracer_provider(NoOpTracerProvider())` to swap the global back.
- LOG-2: in `__post_init__` (or as a `dataclasses.field(init=False, default_factory=dict, ...)`),
  declare `_prior_logger_states: dict[str, bool]`. In `bootstrap()` (lines 107-109),
  capture the previous `disabled` value for each logger before mutating. In
  `teardown()`, restore.

#### Sub-section C — Teardown robustness (LOG-3 / LOG-4 / LOG-9)

- LOG-3 — `lite_bootstrap/instruments/logging_instrument.py:168-178`: wrap the
  root-handler loop and level reset in `try/finally` so
  `self._logger_factory.close_handlers()` always runs. Aggregate `h.close()` exceptions
  into a list; after the loop, raise a `TeardownError`-style aggregate if non-empty.
  Pattern matches `BaseBootstrapper.teardown` (`bootstrappers/base.py:96-105`).
- LOG-4 — `lite_bootstrap/bootstrappers/faststream_bootstrapper.py:110-120`: snapshot
  `broker.config.logger.params_storage` into an `init=False` field before mutating in
  `bootstrap()`. Add a `teardown()` override that restores it before
  `super().teardown()`.
- LOG-9 — `lite_bootstrap/instruments/sentry_instrument.py:94-125`: add `teardown()`
  that calls `sentry_sdk.flush(timeout=2)` and `sentry_sdk.init()` (no args) inside a
  `import_checker.is_sentry_installed` guard. Drop the `finally: sentry_sdk.init()`
  workarounds in `tests/instruments/test_sentry_instrument.py:43, 65` as part of this PR.

#### Sub-section D — App-reuse safety (LOG-6 / LOG-7 / LOG-8)

- LOG-6 — `lite_bootstrap/bootstrappers/litestar_bootstrapper.py:75-99`: replace
  `dict[int, ASGIApp]` with `weakref.WeakValueDictionary` so GC'd `next_app`s evict.
- LOG-7 — `lite_bootstrap/bootstrappers/fastmcp_bootstrapper.py:152-154`: before
  `application.add_provider(_TeardownProvider(...))`, check `application.providers`
  for an existing `_TeardownProvider`. If present, emit
  `warnings.warn("FastMCP application already has a _TeardownProvider; skipping re-attachment", stacklevel=2)`
  and return.
- LOG-8 — `lite_bootstrap/bootstrappers/fastapi_bootstrapper.py:197-205`: store a
  sentinel on `application.state.lite_bootstrap_lifespan_attached = True` after
  wrapping. If already True on entry, warn-and-skip the wrap.

### Tests

- TEST-NEW-2 — `tests/instruments/test_opentelemetry_instrument.py`:
  - `test_teardown_resets_global_tracer_provider_to_noop`: bootstrap, teardown, assert
    `trace.get_tracer_provider()` is a `NoOpTracerProvider`.
  - `test_teardown_restores_disabled_loggers`: set `disabled = False` pre-bootstrap,
    run lifecycle, assert restoration.
- TEST-NEW-3 — `tests/instruments/test_logging_instrument.py`:
  - `test_teardown_aggregates_handler_close_errors`: patch a root handler's `close`
    to raise; assert factory is nulled, level is reset, exception is re-raised.
- TEST-NEW-4 — `tests/test_faststream_bootstrap.py`:
  - `test_teardown_restores_broker_params_storage`: snapshot, lifecycle, assert
    restoration.
- TEST-NEW-5 — multi-file:
  - `test_fastapi_bootstrap.py::test_second_bootstrapper_on_same_app_warns_not_stacks`
  - `test_fastmcp_bootstrap.py::test_second_bootstrapper_on_same_app_warns_not_stacks`
  - `test_litestar_bootstrap.py::test_otel_apps_cache_evicts_dead_refs`
- Add `test_pyroscope_instrument.py::test_bootstrap_raises_when_endpoint_unset_at_call_time`
  and `test_fastapi_bootstrap.py::test_narrow_app_raises_when_application_unset` for LOG-5.
- Drop `sentry_sdk.init()` workarounds in `test_sentry_instrument.py` per LOG-9.
- Add `test_sentry_instrument.py::test_sentry_teardown_resets_sdk_to_noop`.

### Decisions (locked)

| Decision | Choice |
|----------|--------|
| Type narrowing | Explicit `raise RuntimeError(msg)`; drop asserts |
| Tracer reset | `set_tracer_provider(NoOpTracerProvider())` after `shutdown()` |
| OTel loggers | Capture-and-restore; don't drop the silencing |
| Teardown errors | Aggregate-and-raise (matches `TeardownError`) |
| OTel cache | `weakref.WeakValueDictionary` |
| Re-attach behavior | Warn + skip (idempotent); never raise |

### Files

Source:
- `lite_bootstrap/bootstrappers/fastapi_bootstrapper.py`
- `lite_bootstrap/bootstrappers/fastmcp_bootstrapper.py`
- `lite_bootstrap/bootstrappers/faststream_bootstrapper.py`
- `lite_bootstrap/bootstrappers/litestar_bootstrapper.py`
- `lite_bootstrap/instruments/logging_instrument.py`
- `lite_bootstrap/instruments/opentelemetry_instrument.py`
- `lite_bootstrap/instruments/pyroscope_instrument.py`
- `lite_bootstrap/instruments/sentry_instrument.py`

Tests:
- `tests/test_fastapi_bootstrap.py`
- `tests/test_fastmcp_bootstrap.py`
- `tests/test_faststream_bootstrap.py`
- `tests/test_litestar_bootstrap.py`
- `tests/instruments/test_logging_instrument.py`
- `tests/instruments/test_opentelemetry_instrument.py`
- `tests/instruments/test_pyroscope_instrument.py`
- `tests/instruments/test_sentry_instrument.py`

### Risk

Medium. Largest single PR in this plan. Touches 8 source files, 8 test files. The
mitigations are clear scope (one theme: lifecycle), comprehensive tests for each fix,
and existing teardown-error machinery to lean on. PR2 and PR3 stay decoupled, so a
revert of PR1 doesn't block them.

---

## PR2: Config UX & security validation

**Branch:** `fix/bug-audit-v2-pr2-config-security`
**Findings:** UX-1, UX-2, UX-3, SEC-1, SEC-2, SEC-3, TEST-NEW-1, TEST-NEW-6

### Scope

Every fix in this PR is "the user-facing config doesn't behave the way the docs
imply" or "config validation should reject unsafe combinations". Bundled because:

- All edits hit config classes and their validation paths.
- All new tests assert config-level behavior, not lifecycle behavior.
- Reviewer mental model: "what happens at `Config(...)` construction time".

#### Sub-section A — User-app preservation (UX-1)

`lite_bootstrap/bootstrappers/fastapi_bootstrapper.py:58-75` — move the
`application.title/.debug/.version = ...` assignments **inside** the UnsetType branch:

```python
def __post_init__(self) -> None:
    if not import_checker.is_fastapi_installed:
        msg = "fastapi is not installed"
        raise ConfigurationError(msg)

    if isinstance(self.application, UnsetType):
        application = fastapi.FastAPI(docs_url=self.swagger_path, **self.application_kwargs)
        object.__setattr__(self, "application", application)
        application.title = self.service_name
        application.debug = self.service_debug
        application.version = self.service_version
    elif self.application_kwargs:
        warnings.warn("application_kwargs must be used without application", stacklevel=2)
```

#### Sub-section B — FastStream config gaps (UX-2 / UX-3)

`lite_bootstrap/bootstrappers/faststream_bootstrapper.py:63-72`:

- UX-2: add `prometheus_collector_registry: "prometheus_client.CollectorRegistry | None" = None`
  (typed under `TYPE_CHECKING`). In `FastStreamPrometheusInstrument` (line 143-167), use
  the field if non-None, else the existing per-instance default.
- UX-3: add `opentelemetry_excluded_urls: list[str] = dataclasses.field(default_factory=list)`
  matching `FastAPIConfig:53` and `LitestarConfig:114`. No change to `_build_excluded_urls`;
  the field is now discoverable.

#### Sub-section C — Security hardening (SEC-1 / SEC-2 / SEC-3)

- SEC-1 — `lite_bootstrap/helpers/fastapi_helpers.py:37-59`: validate `root_path` with
  `lite_bootstrap.helpers.path.is_valid_path` before interpolation. If validation fails,
  fall back to `""` and emit `warnings.warn("root_path rejected: ...", stacklevel=2)`.
  Matches the existing path-validation regime for `prometheus_metrics_path` /
  `swagger_path`.
- SEC-2 — `lite_bootstrap/instruments/opentelemetry_instrument.py:bootstrap()`: after
  reading `opentelemetry_endpoint`, parse the host. If `opentelemetry_insecure=True`
  AND the host is not `localhost` / `127.0.0.1` / `::1` AND the URL scheme isn't
  `unix://`, emit `warnings.warn("OTLP exporter sending traces unencrypted to a non-local endpoint", stacklevel=2)`.
- SEC-3 — `lite_bootstrap/instruments/cors_instrument.py`: add `__post_init__` to
  `CorsConfig` that raises `ConfigurationError` when `cors_allowed_credentials is True`
  AND (`cors_allowed_origins == ["*"]` OR `cors_allowed_origin_regex in {".*", r".+"}`).
  Re-export `ConfigurationError` from the cors module if not already importable there.

### Tests

- TEST-NEW-1 — `tests/test_fastapi_bootstrap.py::test_user_supplied_app_keeps_title_version_debug`:
  build a pre-configured `fastapi.FastAPI(title="user", version="9.9.9", debug=False)`,
  pass via `FastAPIConfig(application=user_app, service_name="lite", ...)`, assert
  user's values survive.
- `tests/test_faststream_bootstrap.py::test_prometheus_uses_injected_registry`: register
  a counter on a custom registry, pass via the new field, assert the counter appears
  in `/metrics`.
- `tests/test_faststream_bootstrap.py::test_opentelemetry_excluded_urls_applied`:
  set the field, assert the returned set from `_build_excluded_urls` contains the value.
- TEST-NEW-6 — `tests/instruments/test_cors_instrument.py::test_cors_credentials_with_wildcard_raises`:
  parametrized over wildcard variants; assert `ConfigurationError`.
- `tests/test_fastapi_offline_docs.py::test_root_path_with_malicious_chars_is_rejected`:
  pass `root_path="<script>alert(1)</script>"`, assert HTML response does NOT contain
  the injected literal AND a warning was emitted.
- `tests/instruments/test_opentelemetry_instrument.py::test_warns_on_insecure_non_local_endpoint`:
  bootstrap with a remote endpoint and `opentelemetry_insecure=True`; assert warning.

### Decisions (locked)

| Decision | Choice |
|----------|--------|
| UX-1 strategy | Move override inside UnsetType branch; never stomp user values |
| UX-2 default | Keep per-instance isolated registry; opt-in injection |
| SEC-1 method | Validate via `is_valid_path` (consistent with existing path handling) |
| SEC-2 default | Keep `insecure=True`; warn on non-local endpoint |
| SEC-3 scope | Reject at config construction (not at instrument bootstrap) |

### Files

Source:
- `lite_bootstrap/bootstrappers/fastapi_bootstrapper.py`
- `lite_bootstrap/bootstrappers/faststream_bootstrapper.py`
- `lite_bootstrap/helpers/fastapi_helpers.py`
- `lite_bootstrap/instruments/cors_instrument.py`
- `lite_bootstrap/instruments/opentelemetry_instrument.py`

Tests:
- `tests/test_fastapi_bootstrap.py`
- `tests/test_fastapi_offline_docs.py`
- `tests/test_faststream_bootstrap.py`
- `tests/instruments/test_cors_instrument.py`
- `tests/instruments/test_opentelemetry_instrument.py`

### Risk

Low–Medium. Each change is additive or refactors within a single `__post_init__`. The
CORS validation could surprise existing users with permissive configs — flag in the
release notes.

---

## PR3: Hygiene + CI gate

**Branch:** `chore/bug-audit-v2-pr3-hygiene`
**Findings:** UX-4, UX-5, SEC-5, TEST-NEW-7

### Scope

Pure-chore PR. No production code paths change. Bundled so the hygiene fixes land
together as a single small diff.

#### Sub-section A — Dual-channel skip signal (UX-4)

`lite_bootstrap/bootstrappers/base.py:62-67`: after the existing
`warnings.warn(...)`, add `logger.warning("instrument %s skipped: %s", instrument_type.__name__, instrument_type.missing_dependency_message)`.
Two channels — users who suppress one still see the other.

#### Sub-section B — `from_object` asymmetry doc (UX-5)

`CLAUDE.md` under the "Conventions" section: add a one-paragraph note explaining
that `from_dict` accepts explicit `None` (overrides default) while `from_object`
filters `None` (default wins). Reference the docstrings and tests that pin it.

#### Sub-section C — Escalate warning regressions (TEST-NEW-7)

`pyproject.toml [tool.pytest.ini_options]`: add

```toml
filterwarnings = [
    "error::lite_bootstrap.exceptions.InstrumentSkippedWarning",
]
```

Verify the existing tests still pass — they should because every dependency-missing
test already uses `pytest.warns(...)` to opt in.

#### Sub-section D — CI dependency audit (SEC-5)

`.github/workflows/security-audit.yml` (new file; check that no equivalent step exists
in the current workflows first):

```yaml
name: security-audit
on:
  pull_request:
  schedule:
    - cron: "0 6 * * 1"  # weekly Monday
jobs:
  pip-audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: |
          uv export --all-extras --no-hashes > /tmp/reqs.txt
          uv tool install pip-audit
          pip-audit --no-deps --disable-pip -r /tmp/reqs.txt
```

### Tests

No new tests. TEST-NEW-7 changes pytest config; verification is that the existing
suite still passes (`just test`).

### Decisions (locked)

| Decision | Choice |
|----------|--------|
| UX-4 channels | Both `warnings.warn` AND `logger.warning` |
| SEC-5 tool | `pip-audit` over `safety` (OSV-backed, uv-native) |
| SEC-5 cadence | Per-PR + weekly cron |
| TEST-NEW-7 scope | Escalate only `InstrumentSkippedWarning` subclasses |

### Files

- `lite_bootstrap/bootstrappers/base.py`
- `CLAUDE.md`
- `pyproject.toml`
- `.github/workflows/security-audit.yml`

### Risk

Very low. No production behavior change; CI step is additive. Worst case is the
filterwarnings change surfaces a pre-existing leak in the suite, in which case fix
the leaky test inline.

---

## Branch hygiene & CI

- PR1 lands first; PR2 and PR3 can land in any order after PR1, or in parallel
  branches off `main`.
- Each PR runs `just lint-ci` and `just test` via existing CI.
- PR1 additionally verifies the new tests fail on `main` for the LOG-1..9 cases (each
  test should fail when the fix is reverted — this is the regression proof).
- Squash-merge each PR before the next branches off (matches the project's recent
  pattern of `fix:` / `feat:` / `chore:` prefixes).

---

## Cross-PR locked decisions

| Decision | Choice |
|----------|--------|
| Granularity | 3 PRs by review-mental-model theme |
| Order | Lifecycle first (largest mental load while reviewers are fresh) |
| PR2 / PR3 parallelism | Allowed; both independent of each other and of PR1 |

---

## Deferred (out of scope for this plan)

None. The audit's 26 new findings all map to a PR above.

If even 3 PRs feels too coarse, the [9-PR finer-grained sequencing] can be reconstructed
from the audit by mapping:

- PR1 splits into: assert→raise (1 finding), OTel teardown (2), teardown robustness (3),
  app-reuse safety (3).
- PR2 splits into: FastAPI user app (1), FastStream gaps (2), security hardening (3).
- PR3 splits into: warning visibility (1), from_object docs (1), filterwarnings (1),
  CI gate (1).

The 3-PR grouping is the recommended ship cadence; finer splits are available if review
pressure or hot-fix urgency requires.

If even 3 PRs is too much to commit to right now, the lowest-priority items that could
be deferred without risk:

- LOG-6 (`_otel_apps` memory growth): theoretical for hot-reload setups only.
- LOG-7 / LOG-8 (re-bootstrap stacking): produces extra log lines / stack depth but no
  correctness break thanks to idempotent teardown (CRIT-3 fix).
- UX-5 (`from_object` asymmetry): documentation only.

These three together would shrink PR1 modestly and PR3 marginally, but the savings are
not large enough to justify a fourth split.
