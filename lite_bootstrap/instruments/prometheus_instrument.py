import dataclasses

from lite_bootstrap.helpers import is_valid_path
from lite_bootstrap.instruments.base import BaseConfig, BaseInstrument


@dataclasses.dataclass(kw_only=True, frozen=True)
class PrometheusConfig(BaseConfig):
    prometheus_metrics_path: str = "/metrics"
    prometheus_metrics_include_in_schema: bool = False


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class PrometheusInstrument(BaseInstrument):
    bootstrap_config: PrometheusConfig
    not_ready_message = "prometheus_metrics_path is empty or not valid"

    def is_ready(self) -> bool:
        return bool(self.bootstrap_config.prometheus_metrics_path) and is_valid_path(
            self.bootstrap_config.prometheus_metrics_path
        )
