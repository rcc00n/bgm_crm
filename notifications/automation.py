"""A bounded scheduler inside the existing, single-instance Telegram worker."""
import logging
import threading

from django.db import close_old_connections

logger = logging.getLogger(__name__)


def run_once():
    from .delivery import process_pending_messages
    from .lead_digest import send_due_lead_digest
    from .services import process_due_reminders, send_daily_digest

    tasks = (
        (process_pending_messages, {"limit": 5}),
        (send_due_lead_digest, {}),
        (send_daily_digest, {}),
        (process_due_reminders, {"limit": 5}),
    )
    for task, kwargs in tasks:
        close_old_connections()
        try:
            task(**kwargs)
        except Exception:
            logger.exception("Telegram automation deferred: %s", task.__name__)
        finally:
            close_old_connections()


def start_scheduler(stop_event):
    def run():
        while not stop_event.is_set():
            run_once()
            stop_event.wait(60)

    thread = threading.Thread(target=run, name="telegram-automation", daemon=True)
    thread.start()
    return thread
