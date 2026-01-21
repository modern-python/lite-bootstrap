import logging
import typing

import pytest
import sentry_sdk

from tests.conftest import SentryTestTransport


if typing.TYPE_CHECKING:
    pass

from lite_bootstrap.instruments.sentry_instrument import (
    SentryConfig,
    SentryInstrument,
)


logger = logging.getLogger(__name__)


@pytest.fixture
def minimal_sentry_config(sentry_mock: SentryTestTransport) -> SentryConfig:
    return SentryConfig(
        sentry_dsn="https://testdsn@localhost/1",
        sentry_tags={"test": "test"},
        sentry_additional_params={"transport": sentry_mock},
    )


def test_sentry_instrument_with_raise(minimal_sentry_config: SentryConfig, sentry_mock: SentryTestTransport) -> None:
    SentryInstrument(bootstrap_config=minimal_sentry_config).bootstrap()

    try:
        logger.error("some error")
        assert len(sentry_mock.mock_envelopes) == 1
    finally:
        sentry_sdk.init()


def test_sentry_instrument_empty_dsn() -> None:
    SentryInstrument(bootstrap_config=SentryConfig(sentry_dsn="")).bootstrap()
