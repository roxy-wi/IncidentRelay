from unittest.mock import Mock

import pytest

from app import telegram_worker


@pytest.mark.parametrize("processed", [0, 5])
def test_fast_poll_is_rate_limited_even_with_updates(monkeypatch, processed):
    shutdown = Mock()
    monkeypatch.setattr(telegram_worker, "poll_telegram_channels_once", lambda **kw: processed)
    monkeypatch.setattr(telegram_worker.Config, "METRICS_ENABLED", False)
    clock = iter([10.0, 10.1])
    monkeypatch.setattr(telegram_worker.time, "monotonic", lambda: next(clock))
    telegram_worker.run_poll_cycle(shutdown)
    shutdown.wait.assert_called_once_with(pytest.approx(0.9))


def test_long_poll_does_not_add_an_idle_delay(monkeypatch):
    shutdown = Mock()
    monkeypatch.setattr(telegram_worker, "poll_telegram_channels_once", lambda **kw: 0)
    monkeypatch.setattr(telegram_worker.Config, "METRICS_ENABLED", False)
    clock = iter([10.0, 30.0])
    monkeypatch.setattr(telegram_worker.time, "monotonic", lambda: next(clock))
    telegram_worker.run_poll_cycle(shutdown)
    shutdown.wait.assert_called_once_with(0)


def test_error_backoff_can_be_interrupted_by_shutdown(monkeypatch):
    shutdown = Mock()

    def fail(**kw):
        raise RuntimeError("poll failed")

    monkeypatch.setattr(telegram_worker, "poll_telegram_channels_once", fail)
    telegram_worker.run_poll_cycle(shutdown)
    shutdown.wait.assert_called_once_with(5)
