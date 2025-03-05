from lite_bootstrap.instruments.sentry_instrument import SentryInstrument


def test_sentry_bootstrap() -> None:
    SentryInstrument(dsn="https://testdsn@test.sentry.com/1", tags={"tag": "value"}).bootstrap()


def test_sentry_bootstrap_empty_dsn() -> None:
    SentryInstrument(dsn="").bootstrap()
