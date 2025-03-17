import dataclasses

from lite_bootstrap.instruments.sentry_instrument import SentryInstrument


@dataclasses.dataclass(kw_only=True, frozen=True)
class FastAPISentryInstrument(SentryInstrument): ...
