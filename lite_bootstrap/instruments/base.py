import dataclasses
import typing


_DEFAULT_SERVICE_NAME: typing.Final = "micro-service"
_DEFAULT_SERVICE_VERSION: typing.Final = "1.0.0"


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class BaseConfig:
    service_name: str | None = None
    service_description: str | None = None
    service_version: str | None = None
    service_environment: str | None = None
    service_debug: bool = False

    @property
    def service_name_or_default(self) -> str:
        return self.service_name or _DEFAULT_SERVICE_NAME

    @property
    def service_version_or_default(self) -> str:
        return self.service_version or _DEFAULT_SERVICE_VERSION

    def __post_init__(self) -> None:
        """Terminate the multiple-inheritance __post_init__ cascade for subclasses calling super()."""

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


@dataclasses.dataclass(kw_only=True, slots=True)
class BaseInstrument(typing.Generic[ConfigT]):
    bootstrap_config: ConfigT
    not_configured_reason = ""
    missing_dependency_message = ""

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
