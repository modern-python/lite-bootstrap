import logging

import pytest

from lite_bootstrap.exceptions import TeardownError, TeardownErrorCollector, collect_teardown_errors


def _run_teardown(
    steps: list[tuple[str, BaseException | None]],
    logger: logging.Logger | None = None,
) -> TeardownErrorCollector:
    """Run one ``collect_teardown_errors`` block, capturing each named step's exception (if any)."""
    with collect_teardown_errors(logger) as teardown_errors:
        for name, error in steps:
            with teardown_errors.capture(name):
                if error is not None:
                    raise error
    return teardown_errors


def test_collect_teardown_errors_raises_one_teardown_error_after_the_block() -> None:
    first = RuntimeError("boom-1")
    second = ValueError("boom-2")

    with pytest.raises(TeardownError) as excinfo:
        _run_teardown([("First", first), ("Second", second)])

    assert excinfo.value.errors == [("First", first), ("Second", second)]
    assert excinfo.value.__cause__ is first


def test_collect_teardown_errors_is_silent_when_nothing_failed() -> None:
    assert _run_teardown([("Fine", None)]).errors == []


def test_capture_logs_a_warning_when_a_logger_is_given(caplog: pytest.LogCaptureFixture) -> None:
    test_logger = logging.getLogger("tests.test_exceptions")

    with caplog.at_level(logging.WARNING, logger=test_logger.name), pytest.raises(TeardownError):
        _run_teardown([("Noisy", RuntimeError("boom"))], logger=test_logger)

    assert [(record.levelno, record.message) for record in caplog.records] == [
        (logging.WARNING, "Error tearing down Noisy: boom")
    ]


def test_capture_lets_base_exceptions_through() -> None:
    """INVARIANT: capture() collects an Exception and lets every other BaseException propagate.

    Broadening the ``except`` clause in ``capture`` to ``BaseException`` breaks it: a
    ``KeyboardInterrupt`` would be swallowed, the remaining teardown steps would run anyway, and
    the interrupt would surface at the end of the block as a ``TeardownError`` — an uninterruptible
    teardown that reports the wrong failure.
    """
    with pytest.raises(KeyboardInterrupt):
        _run_teardown([("Interrupted", KeyboardInterrupt())])
