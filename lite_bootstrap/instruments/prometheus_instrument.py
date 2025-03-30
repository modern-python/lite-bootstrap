import dataclasses
import re
import typing

from lite_bootstrap.instruments.base import BaseConfig, BaseInstrument


VALID_PATH_PATTERN: typing.Final = re.compile(r"^(/[a-zA-Z0-9_-]+)+/?$")


def _is_valid_path(maybe_path: str) -> bool:
    return bool(re.fullmatch(VALID_PATH_PATTERN, maybe_path))


@dataclasses.dataclass(kw_only=True, frozen=True)
class PrometheusConfig(BaseConfig):
    prometheus_metrics_path: str = "/metrics"
    prometheus_metrics_include_in_schema: bool = False


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class PrometheusInstrument(BaseInstrument):
    bootstrap_config: PrometheusConfig

    def is_ready(self) -> bool:
        return bool(self.bootstrap_config.prometheus_metrics_path) and _is_valid_path(
            self.bootstrap_config.prometheus_metrics_path
        )
