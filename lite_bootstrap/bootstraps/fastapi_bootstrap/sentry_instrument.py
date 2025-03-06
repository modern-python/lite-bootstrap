import contextlib
import dataclasses

import fastapi

from lite_bootstrap.instruments.sentry_instrument import SentryInstrument


with contextlib.suppress(ImportError):
    from sentry_sdk.integrations.asgi import SentryAsgiMiddleware


@dataclasses.dataclass(kw_only=True)
class FastAPISentryInstrument(SentryInstrument):
    app: fastapi.FastAPI = dataclasses.field(init=False)

    def bootstrap(self) -> None:
        super().bootstrap()
        self.app.add_middleware(SentryAsgiMiddleware)  # type: ignore[arg-type]
