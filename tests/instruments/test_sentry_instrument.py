from lite_bootstrap.instruments.sentry_instrument import SentryConfig, SentryInstrument


def test_sentry_instrument() -> None:
    SentryInstrument(
        bootstrap_config=SentryConfig(sentry_dsn="https://testdsn@localhost/1", sentry_tags={"tag": "value"})
    ).bootstrap()


def test_sentry_instrument_empty_dsn() -> None:
    SentryInstrument(bootstrap_config=SentryConfig(sentry_dsn="")).bootstrap()
