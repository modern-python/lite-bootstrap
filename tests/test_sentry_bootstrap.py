from lite_bootstrap.sentry_bootstrap import SentryBootstrap


def test_sentry_bootstrap() -> None:
    SentryBootstrap(sentry_dsn="https://testdsn@test.sentry.com/1", tags={"tag": "value"}).start_tracing()


def test_sentry_bootstrap_empty_dsn() -> None:
    SentryBootstrap(sentry_dsn="").start_tracing()
