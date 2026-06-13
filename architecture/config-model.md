# Config model

Configs describe *what the user wants*. They are immutable, declarative, and
carry no runtime state. Every config in the project descends from `BaseConfig`
(`lite_bootstrap/instruments/base.py`).

## BaseConfig

`BaseConfig` is a `@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)`.
It holds the service-identity fields shared by every instrument (`service_name`,
`service_description`, `service_version`, `service_environment`, `service_debug`).

Framework configs compose multiple instrument configs via **multiple
inheritance**. For example `FastAPIConfig` mixes `CorsConfig`,
`OpenTelemetryConfig`, `LoggingConfig`, `SentryConfig`, `PrometheusConfig`,
`SwaggerConfig`, `HealthChecksConfig`, etc. into one frozen dataclass, so a
single config object configures every instrument the framework supports.

All `*Config` classes are frozen for user-facing immutability; only the
`*Instrument` classes are non-frozen (they cache runtime state — see
`architecture/instruments.md`).

## from_dict vs from_object

Two classmethods build a config from external data. They differ in how they
treat `None`:

- `BaseConfig.from_dict(data)` — keeps unknown keys out (`{k: v for k, v in
  data.items() if k in field_names}`) but passes through explicit `None`. So
  `BaseConfig.from_dict({"service_name": None})` succeeds and **overrides** the
  default with `None`.
- `BaseConfig.from_object(obj)` — pulls each field via `getattr(obj, field,
  None)` and **filters out** any attribute that is `None` or missing, letting
  the dataclass default take over.

The asymmetry is load-bearing: pick `from_dict` when explicit-None override is
the semantic you want; pick `from_object` when missing/None should mean
"fall back to default." It is documented in both docstrings
(`instruments/base.py:25, 31`) and pinned by tests in `tests/test_config.py`.

## UNSET sentinel and FastAPIConfig.application

`lite_bootstrap/types.py` defines `UnsetType` and the singleton `UNSET`
(`typing.Final[UnsetType]`). It distinguishes "user did not supply this" from
"user explicitly passed `None`", which a plain `None` default cannot express.

`FastAPIConfig.application` defaults to `UNSET`. In `__post_init__`, when the
value is still `UnsetType`, the config constructs a fresh `FastAPI()` and writes
it back:

```python
if isinstance(self.application, UnsetType):
    application = fastapi.FastAPI(...)
    object.__setattr__(self, "application", application)
```

The `object.__setattr__` bypasses the frozen guard — the config stays
immutable to the user, but construction-time computed fields can still be set.
A one-line comment documents the trade-off (user-facing immutability vs.
construction-time mutation) at the bypass site.

## __post_init__ cascade invariant

Several configs override `__post_init__` (e.g. `OpenTelemetryConfig` emits a
security warning, `CorsConfig` validates, `FastAPIConfig` constructs the app).
Because they share an MRO under `FastAPIConfig` / `LitestarConfig` /
`FastStreamConfig` / `FreeConfig`, **every** config `__post_init__` must call
`super().__post_init__()` so the chain runs to completion. A class that returns
early before `super()` silently blocks the rest of the chain.

`BaseConfig.__post_init__` is a deliberate no-op that **terminates** the
cascade; without it the chain would raise `AttributeError` on `object`.

`FastAPIConfig` uses the explicit `super(FastAPIConfig, self).__post_init__()`
form rather than bare `super()`. Under `@dataclass(slots=True)` the decorator
replaces the class object after the body compiles, which breaks the bare-`super()`
`__class__` cell; the explicit form is required.
