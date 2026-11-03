import hashlib
import time
import threading

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from telebot.apihelper import ApiTelegramException

from notifications import services
from notifications.models import TelegramBotSettings


class Command(BaseCommand):
    help = "Runs the Telegram bot long-polling worker."

    lock_namespace = "bgm-telegram-bot"

    def _pg_lock_id(self) -> int:
        digest = hashlib.sha256(self.lock_namespace.encode("utf-8")).digest()[:8]
        value = int.from_bytes(digest, "big", signed=False)
        if value > (2**63 - 1):
            value -= 2**64
        return value

    def _acquire_advisory_lock(self) -> bool:
        if connection.vendor != "postgresql":
            return True
        lock_id = self._pg_lock_id()
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(%s);", [lock_id])
            row = cursor.fetchone()
        return bool(row and row[0])

    def _release_advisory_lock(self):
        if connection.vendor != "postgresql":
            return
        lock_id = self._pg_lock_id()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s);", [lock_id])
        except Exception:
            return

    def handle(self, *args, **options):
        settings_obj = TelegramBotSettings.load_active()
        if not settings_obj:
            raise CommandError("Telegram bot is not configured or enabled.")

        while not self._acquire_advisory_lock():
            self.stdout.write(self.style.WARNING("Another bot instance is running. Waiting for lock..."))
            time.sleep(5)

        bot, _ = services.build_bot(settings_obj)  # reuse helpers for consistent options
        bot.delete_webhook(drop_pending_updates=True)
        allowed_ids = set(settings_obj.allowed_user_id_list)

        def _respond(message, text):
            from notifications.models import TelegramMessageLog
            return services.send_telegram_message(
                text,
                event_type=TelegramMessageLog.EVENT_MANUAL,
                chat_ids=[message.chat.id],
                dedupe_key=f"bot-reply:{message.chat.id}:{message.message_id}",
                entity_type="bot_command",
                entity_id=str(message.message_id),
            )

        def _authorized(message) -> bool:
            if not allowed_ids:
                return True
            user = getattr(message, "from_user", None)
            if not user:
                return False
            return user.id in allowed_ids

        @bot.message_handler(commands=["start", "help"])
        def _handle_start(message):
            if not _authorized(message):
                _respond(message, "Unauthorized.")
                return
            text = (
                "Hey! I'm the BGM operations bot.\n"
                "Use /today to see the current workload or /digest to push the summary "
                "to every configured chat."
            )
            _respond(message, text)

        @bot.message_handler(commands=["today"])
        def _handle_today(message):
            if not _authorized(message):
                _respond(message, "Unauthorized.")
                return
            _respond(message, services.build_operations_digest())

        @bot.message_handler(commands=["digest"])
        def _handle_digest(message):
            if not _authorized(message):
                _respond(message, "Unauthorized.")
                return
            delivered = services.send_daily_digest(force=True)
            if delivered:
                _respond(message, f"Digest sent to {delivered} chat(s).")
            else:
                _respond(message, "Digest queued or already sent; check the delivery log for details.")

        self.stdout.write(self.style.SUCCESS("Telegram bot is running. Press CTRL+C to stop."))
        from notifications.automation import start_scheduler
        stop_event = threading.Event()
        scheduler = start_scheduler(stop_event)
        try:
            while True:
                try:
                    bot.infinity_polling(skip_pending=True)
                except ApiTelegramException as exc:
                    if exc.error_code == 409:
                        self.stdout.write(
                            self.style.WARNING(
                                "Another bot instance is polling Telegram (409). Retrying in 5 seconds..."
                            )
                        )
                        time.sleep(5)
                        continue
                    raise
                except KeyboardInterrupt:
                    self.stdout.write(self.style.WARNING("Bot stopped by user."))
                    break
        finally:
            stop_event.set()
            scheduler.join(timeout=2)
            self._release_advisory_lock()
