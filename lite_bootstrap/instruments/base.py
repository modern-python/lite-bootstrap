import abc
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

    @classmethod
    def from_dict(cls, data: dict[str, typing.Any]) -> typing_extensions.Self:
        field_names = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in field_names})

    @classmethod
    def from_object(cls, obj: object) -> typing_extensions.Self:
        prepared_data = {}
        field_names = {f.name for f in dataclasses.fields(cls)}

        for field in field_names:
            if (value := getattr(obj, field, None)) is not None:
                prepared_data[field] = value
        return cls(**prepared_data)


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class BaseInstrument(abc.ABC):
    bootstrap_config: BaseConfig
    not_ready_message = ""
    missing_dependency_message = ""

    def bootstrap(self) -> None: ...  # noqa: B027

    def teardown(self) -> None: ...  # noqa: B027

    def is_ready(self) -> bool:
        return True

    @staticmethod
    def check_dependencies() -> bool:
        return True
