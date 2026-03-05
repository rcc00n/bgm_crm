from django.core.management.base import BaseCommand, CommandError

from core.services.printful import PrintfulAPIError
from store.printful_fulfillment import sync_printful_webhook_subscription


class Command(BaseCommand):
    help = "Create or update the Printful webhook subscription for this store."

    def handle(self, *args, **options):
        try:
            payload = sync_printful_webhook_subscription()
        except PrintfulAPIError as exc:
            raise CommandError(f"Printful webhook sync failed: {exc}") from exc

        self.stdout.write(self.style.SUCCESS("Printful webhook synced."))
        self.stdout.write(str(payload))
