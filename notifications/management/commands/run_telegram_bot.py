from django.core.management.base import BaseCommand, CommandError

from notifications import services
from notifications.models import TelegramBotSettings


class Command(BaseCommand):
    help = "Runs the Telegram bot long-polling worker."

    def handle(self, *args, **options):
        settings_obj = TelegramBotSettings.load_active()
        if not settings_obj:
            raise CommandError("Telegram bot is not configured or enabled.")

        bot, _ = services.build_bot(settings_obj)  # reuse helpers for consistent options
        allowed_ids = set(settings_obj.allowed_user_id_list)

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
                bot.reply_to(message, "Unauthorized.")
                return
            text = (
                "Hey! I'm the BGM operations bot.\n"
                "Use /today to see the current workload or /digest to push the summary "
                "to every configured chat."
            )
            bot.reply_to(message, text)

        @bot.message_handler(commands=["today"])
        def _handle_today(message):
            if not _authorized(message):
                bot.reply_to(message, "Unauthorized.")
                return
            bot.send_message(message.chat.id, services.build_operations_digest(), disable_web_page_preview=True)

        @bot.message_handler(commands=["digest"])
        def _handle_digest(message):
            if not _authorized(message):
                bot.reply_to(message, "Unauthorized.")
                return
            delivered = services.send_daily_digest(force=True)
            if delivered:
                bot.reply_to(message, f"Digest sent to {delivered} chat(s).")
            else:
                bot.reply_to(message, "Digest not sent (check configuration).")

        self.stdout.write(self.style.SUCCESS("Telegram bot is running. Press CTRL+C to stop."))
        try:
            bot.infinity_polling(skip_pending=True)
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("Bot stopped by user."))
