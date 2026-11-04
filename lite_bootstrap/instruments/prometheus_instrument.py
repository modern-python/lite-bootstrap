"""Prometheus config and readiness check; framework-specific bootstrap lives in the bootstrapper subclasses."""

import dataclasses
import re
import typing

from lite_bootstrap import import_checker
from lite_bootstrap.exceptions import ConfigurationError
from lite_bootstrap.helpers.path import is_valid_path
from lite_bootstrap.instruments.base import BaseConfig, BaseInstrument


@dataclasses.dataclass(kw_only=True, frozen=True)
class PrometheusConfig(BaseConfig):
    prometheus_metrics_path: str = "/metrics"
    prometheus_metrics_include_in_schema: bool = False

    def __post_init__(self) -> None:
        super().__post_init__()
        path = self.prometheus_metrics_path
        if path and not is_valid_path(path):
            msg = f"Invalid prometheus_metrics_path: {path!r}"
            raise ConfigurationError(msg)


@dataclasses.dataclass(kw_only=True, frozen=True)
class PrometheusHttpConfig(PrometheusConfig):
    prometheus_http_metrics_enabled: bool | None = None

    def is_prometheus_http_metrics_on(self, *, opentelemetry_records_http_metrics: bool) -> bool:
        """Left None, Prometheus records HTTP metrics unless OpenTelemetry already records them."""
        if self.prometheus_http_metrics_enabled is not None:
            return self.prometheus_http_metrics_enabled
        return not opentelemetry_records_http_metrics


PrometheusConfigT = typing.TypeVar("PrometheusConfigT", bound=PrometheusConfig)


@dataclasses.dataclass(kw_only=True, slots=True)
class PrometheusInstrument(BaseInstrument[PrometheusConfigT]):
    not_configured_reason = "prometheus_metrics_path is empty or uses its default without prometheus_client"

    @classmethod
    def is_configured(cls, bootstrap_config: "PrometheusConfig") -> bool:
        path = bootstrap_config.prometheus_metrics_path
        default_path = next(
            field.default for field in dataclasses.fields(bootstrap_config) if field.name == "prometheus_metrics_path"
        )
        return bool(path) and (path != default_path or import_checker.is_prometheus_client_installed)

    def infrastructure_excluded_patterns(self) -> list[str]:
        config = self.bootstrap_config
        paths = (getattr(config, "health_checks_path", ""), config.prometheus_metrics_path)
        return [rf"^{re.escape(path.rstrip('/'))}/?$" for path in paths if path]
