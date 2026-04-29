import signal
import sys
import time

from app import create_app
from app.services.scheduler import start_scheduler


def stop(signum, frame):
    """
    Stop scheduler process.
    """

    sys.exit(0)


def main():
    """
    Start IncidentRelay scheduler as a standalone process.
    """

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    app = create_app()

    with app.app_context():
        start_scheduler()

        while True:
            time.sleep(60)


if __name__ == "__main__":
    main()
