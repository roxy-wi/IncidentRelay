import logging
import signal
import time

from app import create_app
from app.notifiers.telegram.poller import poll_telegram_channels_once
from app.services.metrics import record_worker_heartbeat
from app.settings import Config


logger = logging.getLogger("oncall.telegram")
_shutdown = False


def _handle_shutdown(signum, frame):
    """
    Handle shutdown signals.
    """
    global _shutdown

    _shutdown = True

    logger.info(
        "telegram worker shutdown requested",
        extra={"extra": {"signal": signum}},
    )


def main():
    """
    Start Telegram callback polling worker.
    """
    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)

    app = create_app(log_role="telegram")

    logger.info("telegram worker started")

    with app.app_context():
        while not _shutdown:
            try:
                processed = poll_telegram_channels_once(timeout=20)

                logger.debug(
                    "telegram poll completed",
                    extra={"extra": {"processed": processed}},
                )

                if Config.METRICS_ENABLED:
                    record_worker_heartbeat("telegram")
            except Exception:
                logger.exception("telegram poll failed")
                time.sleep(5)

    logger.info("telegram worker stopped")


if __name__ == "__main__":
    main()
