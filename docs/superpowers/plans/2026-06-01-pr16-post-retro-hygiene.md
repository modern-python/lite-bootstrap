# PR16: Post-Retro Hygiene (uv_build upper bound + Pyroscope endpoint assert)

**Goal:** Two small hygiene items surfaced during retrospective action-item work.

**Files:**
- `pyproject.toml` — add upper bound to `uv_build` to silence the every-`just lint` warning
- `lite_bootstrap/instruments/pyroscope_instrument.py` — add a runtime assert on `pyroscope_endpoint` to document the `is_ready()`-enforced invariant

**Parent docs:** Surfaced in the [audit retrospective](../specs/2026-06-01-audit-implementation-retro.md). Neither is an audit finding; both noticed during the retro action-item work (`just lint` warning persistence + Pyright's `reportArgumentType` on pyroscope's `server_address`).

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
