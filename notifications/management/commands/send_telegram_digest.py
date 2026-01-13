from django.core.management.base import BaseCommand

from notifications import services


class Command(BaseCommand):
    help = "Sends the daily Telegram digest when enabled."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Ignore schedule and send the digest immediately.",
        )

    def handle(self, *args, **options):
        delivered = services.send_daily_digest(force=options["force"])
        if delivered:
            self.stdout.write(self.style.SUCCESS(f"Digest sent to {delivered} chat(s)."))
        else:
            self.stdout.write("Digest not sent (check configuration or already sent today).")
