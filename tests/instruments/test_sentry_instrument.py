from lite_bootstrap.instruments.sentry_instrument import SentryInstrument
from lite_bootstrap.service_config import ServiceConfig


def test_sentry_instrument(service_config: ServiceConfig) -> None:
    SentryInstrument(dsn="https://testdsn@localhost/1", tags={"tag": "value"}).bootstrap(service_config)


def test_sentry_instrument_empty_dsn(service_config: ServiceConfig) -> None:
    SentryInstrument(dsn="").bootstrap(service_config)
