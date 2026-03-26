from __future__ import annotations

from contextlib import nullcontext

from django.core.management.base import BaseCommand
from django.db import transaction

from store.fitment import (
    AUTO_GENERATED_COMPATIBILITY_NOTES,
    infer_fitment,
    resolve_fitment_models,
    suggested_category_name,
    sync_consumer_vehicle_catalog,
)
from store.models import Category, Product


class Command(BaseCommand):
    help = (
        "Sync the consumer truck/SUV vehicle catalog and normalize fitment data for non-merch products. "
        "Dry-run by default; pass --apply to write changes."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write the catalog, category, and compatibility changes.",
        )
        parser.add_argument(
            "--include-inactive",
            action="store_true",
            help="Process inactive non-merch products as well. Default: active products only.",
        )
        parser.add_argument(
            "--skip-category-cleanup",
            action="store_true",
            help="Leave active uncategorized products in their current category.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Only process the first N non-merch products for spot checks.",
        )

    def handle(self, *args, **options):
        apply = bool(options["apply"])
        include_inactive = bool(options["include_inactive"])
        skip_category_cleanup = bool(options["skip_category_cleanup"])
        limit = max(int(options["limit"] or 0), 0)

        catalog_summary = sync_consumer_vehicle_catalog(apply=apply)
        self.stdout.write(
            self.style.NOTICE(
                "Vehicle catalog sync: "
                f"legacy_normalized={catalog_summary['legacy_records_normalized']} "
                f"makes_created={catalog_summary['makes_created']} "
                f"models_created={catalog_summary['models_created']}"
            )
        )

        queryset = (
            Product.objects.select_related("category")
            .prefetch_related("compatible_models__make")
            .exclude(category__slug="merch")
            .exclude(sku__startswith="PF-")
            .exclude(slug__startswith="merch-")
            .order_by("id")
        )
        if not include_inactive:
            queryset = queryset.filter(is_active=True)
        if limit:
            queryset = queryset[:limit]

        categories_by_name = {}
        if not skip_category_cleanup:
            categories_by_name = {category.name: category for category in Category.objects.all()}

        summary = {
            "scanned": 0,
            "specific": 0,
            "universal": 0,
            "commercial": 0,
            "products_updated": 0,
            "fitment_updates": 0,
            "note_updates": 0,
            "category_updates": 0,
        }
        changed_examples: list[str] = []

        write_context = transaction.atomic() if apply else nullcontext()
        with write_context:
            for product in queryset:
                summary["scanned"] += 1
                inference = infer_fitment(
                    name=product.name,
                    sku=product.sku,
                    category_name=getattr(product.category, "name", ""),
                )
                summary[inference.kind] += 1

                current_models = {
                    (
                        model.make.name,
                        model.name,
                        model.year_from,
                        model.year_to,
                    )
                    for model in product.compatible_models.all()
                }
                target_models = {
                    (
                        spec.make,
                        spec.model,
                        spec.year_from,
                        spec.year_to,
                    )
                    for spec in inference.specs
                }

                current_note = (product.compatibility or "").strip()
                target_note = self._desired_note(current_note=current_note, inferred_kind=inference.kind, inferred_note=inference.note)

                target_category = None
                if not skip_category_cleanup:
                    suggested_name = suggested_category_name(
                        current_category_name=getattr(product.category, "name", ""),
                        product_name=product.name,
                    )
                    if suggested_name:
                        target_category = categories_by_name.get(suggested_name)

                category_changed = bool(target_category and product.category_id != target_category.id)
                fitment_changed = current_models != target_models
                note_changed = current_note != target_note

                if not any((category_changed, fitment_changed, note_changed)):
                    continue

                summary["products_updated"] += 1
                if fitment_changed:
                    summary["fitment_updates"] += 1
                if note_changed:
                    summary["note_updates"] += 1
                if category_changed:
                    summary["category_updates"] += 1

                if len(changed_examples) < 25:
                    changed_examples.append(
                        f"{product.id} | {product.name} | {inference.kind} | "
                        f"fitments={len(target_models)} | "
                        f"category={'unchanged' if not category_changed else target_category.name}"
                    )

                if not apply:
                    continue

                if fitment_changed:
                    resolved_models = resolve_fitment_models(specs=inference.specs)
                    product.compatible_models.set(resolved_models)

                update_fields: list[str] = []
                if note_changed:
                    product.compatibility = target_note
                    update_fields.append("compatibility")
                if category_changed and target_category is not None:
                    product.category = target_category
                    update_fields.append("category")
                if update_fields:
                    product.save(update_fields=update_fields)

        mode_label = "APPLY" if apply else "DRY-RUN"
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"{mode_label} complete"))
        for key in (
            "scanned",
            "specific",
            "universal",
            "commercial",
            "products_updated",
            "fitment_updates",
            "note_updates",
            "category_updates",
        ):
            self.stdout.write(f"{key}: {summary[key]}")

        if changed_examples:
            self.stdout.write("")
            self.stdout.write("Example changes:")
            for line in changed_examples:
                self.stdout.write(f"- {line}")

        if not apply:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    "Dry-run only. Re-run with --apply to write the normalized fitment data."
                )
            )

    @staticmethod
    def _desired_note(*, current_note: str, inferred_kind: str, inferred_note: str) -> str:
        current = (current_note or "").strip()
        if inferred_kind == "specific":
            return "" if current in AUTO_GENERATED_COMPATIBILITY_NOTES else current
        if current and current not in AUTO_GENERATED_COMPATIBILITY_NOTES:
            return current
        return inferred_note
