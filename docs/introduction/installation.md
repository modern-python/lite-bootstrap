# Installation

## Choose suitable extras

You can choose required framework and instruments using this table:

| Instrument    | Litestar           | Faststream           | FastAPI           | Free Bootstrapper, without framework |
|---------------|--------------------|----------------------|-------------------|--------------------------------------|
| sentry        | `litestar-sentry`  | `faststream-sentry`  | `fastapi-sentry`  | `sentry`                             |
| prometheus    | `litestar-metrics` | `faststream-metrics` | `fastapi-metrics` | not used                             |
| opentelemetry | `litestar-otl`     | `faststream-otl`     | `fastapi-otl`     | `otl`                                |
| structlog     | `litestar-logging` | `faststream-logging` | `fastapi-logging` | `logging`                            |
| cors          | no extra           | not used             | no extra          | not used                             |
| swagger       | no extra           | not used             | no extra          | not used                             |
| health-checks | no extra           | no extra             | no extra          | not used                             |
| all           | `litestar-all`     | `faststream-all`     | `fastapi-all`     | `free-all`                           |

* not used - means that the instrument is not implemented in the integration.
* no extra - means that the instrument requires no additional dependencies.

## Install `lite-bootstrap` using your favorite tool with choosen extras

For example, if you want to bootstrap litestar with structlog and opentelemetry instruments:

=== "uv"

      ```bash
      uv add lite-bootstrapp[litestar-logging,litestar-otl]
      ```

=== "pip"

      ```bash
      pip install lite-bootstrapp[litestar-logging,litestar-otl]
      ```

=== "poetry"

      ```bash
      poetry add lite-bootstrapp[litestar-logging,litestar-otl]
      ```
