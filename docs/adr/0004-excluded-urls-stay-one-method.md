# Trace-exclusion policy stays in one method, not contributed per instrument

**Decision:** `_build_excluded_urls` keeps the whole OpenTelemetry URL-exclusion policy in one
method that reads its sibling instruments' paths. We reject a contribution mechanism in which each
instrument or config declares the paths it wants excluded and OpenTelemetry unions them (#132).

The method reads `prometheus_metrics_path` and `health_checks_path` off the config through defensive
`getattr(..., None)`, because a given framework config need not compose `PrometheusConfig` or
`HealthChecksConfig` at all — those are genuinely optional siblings, and the defensive read is the
correct expression of that, not a smell to refactor away.

A contribution mechanism was the obvious alternative and fails the deletion test. Today the entire
exclusion policy is readable in one place; contributing would *spread* it across `PrometheusConfig`,
`HealthChecksConfig` and OpenTelemetry, and the health-check case would still need OpenTelemetry's
own `opentelemetry_generate_health_check_spans` flag, so the cross-coupling would not even
disappear. It moves complexity and worsens locality.

The real risk in the sibling reads is silent breakage: rename `prometheus_metrics_path` and the
`getattr` returns `None`, the metrics endpoint quietly stops being excluded from traces, and nothing
fails. That is answered with a test that pins each sibling path in the built set, not with a
refactor.

**Revisit trigger:** a third-party or user-supplied instrument needs its own paths excluded. The
policy would then have to name paths it cannot know about, which is precisely the case a contribution
mechanism exists for.
