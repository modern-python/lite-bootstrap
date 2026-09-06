# Quickstart

This walkthrough takes you from an empty project to a **FastAPI service with
production observability** — metrics, health checks, CORS, Swagger, and
structured logging — wired up in a few lines. The same pattern applies to
[Litestar](../integrations/litestar.md), [FastStream](../integrations/faststream.md),
[FastMCP](../integrations/fastmcp.md), and
[framework-free services](../integrations/free.md).

## 1. Install

Install `lite-bootstrap` with the FastAPI extras. `fastapi-all` pulls in every
supported instrument:

=== "uv"

      ```bash
      uv add lite-bootstrap[fastapi-all]
      ```

=== "pip"

      ```bash
      pip install lite-bootstrap[fastapi-all]
      ```

=== "poetry"

      ```bash
      poetry add lite-bootstrap[fastapi-all]
      ```

Want only some instruments? See the extras matrix in
[Installation](installation.md).

## 2. Bootstrap your application

Create `main.py`:

```python
from fastapi import FastAPI
from lite_bootstrap import FastAPIConfig, FastAPIBootstrapper

config = FastAPIConfig(
    service_name="my-service",
    service_version="1.0.0",
    service_environment="local",
    prometheus_metrics_path="/metrics",
    health_checks_enabled=True,
    health_checks_path="/health",
    cors_allowed_origins=["*"],
    swagger_offline_docs=True,
)

app: FastAPI = FastAPIBootstrapper(config).bootstrap()


@app.get("/")
async def root() -> dict[str, str]:
    return {"hello": "world"}
```

`bootstrap()` returns a ready `FastAPI` app with every configured instrument
attached.

## 3. Run it

```bash
uvicorn main:app --reload
```

## 4. What you get

With the config above, your service now exposes:

- **Metrics** at `/metrics` in Prometheus format — point your scraper at it.
- **Health check** at `/health` — wire it to your orchestrator's readiness probe.
- **Swagger UI** at `/docs` — with offline assets, so it renders without a CDN.
- **CORS** headers for the configured origins.
- **Structured logging** via `structlog` — enabled by default (opt out with
  `logging_enabled=False`).

## 5. Enable more

Each instrument is opt-in: add its config field to turn it on. Unset (or empty)
fields are skipped automatically, so you only pay for what you enable.

```python
config = FastAPIConfig(
    service_name="my-service",
    service_version="1.0.0",
    service_environment="local",
    # tracing — spans exported to your OTLP endpoint
    opentelemetry_endpoint="http://localhost:4317",
    # error reporting
    sentry_dsn="https://examplePublicKey@o0.ingest.sentry.io/0",
    # continuous profiling (needs the `pyroscope` extra)
    pyroscope_endpoint="http://localhost:4040",
)
```

To see exactly which instruments were enabled or skipped at startup, inspect the
bootstrapper:

```python
bootstrapper = FastAPIBootstrapper(config)
app = bootstrapper.bootstrap()

print(bootstrapper.build_summary())  # human-readable summary
for cls, reason in bootstrapper.skipped_instruments:
    print(f"skipped {cls.__name__}: {reason}")
```

## Next steps

- [Configuration](configuration.md) — every config field and per-instrument option.
- [Integrations](../integrations/litestar.md) — Litestar, FastStream, FastMCP,
  and framework-free services.
