import dataclasses
import typing

import typing_extensions


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class BaseConfig:
    service_name: str = "micro-service"
    service_description: str | None = None
    service_version: str = "1.0.0"
    service_environment: str | None = None
    service_debug: bool = True

    def __post_init__(self) -> None:
        """Terminate the MRO __post_init__ cascade safely.

        Subclasses call super().__post_init__() to propagate through multiple-inheritance
        chains (e.g. FastAPIConfig → CorsConfig → OpenTelemetryConfig → BaseConfig).
        Without this no-op, the chain would raise AttributeError on object.
        """

    @classmethod
    def from_dict(cls, data: dict[str, typing.Any]) -> typing_extensions.Self:
        """Build a config from a dict; unknown keys are silently dropped, explicit None overrides defaults."""
        field_names = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in field_names})

    @classmethod
    def from_object(cls, obj: object) -> typing_extensions.Self:
        """Build a config by merging non-None attributes from obj; None or missing attributes fall back to defaults."""
        field_names = {f.name for f in dataclasses.fields(cls)}
        prepared_data = {field: value for field in field_names if (value := getattr(obj, field, None)) is not None}
        return cls(**prepared_data)


ConfigT = typing.TypeVar("ConfigT", bound=BaseConfig)


# Legacy name -> current name; __init_subclass__ forwards an out-of-tree instrument's old spelling.
_RENAMED_ATTRIBUTES: typing.Final = {
    "not_ready_message": "not_configured_reason",
    "check_dependencies": "dependencies_installed",
}


@dataclasses.dataclass(kw_only=True, slots=True)
class BaseInstrument(typing.Generic[ConfigT]):
    bootstrap_config: ConfigT
    not_configured_reason = ""
    missing_dependency_message = ""

    def __init_subclass__(cls, **kwargs: object) -> None:
        # @dataclass(slots=True) replaces the class object, breaking bare super().
        super(BaseInstrument, cls).__init_subclass__(**kwargs)
        for legacy_name, current_name in _RENAMED_ATTRIBUTES.items():
            if legacy_name in cls.__dict__ and current_name not in cls.__dict__:
                setattr(cls, current_name, cls.__dict__[legacy_name])

    def bootstrap(self) -> None: ...

    def teardown(self) -> None: ...

    @classmethod
    def is_configured(cls, bootstrap_config: ConfigT) -> bool:  # noqa: ARG003
        """Return True if config indicates this instrument should be active. Default: always active."""
        return True

    @staticmethod
    def dependencies_installed() -> bool:
        """Return True if this instrument's optional package is importable. Default: nothing to import."""
        return True
