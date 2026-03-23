from __future__ import annotations

from django.core.management.base import BaseCommand

from store.dirtydiesel_import import DEFAULT_EXCLUDED_CATEGORY_PREFIXES, DirtyDieselImportPipeline


class Command(BaseCommand):
    help = "Import non-in-house product images from the authorized Dirty Diesel catalog."

    def add_arguments(self, parser):
        parser.add_argument(
            "--category-slug",
            action="append",
            dest="category_slugs",
            help="Internal category slug to target. Can be repeated.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Apply changes. Without this flag the command runs in dry-run mode.",
        )
        parser.add_argument(
            "--match-by-name",
            action="store_true",
            help="Allow conservative normalized-name fallback matching when exact SKU matching fails.",
        )
        parser.add_argument(
            "--match-by-embedded-code",
            action="store_true",
            help="Allow unambiguous exact supplier SKU matches embedded in the internal product name.",
        )
        parser.add_argument(
            "--skip-gallery",
            action="store_true",
            help="Only import the primary product image and skip gallery images.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Optional max number of internal products to scan.",
        )
        parser.add_argument(
            "--include-fass",
            action="store_true",
            help="Include FASS categories in the target set. By default they are excluded.",
        )
        parser.add_argument(
            "--source-cache",
            default="",
            help="Reuse a previously saved source_products.json report instead of fetching the supplier again.",
        )
        parser.add_argument(
            "--replace-current-image",
            action="append",
            default=[],
            help="Only replace products whose current image exactly matches this value. Can be repeated.",
        )
        parser.add_argument(
            "--replace-current-prefix",
            action="append",
            default=[],
            help="Only replace products whose current image starts with this prefix. Can be repeated.",
        )
        parser.add_argument(
            "--empty-only",
            action="store_true",
            help="Only fill products with empty main images or placeholders.",
        )

    def handle(self, *args, **options):
        excluded_category_prefixes = [] if options["include_fass"] else list(DEFAULT_EXCLUDED_CATEGORY_PREFIXES)
        pipeline = DirtyDieselImportPipeline(
            supplier_label="Dirty Diesel",
            category_slugs=options["category_slugs"] or [],
            excluded_category_prefixes=excluded_category_prefixes,
            apply_changes=options["apply"],
            allow_name_match=options["match_by_name"],
            allow_embedded_code_match=options["match_by_embedded_code"],
            include_gallery_images=not options["skip_gallery"],
            limit=options["limit"] or 0,
            replace_current_images=options["replace_current_image"] or [],
            replace_current_prefixes=options["replace_current_prefix"] or [],
            require_empty_current=options["empty_only"],
            source_report_path=options["source_cache"] or "",
        )
        report = pipeline.run()

        summary = report.summary
        self.stdout.write(
            self.style.SUCCESS(
                "Dirty Diesel import complete "
                f"(dry_run={not options['apply']}, "
                f"products_scanned={summary.get('products_scanned', 0)}, "
                f"updated_products={summary.get('updated_products', summary.get('planned_product_updates', 0))}, "
                f"ambiguous={summary.get('ambiguous_matches', 0)}, "
                f"failures={len(report.failures)})"
            )
        )
        for label, path in sorted(report.debug_files.items()):
            self.stdout.write(f"{label}: {path}")
