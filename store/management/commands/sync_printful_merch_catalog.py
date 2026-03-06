from django.core.management.base import BaseCommand, CommandError

from accounts.views import _sync_printful_merch_products
from core.services.printful import get_printful_merch_feed


class Command(BaseCommand):
    help = "Refresh the local merch product mirror from the live Printful catalog."

    def handle(self, *args, **options):
        payload = get_printful_merch_feed(force_refresh=True)
        products = payload.get("products") if isinstance(payload, dict) else []
        error = (payload.get("error") or "").strip() if isinstance(payload, dict) else ""
        if error and not products:
            raise CommandError(f"Printful merch sync failed: {error}")
        if not isinstance(products, list) or not products:
            raise CommandError("Printful merch sync returned no products.")

        _sync_printful_merch_products(products)
        self.stdout.write(self.style.SUCCESS(f"Synced {len(products)} Printful merch products."))
