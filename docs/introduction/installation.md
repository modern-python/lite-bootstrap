# Installation

## Choose suitable extras

You can choose required framework and instruments using this table:

FastMCP has no per-pair (`fastmcp-sentry`, …) or rollup (`fastmcp-all`) extras because they would not pull in new dependencies. Compose what you need yourself, e.g. `lite-bootstrap[fastmcp,fastmcp-metrics,sentry,logging,pyroscope]`.

| Instrument    | Litestar           | Faststream           | FastAPI           | FastMCP             | Free Bootstrapper, without framework |
|---------------|--------------------|----------------------|-------------------|---------------------|--------------------------------------|
| sentry        | `litestar-sentry`  | `faststream-sentry`  | `fastapi-sentry`  | `sentry` (compose)  | `sentry`                             |
| prometheus    | `litestar-metrics` | `faststream-metrics` | `fastapi-metrics` | `fastmcp-metrics`   | not used                             |
| opentelemetry | `litestar-otl`     | `faststream-otl`     | `fastapi-otl`     | not used            | `otl`                                |
| pyroscope     | `pyroscope`        | `pyroscope`          | `pyroscope`       | `pyroscope`         | `pyroscope`                          |
| structlog     | `litestar-logging` | `faststream-logging` | `fastapi-logging` | `logging` (compose) | `logging`                            |
| cors          | no extra           | not used             | no extra          | not used            | not used                             |
| swagger       | no extra           | not used             | no extra          | not used            | not used                             |
| health-checks | no extra           | no extra             | no extra          | no extra            | not used                             |
| all           | `litestar-all`     | `faststream-all`     | `fastapi-all`     | no rollup (compose) | `free-all`                           |

* not used - means that the instrument is not implemented in the integration.
* no extra - means that the instrument requires no additional dependencies.

## Install `lite-bootstrap` using your favorite tool with choosen extras

For example, if you want to bootstrap litestar with structlog and opentelemetry instruments:

=== "uv"

      ```bash
      uv add lite-bootstrap[litestar-logging,litestar-otl]
      ```

=== "pip"

      ```bash
      pip install lite-bootstrap[litestar-logging,litestar-otl]
      ```

=== "poetry"

      ```bash
      poetry add lite-bootstrap[litestar-logging,litestar-otl]
      ```
