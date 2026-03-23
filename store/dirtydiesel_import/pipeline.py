from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from django.db import transaction

from store.fassride_import.images import ImageAssetManager
from store.models import Product, ProductImage

from .matching import build_compact_sku_index, build_name_index, build_sku_index, match_catalog_product
from .reporting import save_json_report
from .source import DirtyDieselCatalogClient, load_source_products
from .types import ImportReport, SourceProduct

logger = logging.getLogger(__name__)

DEFAULT_EXCLUDED_CATEGORY_PREFIXES = ("fass-",)
PRODUCT_IMAGE_ALT_MAX_LENGTH = ProductImage._meta.get_field("alt").max_length or 0


class DirtyDieselImportPipeline:
    def __init__(
        self,
        *,
        supplier_label: str = "Dirty Diesel",
        category_slugs: list[str] | tuple[str, ...] = (),
        excluded_category_prefixes: list[str] | tuple[str, ...] = DEFAULT_EXCLUDED_CATEGORY_PREFIXES,
        apply_changes: bool = False,
        allow_name_match: bool = False,
        allow_embedded_code_match: bool = False,
        include_gallery_images: bool = True,
        limit: int = 0,
        replace_current_images: list[str] | tuple[str, ...] = (),
        replace_current_prefixes: list[str] | tuple[str, ...] = (),
        require_empty_current: bool = False,
        source_report_path: str = "",
        report_prefix: str = "store/import-reports/dirtydiesel",
        source_client: DirtyDieselCatalogClient | None = None,
        image_manager: ImageAssetManager | None = None,
    ) -> None:
        self.supplier_label = str(supplier_label or "Supplier").strip()
        self.category_slugs = tuple(dict.fromkeys(slug.strip() for slug in category_slugs if slug.strip()))
        self.excluded_category_prefixes = tuple(
            dict.fromkeys(prefix.strip() for prefix in excluded_category_prefixes if prefix.strip())
        )
        self.apply_changes = bool(apply_changes)
        self.allow_name_match = bool(allow_name_match)
        self.allow_embedded_code_match = bool(allow_embedded_code_match)
        self.include_gallery_images = bool(include_gallery_images)
        self.limit = max(int(limit), 0)
        self.explicit_replace_images = {value.strip() for value in replace_current_images if value and value.strip()}
        self.explicit_replace_prefixes = tuple(
            value.strip() for value in replace_current_prefixes if value and value.strip()
        )
        self.require_empty_current = bool(require_empty_current)
        self.source_report_path = source_report_path.strip()
        self.report_prefix = report_prefix.strip().strip("/") or "store/import-reports/dirtydiesel"
        self.source_client = source_client or DirtyDieselCatalogClient()
        self.image_manager = image_manager or ImageAssetManager(storage_prefix="store/imports/dirtydiesel/assets")
        self.run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    def run(self) -> ImportReport:
        report = ImportReport(
            assumptions=[
                "Only non-in-house products are considered.",
                "FASS categories are excluded by default so Dirty Diesel images do not overwrite the dedicated FASS supplier import.",
                "Exact SKU and compact SKU matches are treated as high confidence and auto-applied.",
                "Unambiguous supplier SKUs embedded in the internal product name can be treated as high confidence when explicitly enabled.",
                "Normalized-name matches are medium confidence and are only applied when --match-by-name is explicitly enabled.",
                f"Gallery imports add missing {self.supplier_label} images without duplicating existing gallery entries.",
            ]
        )

        products = list(self._target_products())
        source_products = (
            load_source_products(self.source_report_path)
            if self.source_report_path
            else self.source_client.fetch_catalog()
        )
        source_by_sku = build_sku_index(source_products)
        source_by_compact_sku = build_compact_sku_index(source_products)
        source_candidates, token_index = build_name_index(source_products)

        planned_updates: list[dict[str, Any]] = []
        summary = defaultdict(int)
        summary["target_products"] = len(products)
        summary["source_products"] = len(source_products)

        for product in products:
            summary["products_scanned"] += 1
            if not self._should_replace_product_image(product):
                summary["skipped_existing_images"] += 1
                continue
            match = match_catalog_product(
                product,
                source_by_sku=source_by_sku,
                source_by_compact_sku=source_by_compact_sku,
                source_candidates=source_candidates,
                token_index=token_index,
                allow_name_match=self.allow_name_match,
                allow_embedded_code_match=self.allow_embedded_code_match,
            )
            if match.reason.startswith("ambiguous_"):
                summary["ambiguous_matches"] += 1
                report.ambiguous_matches.append(
                    {
                        "sku": product.sku,
                        "name": product.name,
                        "category": getattr(product.category, "slug", ""),
                        "reason": match.reason,
                        "source_candidates": [candidate.to_dict() for candidate in match.alternatives],
                    }
                )
                continue
            if match.confidence == "low" or not match.source:
                summary["skipped_low_confidence"] += 1
                report.failures.append(
                    {
                        "sku": product.sku,
                        "name": product.name,
                        "category": getattr(product.category, "slug", ""),
                        "reason": match.reason,
                    }
                )
                continue

            usable_urls = self._validated_image_urls(match.source)
            if not usable_urls:
                summary["skipped_no_usable_image"] += 1
                report.failures.append(
                    {
                        "sku": product.sku,
                        "name": product.name,
                        "category": getattr(product.category, "slug", ""),
                        "reason": "no_usable_image",
                        "source_product_url": match.source.product_page_url,
                    }
                )
                continue

            gallery_urls = usable_urls[1:] if self.include_gallery_images else []
            main_image_name = self.image_manager.storage_name(usable_urls[0])
            gallery_image_names = [self.image_manager.storage_name(url) for url in gallery_urls]
            if not self._needs_update(product, main_image_name, gallery_image_names):
                summary["skipped_already_current"] += 1
                continue

            planned_updates.append(
                {
                    "product_id": product.pk,
                    "sku": product.sku,
                    "name": product.name,
                    "category": getattr(product.category, "slug", ""),
                    "confidence": match.confidence,
                    "match_reason": match.reason,
                    "source": match.source.to_dict(),
                    "main_image_url": usable_urls[0],
                    "gallery_image_urls": gallery_urls,
                }
            )
            summary["matched_exact"] += 1 if match.reason in {"exact_sku", "exact_compact_sku"} else 0
            summary["matched_embedded_code"] += 1 if match.reason == "embedded_source_sku" else 0
            summary["matched_name"] += 1 if match.reason == "normalized_name" else 0

        report.debug_files.update(self._save_debug_files(source_products, planned_updates))

        if self.apply_changes:
            summary["updated_products"] = self._apply_product_updates(products, planned_updates, report, summary)
        else:
            summary["planned_product_updates"] = len(planned_updates)

        report.summary = dict(summary)
        report_path = save_json_report(f"{self.report_prefix}/{self.run_id}/report.json", report.to_dict())
        report.debug_files["report"] = report_path
        return report

    def _target_products(self):
        queryset = (
            Product.objects.filter(is_in_house=False)
            .select_related("category")
            .prefetch_related("images")
            .order_by("category__slug", "sku")
        )
        for prefix in self.excluded_category_prefixes:
            queryset = queryset.exclude(category__slug__startswith=prefix)
        if self.category_slugs:
            queryset = queryset.filter(category__slug__in=self.category_slugs)
        if self.limit:
            queryset = queryset[: self.limit]
        return queryset

    def _validated_image_urls(self, source: SourceProduct) -> list[str]:
        usable: list[str] = []
        for url in self.image_manager.dedupe_urls(source.image_urls):
            check = self.image_manager.validate(url)
            if check.ok:
                usable.append(url)
        return usable

    def _should_replace_product_image(self, product: Product) -> bool:
        current_name = str(product.main_image.name or "").strip()
        if not current_name:
            return True
        if product.main_image_is_placeholder:
            return True
        if self.require_empty_current:
            return False
        if current_name in self.explicit_replace_images:
            return True
        if any(current_name.startswith(prefix) for prefix in self.explicit_replace_prefixes):
            return True
        if self.explicit_replace_images or self.explicit_replace_prefixes:
            return False
        return True

    def _needs_update(self, product: Product, main_image_name: str, gallery_image_names: list[str]) -> bool:
        current_main = str(product.main_image.name or "").strip()
        if current_main != main_image_name:
            return True
        existing_gallery = set(product.images.values_list("image", flat=True))
        return any(name not in existing_gallery for name in gallery_image_names)

    def _apply_product_updates(
        self,
        products: list[Product],
        planned_updates: list[dict[str, Any]],
        report: ImportReport,
        summary: defaultdict[str, int],
    ) -> int:
        product_by_id = {product.pk: product for product in products}
        updated = 0

        for row in planned_updates:
            product = product_by_id[row["product_id"]]
            main_image_name = self.image_manager.localize(row["main_image_url"])
            gallery_image_names = [self.image_manager.localize(url) for url in row["gallery_image_urls"]]
            gallery_alt = (
                product.name[:PRODUCT_IMAGE_ALT_MAX_LENGTH] if PRODUCT_IMAGE_ALT_MAX_LENGTH else product.name
            )
            changed = False

            with transaction.atomic():
                if product.main_image.name != main_image_name:
                    product.main_image = main_image_name
                    product.save()
                    changed = True

                existing_gallery = {item.image.name: item for item in product.images.all()}
                for sort_order, image_name in enumerate(gallery_image_names, start=1):
                    existing = existing_gallery.get(image_name)
                    if existing is not None:
                        image_changed = False
                        if existing.sort_order != sort_order:
                            existing.sort_order = sort_order
                            image_changed = True
                        if existing.alt != gallery_alt:
                            existing.alt = gallery_alt
                            image_changed = True
                        if image_changed:
                            existing.save()
                            changed = True
                        continue
                    ProductImage.objects.create(
                        product=product,
                        image=image_name,
                        alt=gallery_alt,
                        sort_order=sort_order,
                    )
                    changed = True

            if not changed:
                summary["skipped_already_current"] += 1
                continue

            report.updated_products.append(
                {
                    "sku": product.sku,
                    "name": product.name,
                    "category": getattr(product.category, "slug", ""),
                    "match_reason": row["match_reason"],
                    "confidence": row["confidence"],
                    "source_sku": row["source"]["sku"],
                    "source_product_name": row["source"]["product_name"],
                    "source_variant_name": row["source"]["variant_name"],
                    "source_product_url": row["source"]["product_page_url"],
                    "main_image": main_image_name,
                    "gallery_images": gallery_image_names,
                }
            )
            updated += 1
        return updated

    def _save_debug_files(
        self,
        source_products: list[SourceProduct],
        planned_updates: list[dict[str, Any]],
    ) -> dict[str, str]:
        base = f"{self.report_prefix}/{self.run_id}"
        source_path = save_json_report(
            f"{base}/source_products.json",
            {"products": [item.to_dict() for item in source_products]},
        )
        plan_path = save_json_report(
            f"{base}/match_plan.json",
            {"products": planned_updates},
        )
        return {
            "source_products": source_path,
            "match_plan": plan_path,
        }
