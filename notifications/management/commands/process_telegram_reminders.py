from django.core.management.base import BaseCommand

from notifications import services


class Command(BaseCommand):
    help = "Sends pending Telegram reminders that are due."

    def handle(self, *args, **options):
        processed = services.process_due_reminders()
        if processed:
            self.stdout.write(self.style.SUCCESS(f"Processed {processed} reminder(s)."))
        else:
            self.stdout.write("No due reminders.")
