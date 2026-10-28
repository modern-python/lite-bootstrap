import dataclasses
import typing
from collections.abc import Mapping

from lite_bootstrap.exceptions import ConfigurationError
from lite_bootstrap.helpers.warn import warn_at_caller
from lite_bootstrap.types import UNSET, UnsetType


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class BaseConfig:
    service_name: str = "micro-service"
    service_description: str | None = None
    service_version: str = "1.0.0"
    service_environment: str | None = None
    service_debug: bool = True
    # Deprecated field name -> the field that replaced it. The deprecated field defaults to UNSET.
    _renamed_fields: typing.ClassVar[Mapping[str, str]] = {}

    def __post_init__(self) -> None:
        """Terminate the MRO __post_init__ cascade safely, after forwarding deprecated field names.

        Subclasses call super().__post_init__() to propagate through multiple-inheritance
        chains (e.g. FastAPIConfig → CorsConfig → OpenTelemetryConfig → BaseConfig).
        Without this, the chain would raise AttributeError on object.

        Running first in the cascade, the forwarding copies each deprecated field the caller set into
        its replacement before any subclass reads it, then resets the deprecated field to UNSET so
        `dataclasses.replace()` does not see both set.
        """
        for old_name, new_name in self._renamed_fields.items():
            old_value = getattr(self, old_name)
            if isinstance(old_value, UnsetType):
                continue
            new_field = next(field for field in dataclasses.fields(self) if field.name == new_name)
            new_default = (
                new_field.default if new_field.default_factory is dataclasses.MISSING else new_field.default_factory()
            )
            if getattr(self, new_name) != new_default:
                msg = f"{old_name} and {new_name} are both set; {old_name} is deprecated, set only {new_name}."
                raise ConfigurationError(msg)
            warn_at_caller(
                f"{old_name} is deprecated and will be removed in lite-bootstrap 2.0; use {new_name} instead.",
                category=DeprecationWarning,
            )
            object.__setattr__(self, new_name, old_value)
            object.__setattr__(self, old_name, UNSET)

    @classmethod
    def from_dict(cls, data: dict[str, typing.Any]) -> typing.Self:
        """Build a config from a dict; unknown keys are silently dropped, explicit None overrides defaults."""
        field_names = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in field_names})

    @classmethod
    def from_object(cls, obj: object) -> typing.Self:
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
                warn_at_caller(
                    f"{cls.__name__}.{legacy_name} is deprecated and will be removed in lite-bootstrap 2.0; "
                    f"use {current_name} instead.",
                    category=DeprecationWarning,
                )
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
