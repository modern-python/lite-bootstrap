import dataclasses
import typing

from lite_bootstrap import import_checker
from lite_bootstrap.instruments.base import BaseInstrument
from lite_bootstrap.instruments.opentelemetry_instrument import OpenTelemetryServiceFieldsConfig


if import_checker.is_pyroscope_installed:
    import pyroscope


@dataclasses.dataclass(kw_only=True, frozen=True)
class PyroscopeConfig(OpenTelemetryServiceFieldsConfig):
    pyroscope_endpoint: str | None = None
    pyroscope_sample_rate: int = 100
    pyroscope_tags: dict[str, str] = dataclasses.field(default_factory=dict)
    pyroscope_additional_params: dict[str, typing.Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass(kw_only=True, slots=True)
class PyroscopeInstrument(BaseInstrument[PyroscopeConfig]):
    not_configured_reason = "pyroscope_endpoint is empty"
    missing_dependency_message = "pyroscope is not installed"

    @classmethod
    def is_configured(cls, bootstrap_config: "PyroscopeConfig") -> bool:
        return bool(bootstrap_config.pyroscope_endpoint)

    @staticmethod
    def dependencies_installed() -> bool:
        return import_checker.is_pyroscope_installed

    def bootstrap(self) -> None:
        config = self.bootstrap_config
        # is_configured() guarantees pyroscope_endpoint is set when called via the
        # bootstrapper. Direct callers bypassing is_configured see an explicit raise.
        if config.pyroscope_endpoint is None:
            msg = "pyroscope_endpoint is unset; PyroscopeInstrument.is_configured() should have returned False"
            raise RuntimeError(msg)
        namespace = config.opentelemetry_namespace
        tags = ({"service_namespace": namespace} if namespace else {}) | config.pyroscope_tags
        pyroscope.configure(
            application_name=config.opentelemetry_service_name or config.service_name,
            server_address=config.pyroscope_endpoint,
            sample_rate=config.pyroscope_sample_rate,
            tags=tags,
            **config.pyroscope_additional_params,
        )

    def teardown(self) -> None:
        pyroscope.shutdown()
