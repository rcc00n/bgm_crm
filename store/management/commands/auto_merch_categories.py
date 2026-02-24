from __future__ import annotations

from django.core.management.base import BaseCommand

from core.services.printful import get_printful_merch_feed
from store.models import MerchCategory, Product
from store.utils_merch import normalize_merch_category


def _build_printful_product_sku(product_id: int) -> str:
    return f"PF-{product_id}"


class Command(BaseCommand):
    help = "Auto-assign merch categories to Printful products."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite existing merch_category assignments.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report changes without saving.",
        )

    def handle(self, *args, **options):
        force = bool(options.get("force"))
        dry_run = bool(options.get("dry_run"))

        feed = get_printful_merch_feed(force_refresh=True)
        products = feed.get("products", []) if isinstance(feed, dict) else []
        if not products:
            self.stdout.write(self.style.WARNING("No Printful products returned."))
            return

        merch_categories = list(MerchCategory.objects.all())
        merch_by_slug = {(cat.slug or "").strip().lower(): cat for cat in merch_categories if cat.slug}
        merch_by_name = {(cat.name or "").strip().lower(): cat for cat in merch_categories if cat.name}

        created = 0
        updated = 0
        skipped = 0
        missing = 0

        for item in products:
            try:
                product_id = int(item.get("id") or 0)
            except (TypeError, ValueError):
                product_id = 0
            if product_id <= 0:
                continue

            sku = _build_printful_product_sku(product_id)
            product = Product.objects.filter(sku=sku).select_related("merch_category").first()
            if not product:
                missing += 1
                continue

            if product.merch_category_id and not force:
                skipped += 1
                continue

            label_source = (item.get("category_label") or item.get("name") or "").strip()
            category_key, category_label = normalize_merch_category(label_source)
            if not category_label:
                skipped += 1
                continue

            key = (category_key or "").strip().lower()
            name_key = category_label.strip().lower()
            category = merch_by_slug.get(key) or merch_by_name.get(name_key)

            if not category:
                if not dry_run:
                    category = MerchCategory.objects.create(
                        name=category_label,
                        slug=category_key or "",
                        is_active=True,
                    )
                else:
                    category = MerchCategory(name=category_label, slug=category_key or "")
                merch_by_slug[(category.slug or "").strip().lower()] = category
                merch_by_name[(category.name or "").strip().lower()] = category
                created += 1

            if not dry_run:
                product.merch_category = category
                product.save(update_fields=["merch_category"])
            updated += 1

        summary = (
            f"Auto merch categories complete. "
            f"updated={updated}, created_categories={created}, skipped={skipped}, missing_products={missing}"
        )
        self.stdout.write(self.style.SUCCESS(summary))
