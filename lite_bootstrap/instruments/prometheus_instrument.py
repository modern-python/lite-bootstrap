import dataclasses
import re
import typing

from lite_bootstrap.instruments.base import BaseInstrument
from lite_bootstrap.service_config import ServiceConfig


VALID_PATH_PATTERN: typing.Final = re.compile(r"^(/[a-zA-Z0-9_-]+)+/?$")


def _is_valid_path(maybe_path: str) -> bool:
    return bool(re.fullmatch(VALID_PATH_PATTERN, maybe_path))


@dataclasses.dataclass(kw_only=True, slots=True, frozen=True)
class PrometheusInstrument(BaseInstrument):
    metrics_path: str = "/metrics"
    metrics_include_in_schema: bool = False

    def is_ready(self, _: ServiceConfig) -> bool:
        return bool(self.metrics_path) and _is_valid_path(self.metrics_path)
