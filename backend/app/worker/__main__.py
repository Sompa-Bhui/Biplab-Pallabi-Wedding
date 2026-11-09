import logging
import time

from app.core.config import get_settings
from app.db.session import session_factory
from app.services.outbox import run_once


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    settings.validate_email_configuration()
    factory = session_factory()
    logging.getLogger(__name__).info("RSVP email worker started.")
    try:
        while True:
            if not run_once(factory, settings):
                time.sleep(settings.outbox_poll_seconds)
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("RSVP email worker stopped.")


if __name__ == "__main__":
    main()
