import logging
import signal
import time

from app import create_app
from app.notifiers.slack.socket_worker import SlackSocketManager


logger = logging.getLogger("oncall.slack")
_shutdown = False


def _handle_shutdown(signum, frame):
    global _shutdown
    _shutdown = True
    logger.info(
        "Slack worker shutdown requested",
        extra={"extra": {"signal": signum}},
    )


def main():
    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)

    app = create_app(log_role="slack")
    manager = SlackSocketManager(app)
    logger.info("Slack Socket Mode worker started")

    try:
        with app.app_context():
            while not _shutdown:
                try:
                    connection_count = manager.reconcile()
                    logger.debug(
                        "Slack Socket Mode configuration reconciled",
                        extra={
                            "extra": {
                                "connection_count": connection_count,
                            }
                        },
                    )
                except Exception:
                    logger.exception("Slack Socket Mode reconciliation failed")
                for _ in range(15):
                    if _shutdown:
                        break
                    time.sleep(1)
    finally:
        manager.close()

    logger.info("Slack Socket Mode worker stopped")


if __name__ == "__main__":
    main()
