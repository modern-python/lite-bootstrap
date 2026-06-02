"""Prometheus config and readiness check; framework-specific bootstrap lives in the bootstrapper subclasses."""

import dataclasses

from lite_bootstrap.helpers.path import is_valid_path
from lite_bootstrap.instruments.base import BaseConfig, BaseInstrument


@dataclasses.dataclass(kw_only=True, frozen=True)
class PrometheusConfig(BaseConfig):
    prometheus_metrics_path: str = "/metrics"
    prometheus_metrics_include_in_schema: bool = False


@dataclasses.dataclass(kw_only=True, slots=True)
class PrometheusInstrument(BaseInstrument[PrometheusConfig]):
    not_ready_message = "prometheus_metrics_path is empty or not valid"

    @classmethod
    def is_configured(cls, bootstrap_config: "PrometheusConfig") -> bool:
        return bool(bootstrap_config.prometheus_metrics_path) and is_valid_path(
            bootstrap_config.prometheus_metrics_path
        )
