import logging
import signal
import threading
import time

from app import create_app
from app.notifiers.telegram.poller import poll_telegram_channels_once
from app.services.metrics import record_worker_heartbeat
from app.settings import Config


logger = logging.getLogger("oncall.telegram")
_shutdown = threading.Event()


def _handle_shutdown(signum, frame):
    """
    Handle shutdown signals.
    """
    _shutdown.set()

    logger.info(
        "telegram worker shutdown requested",
        extra={"extra": {"signal": signum}},
    )


def run_poll_cycle(shutdown):
    """Bound empty/backed-off polls without delaying a normal long poll.

    A successful poll can return immediately when no channel is configured or
    all channels are in backoff. Waiting on the shutdown event also makes both
    idle and error backoffs interruptible by SIGTERM.
    """
    started = time.monotonic()
    try:
        processed = poll_telegram_channels_once(timeout=20)
        logger.debug("telegram poll completed", extra={"extra": {"processed": processed}})
        if Config.METRICS_ENABLED:
            record_worker_heartbeat("telegram")
    except Exception:
        logger.exception("telegram poll failed")
        shutdown.wait(5)
        return
    shutdown.wait(max(0, 1 - (time.monotonic() - started)))


def main():
    """
    Start Telegram callback polling worker.
    """
    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)

    app = create_app(log_role="telegram")

    logger.info("telegram worker started")

    with app.app_context():
        while not _shutdown.is_set():
            run_poll_cycle(_shutdown)

    logger.info("telegram worker stopped")


if __name__ == "__main__":
    main()
