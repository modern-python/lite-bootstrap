import dataclasses

from lite_bootstrap.instruments.logging_instrument import LoggingInstrument


@dataclasses.dataclass(kw_only=True, frozen=True)
class FastAPILoggingInstrument(LoggingInstrument): ...
