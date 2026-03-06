from django.core.management.base import BaseCommand, CommandError

from core.services.printful import get_printful_merch_feed, get_printful_merch_product
from store.printful_catalog import sync_printful_merch_products


class Command(BaseCommand):
    help = "Refresh the local merch product mirror from the live Printful catalog."

    def add_arguments(self, parser):
        parser.add_argument(
            "--product-id",
            dest="product_ids",
            action="append",
            type=int,
            default=[],
            help="Sync only the given Printful product ID. Repeat for multiple products.",
        )

    def handle(self, *args, **options):
        product_ids = []
        seen_ids = set()
        for raw_id in options.get("product_ids") or []:
            normalized = int(raw_id or 0)
            if normalized <= 0 or normalized in seen_ids:
                continue
            seen_ids.add(normalized)
            product_ids.append(normalized)

        if product_ids:
            products = [get_printful_merch_product(product_id) for product_id in product_ids]
            products = [product for product in products if product]
            if not products:
                raise CommandError("Printful merch sync returned no products for the requested product IDs.")
            sync_printful_merch_products(products)
            self.stdout.write(self.style.SUCCESS(f"Synced {len(products)} Printful merch products."))
            return

        payload = get_printful_merch_feed(force_refresh=True)
        products = payload.get("products") if isinstance(payload, dict) else []
        error = (payload.get("error") or "").strip() if isinstance(payload, dict) else ""
        if error and not products:
            raise CommandError(f"Printful merch sync failed: {error}")
        if not isinstance(products, list) or not products:
            raise CommandError("Printful merch sync returned no products.")

        sync_printful_merch_products(products)
        self.stdout.write(self.style.SUCCESS(f"Synced {len(products)} Printful merch products."))
