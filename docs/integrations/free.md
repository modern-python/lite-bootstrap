# Usage without frameworks

## 1. Install `lite-bootstrap[free-all]`:

=== "uv"

      ```bash
      uv add lite-bootstrap[free-all]
      ```

=== "pip"

      ```bash
      pip install lite-bootstrap[free-all]
      ```

=== "poetry"

      ```bash
      poetry add lite-bootstrap[free-all]
      ```

Read more about available extras [here](../../../introduction/installation):

## 2. Define bootstrapper config and build you application:

```python
from lite_bootstrap import FreeBootstrapperConfig, FreeBootstrapper


bootstrapper_config = FreeBootstrapperConfig(
    service_debug=False,
    opentelemetry_endpoint="otl",
    sentry_dsn="https://testdsn@localhost/1",
)
bootstrapper = FreeBootstrapper(bootstrapper_config)
bootstrapper.bootstrap()
```

Read more about available configuration options [here](../../../introduction/configuration):
