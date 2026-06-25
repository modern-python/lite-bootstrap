---
summary: Move OTel's own opentelemetry_excluded_urls field onto OpenTelemetryConfig (typed access, one declaration) and pin the genuine prometheus/health cross-config exclusion reads with a regression test.
---

# Design: Move `opentelemetry_excluded_urls` onto its own config; pin the sibling-path exclusions

## Summary

`OpenTelemetryInstrument._build_excluded_urls` reads four config fields by string via
`getattr(..., default)`. One of them — `opentelemetry_excluded_urls` — is OTel's *own*
setting, yet it is declared three times on the framework configs and never on
`OpenTelemetryConfig`, which is *why* OTel must getattr it. This change moves that field
home to `OpenTelemetryConfig` (de-duplicating three declarations into one and making the
read typed), and adds a regression test pinning the *genuine* cross-instrument reads
(`prometheus_metrics_path` / `health_checks_path`) so a future rename breaks loudly
instead of silently dropping URLs from the trace-exclusion set.

## Motivation

`_build_excluded_urls` (`instruments/opentelemetry_instrument.py:144-153`) makes four
stringly-typed cross-config reads:

```python
excluded_urls = set(getattr(self.bootstrap_config, "opentelemetry_excluded_urls", []))   # OTel's OWN field
prometheus_path = getattr(self.bootstrap_config, "prometheus_metrics_path", None)         # PrometheusConfig
if not self.bootstrap_config.opentelemetry_generate_health_check_spans:
    health_path = getattr(self.bootstrap_config, "health_checks_path", None)              # HealthChecksConfig
```

These are two different kinds of read, and conflating them hides the real issue:

- **`opentelemetry_excluded_urls` is OTel's own field, misplaced.** It is declared on
  `FastAPIConfig:53`, `LitestarConfig:120`, and `FastStreamConfig:69` — three identical
  copies — and not on `OpenTelemetryConfig`. The getattr exists only because the field
  isn't where it belongs. The method is defined on the base `OpenTelemetryInstrument`,
  whose `bootstrap_config` is typed `OpenTelemetryConfig`; if the field lived there, the
  read would be typed.
- **`prometheus_metrics_path` / `health_checks_path` are genuinely other instruments'
  fields.** OTel runs in `FreeConfig`, which composes neither Prometheus nor
  HealthChecks, so these fields may legitimately be absent. The defensive
  `getattr(..., None)` is the correct expression of "optional sibling" and should stay.

The risk in the genuine-sibling reads is silent breakage: rename `prometheus_metrics_path`
on `PrometheusConfig` and the getattr returns `None`, the metrics endpoint silently stops
being excluded from traces, and **no test catches it** — the only direct
`_build_excluded_urls` test (`test_faststream_bootstrap.py:225`) covers just the
`opentelemetry_excluded_urls` passthrough. Same shape as the candidate-1 drift bug, lower
impact (extra spans, not lost data). (Surfaced as candidate 4 of the 2026-06-23
architecture review; rated Speculative — this is the proportionate slice of it.)

## Non-goals

- **A "contribution" mechanism** (each instrument/config declares its excluded paths,
  OTel unions them). Rejected: today `_build_excluded_urls` concentrates the entire
  exclusion policy in one readable method (good locality); a contribution mechanism would
  *spread* that policy across `PrometheusConfig`, `HealthChecksConfig`, and OTel, and the
  health-check case still needs OTel's `opentelemetry_generate_health_check_spans` flag,
  so the cross-coupling would not even disappear. It moves complexity and worsens
  locality — fails the deletion test.
- **Removing the genuine-sibling getattrs.** `prometheus_metrics_path` /
  `health_checks_path` / `pyroscope_endpoint` belong to other instruments and are
  optional; the defensive read is correct. We pin them with a test, not a refactor.
- **Touching the `pyroscope_endpoint` getattr (line 174).** It is a span-processor
  decision, not part of `_build_excluded_urls`; same intentional optional-sibling
  pattern, different concern.

## Design

### 1. Move `opentelemetry_excluded_urls` onto `OpenTelemetryConfig`

Add the field to `OpenTelemetryConfig` and delete the three framework-config copies:

```python
# instruments/opentelemetry_instrument.py — OpenTelemetryConfig
opentelemetry_excluded_urls: list[str] = dataclasses.field(default_factory=list)
```

Users still set it exactly as before (`FastAPIConfig(opentelemetry_excluded_urls=[...])`)
— it is inherited. The read in `_build_excluded_urls` becomes typed:

```python
excluded_urls: set[str] = set(self.bootstrap_config.opentelemetry_excluded_urls)
```

The `prometheus_metrics_path` / `health_checks_path` reads stay as `getattr(..., default)`.

### 2. Accepted trade: the field is now inherited by `FreeConfig`

`FreeConfig` composes `OpenTelemetryConfig`, so it gains `opentelemetry_excluded_urls`
(inert there — `_build_excluded_urls` is only called by the HTTP framework OTel
subclasses, never in Free's path). `FastMcpConfig` is unaffected (it composes no OTel
config). `FreeConfig.from_dict({"opentelemetry_excluded_urls": ...})` now accepts the key
instead of filtering it. This cosmetic widening is accepted: Free already inherits other
OTel fields that only matter in some setups, and the field belongs on `OpenTelemetryConfig`.

### 3. Pin the genuine-sibling exclusions with one regression test

One representative test (the method is a single shared base method; the fields live on the
shared `PrometheusConfig` / `HealthChecksConfig`, so a rename breaks every framework at
once — one test suffices). Placed beside the existing `_build_excluded_urls` test in
`test_faststream_bootstrap.py`. It asserts the full policy:

- the prometheus metrics path is **always** in the excluded set;
- the health-checks path **is** excluded when `opentelemetry_generate_health_check_spans=False`;
- the health-checks path **is not** excluded when it is `True`.

A rename of `prometheus_metrics_path` / `health_checks_path`, or a regression in the
conditional, then fails this test loudly.

## Operations

None.

## Out of scope

Covered under Non-goals.

## Testing

- **Existing guard (A):** `test_faststream_opentelemetry_excluded_urls_in_built_set`
  (`test_faststream_bootstrap.py:225`) already pins the `opentelemetry_excluded_urls`
  passthrough and keeps passing after the field moves (it is inherited), so A is a
  refactor under a stable test.
- **New regression (B):** the cross-config exclusion test above.

`just test` green at 100%, `just lint-ci` clean (`ty` included).

## Risk

- **Behaviour change from the field move (low likelihood × low impact).** Moving the
  field is additive — every current call site keeps working via inheritance; the only
  observable change is `FreeConfig` accepting a previously-rejected key. Mitigation: the
  existing passthrough test guards the read.
- **`from_dict` semantics on Free (low × low).** Free now accepts `opentelemetry_excluded_urls`
  in `from_dict`/`from_object`. Accepted per design §2.
- **Residual silent-rename on `pyroscope_endpoint` (low × low).** Out of scope; it is not
  part of `_build_excluded_urls`. Noted so a future pass knows it was deliberately left.
