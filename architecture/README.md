# Architecture

The living, code-current truth about **what `lite-bootstrap` does now** — one
file per capability, written as prose and dated by git. This is the truth home:
the present-tense companion to `planning/changes/`, which records *how it got
there*.

## Capabilities

- [`config-model.md`](config-model.md) — frozen `BaseConfig` hierarchy, framework
  configs via multiple inheritance, `from_dict`/`from_object` semantics, the
  `UNSET` sentinel, and the `__post_init__` cascade invariant.
- [`instruments.md`](instruments.md) — `BaseInstrument` lifecycle, the instrument
  catalog, the optional-dependency guard, why instruments are non-frozen, the
  cross-instrument integrations (Logging↔Sentry, OTel↔Logging, Pyroscope↔OTel),
  and OpenTelemetry's single-instance-per-process constraint.
- [`bootstrappers.md`](bootstrappers.md) — the `BaseBootstrapper` hierarchy, skip
  ordering at construction, the instrument registry + idempotent teardown, summary
  logging, the teardown-on-shutdown attach seam, and the `_lite_bootstrap_*`
  app-tagging sentinel convention.

## Promotion rule

When a change alters a capability's behavior, **hand-edit the matching
`architecture/<capability>.md` in the same PR** as the code. That promotion —
reviewed in the same diff, never deferred to a post-merge step — is what keeps
these files true. Code that changes without it silently rots the truth home.
