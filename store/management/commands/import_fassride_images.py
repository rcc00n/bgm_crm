from __future__ import annotations

from django.core.management.base import BaseCommand

from store.fassride_import import DEFAULT_FASS_CATEGORY_SLUGS, FassrideImportPipeline


class Command(BaseCommand):
    help = "Import FASS product and category images from the authorized FASS source catalog."

    def add_arguments(self, parser):
        parser.add_argument(
            "--category-slug",
            action="append",
            dest="category_slugs",
            help="Internal category slug to target. Can be repeated. Defaults to the full FASS category set.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Apply changes. Without this flag the command runs in dry-run mode.",
        )
        parser.add_argument(
            "--match-by-name",
            action="store_true",
            help="Allow normalized-name fallback matching when exact SKU/part-number matching fails.",
        )
        parser.add_argument(
            "--skip-gallery",
            action="store_true",
            help="Only import the primary product image and skip gallery images.",
        )
        parser.add_argument(
            "--replace-current-image",
            action="append",
            default=[],
            help="Current image path that is allowed to be replaced. Can be repeated.",
        )

    def handle(self, *args, **options):
        category_slugs = options["category_slugs"] or list(DEFAULT_FASS_CATEGORY_SLUGS)
        pipeline = FassrideImportPipeline(
            category_slugs=category_slugs,
            apply_changes=options["apply"],
            allow_name_match=options["match_by_name"],
            include_gallery_images=not options["skip_gallery"],
            replace_current_images=options["replace_current_image"] or [],
        )
        report = pipeline.run()

        summary = report.summary
        self.stdout.write(
            self.style.SUCCESS(
                "FASS import complete "
                f"(dry_run={not options['apply']}, "
                f"products_scanned={summary.get('products_scanned', 0)}, "
                f"updated_products={summary.get('updated_products', summary.get('planned_product_updates', 0))}, "
                f"updated_categories={summary.get('updated_categories', summary.get('planned_category_updates', 0))}, "
                f"ambiguous={summary.get('ambiguous_matches', 0)}, "
                f"failures={len(report.failures)})"
            )
        )
        for label, path in sorted(report.debug_files.items()):
            self.stdout.write(f"{label}: {path}")
