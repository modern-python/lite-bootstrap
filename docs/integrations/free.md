# Usage without frameworks

## 1. Install `lite-bootstrapp[free-all]`:

=== "uv"
 
      ```bash
      uv add lite-bootstrapp[free-all]
      ```
 
=== "pip"

      ```bash
      pip install lite-bootstrapp[free-all]
      ```

=== "poetry"

      ```bash
      poetry add lite-bootstrapp[free-all]
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
