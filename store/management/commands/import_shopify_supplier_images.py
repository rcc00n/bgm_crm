from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils.text import slugify

from store.dirtydiesel_import.pipeline import DEFAULT_EXCLUDED_CATEGORY_PREFIXES, DirtyDieselImportPipeline
from store.dirtydiesel_import.source import DirtyDieselCatalogClient
from store.fassride_import.images import ImageAssetManager


class Command(BaseCommand):
    help = "Import non-in-house product images from a Shopify supplier catalog."

    def add_arguments(self, parser):
        parser.add_argument("--supplier-name", required=True, help="Display label for the supplier.")
        parser.add_argument("--base-url", required=True, help="Shopify storefront base URL.")
        parser.add_argument("--storage-prefix", required=True, help="Image storage prefix to save localized files under.")
        parser.add_argument(
            "--report-prefix",
            default="",
            help="Optional report prefix. Defaults to store/import-reports/<supplier-name-slug>.",
        )
        parser.add_argument(
            "--source-cache",
            default="",
            help="Reuse a previously saved source_products.json report instead of fetching the supplier again.",
        )
        parser.add_argument(
            "--category-slug",
            action="append",
            dest="category_slugs",
            help="Internal category slug to target. Can be repeated.",
        )
        parser.add_argument("--apply", action="store_true", help="Apply changes. Without this flag the run is dry-run.")
        parser.add_argument(
            "--match-by-name",
            action="store_true",
            help="Allow conservative normalized-name fallback matching when exact SKU matching fails.",
        )
        parser.add_argument("--skip-gallery", action="store_true", help="Only import the primary product image.")
        parser.add_argument("--limit", type=int, default=0, help="Optional max number of internal products to scan.")
        parser.add_argument(
            "--include-fass",
            action="store_true",
            help="Include FASS categories in the target set. By default they are excluded.",
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
        supplier_name = options["supplier_name"].strip()
        report_prefix = options["report_prefix"].strip() or f"store/import-reports/{slugify(supplier_name) or 'supplier'}"
        excluded_category_prefixes = [] if options["include_fass"] else list(DEFAULT_EXCLUDED_CATEGORY_PREFIXES)

        pipeline = DirtyDieselImportPipeline(
            supplier_label=supplier_name,
            category_slugs=options["category_slugs"] or [],
            excluded_category_prefixes=excluded_category_prefixes,
            apply_changes=options["apply"],
            allow_name_match=options["match_by_name"],
            include_gallery_images=not options["skip_gallery"],
            limit=options["limit"] or 0,
            replace_current_images=options["replace_current_image"] or [],
            replace_current_prefixes=options["replace_current_prefix"] or [],
            require_empty_current=options["empty_only"],
            source_report_path=options["source_cache"] or "",
            report_prefix=report_prefix,
            source_client=DirtyDieselCatalogClient(
                base_url=options["base_url"],
                catalog_label=supplier_name,
            ),
            image_manager=ImageAssetManager(storage_prefix=options["storage_prefix"]),
        )
        report = pipeline.run()
        summary = report.summary
        self.stdout.write(
            self.style.SUCCESS(
                f"{supplier_name} import complete "
                f"(dry_run={not options['apply']}, "
                f"products_scanned={summary.get('products_scanned', 0)}, "
                f"updated_products={summary.get('updated_products', summary.get('planned_product_updates', 0))}, "
                f"ambiguous={summary.get('ambiguous_matches', 0)}, "
                f"failures={len(report.failures)})"
            )
        )
        for label, path in sorted(report.debug_files.items()):
            self.stdout.write(f"{label}: {path}")
