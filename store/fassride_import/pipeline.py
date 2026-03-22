from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from django.db import transaction

from store.models import Category, Product, ProductImage

from .images import ImageAssetManager
from .matching import build_part_number_index, match_catalog_product
from .reporting import save_json_report
from .source import FassrideApiClient
from .types import CuratedCategoryImage, ImportReport, SourceProduct

logger = logging.getLogger(__name__)

DEFAULT_FASS_CATEGORY_SLUGS = (
    "fass-accessories",
    "fass-competition-series",
    "fass-drop-in-series",
    "fass-filters",
    "fass-fuel-line-fittings",
    "fass-fuel-pumps",
    "fass-fuel-systems",
    "fass-industrial-series",
    "fass-mounting-packages",
    "fass-replacement-parts",
    "fass-replacement-pumps",
)


class FassrideImportPipeline:
    def __init__(
        self,
        *,
        category_slugs: list[str] | tuple[str, ...] = DEFAULT_FASS_CATEGORY_SLUGS,
        apply_changes: bool = False,
        allow_name_match: bool = False,
        include_gallery_images: bool = True,
        replace_current_images: list[str] | tuple[str, ...] = (),
        report_prefix: str = "store/import-reports/fassride",
        source_client: FassrideApiClient | None = None,
        image_manager: ImageAssetManager | None = None,
    ) -> None:
        self.category_slugs = tuple(dict.fromkeys(slug.strip() for slug in category_slugs if slug.strip()))
        self.apply_changes = bool(apply_changes)
        self.allow_name_match = bool(allow_name_match)
        self.include_gallery_images = bool(include_gallery_images)
        self.report_prefix = report_prefix.strip().strip("/") or "store/import-reports/fassride"
        self.source_client = source_client or FassrideApiClient()
        self.image_manager = image_manager or ImageAssetManager()
        self.explicit_replace_images = {value.strip() for value in replace_current_images if value and value.strip()}
        self.run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    def run(self) -> ImportReport:
        report = ImportReport(
            assumptions=[
                "Only high-confidence exact SKU/part-number matches are auto-applied unless name matching is explicitly enabled.",
                "Configured category cover overrides use curated FASS page assets from authorized source pages before product-derived cover candidates.",
                "Other category cover images are sourced from the strongest successfully matched product image in that internal category.",
                "Products with unique non-placeholder images are left untouched unless their current image matches the configured replace list.",
            ]
        )

        categories = list(Category.objects.filter(slug__in=self.category_slugs).order_by("slug"))
        products = list(
            Product.objects.filter(category__slug__in=self.category_slugs)
            .select_related("category")
            .prefetch_related("images")
            .order_by("category__slug", "sku")
        )

        allowed_replace_images = set(self.explicit_replace_images)
        allowed_replace_images.update(
            str(category.image.name or "").strip()
            for category in categories
            if self._category_image_is_replaceable_seed(category)
        )

        source_products = self.source_client.fetch_catalog()
        curated_category_covers = self.source_client.fetch_curated_category_covers(category_slugs=self.category_slugs)
        source_by_part_number = build_part_number_index(source_products)

        planned_updates: list[dict[str, Any]] = []
        category_cover_candidates: dict[int, list[dict[str, Any]]] = defaultdict(list)

        summary = defaultdict(int)
        summary["target_categories"] = len(categories)
        summary["target_products"] = len(products)
        summary["source_products"] = len(source_products)

        for product in products:
            summary["products_scanned"] += 1
            if not self._should_replace_product_image(product, allowed_replace_images):
                summary["skipped_existing_images"] += 1
                report.failures.append(
                    {
                        "sku": product.sku,
                        "name": product.name,
                        "category": product.category.slug,
                        "reason": "existing_non_generic_image",
                    }
                )
                continue

            match = match_catalog_product(
                product,
                source_by_part_number=source_by_part_number,
                source_products=source_products,
                allow_name_match=self.allow_name_match,
            )
            if match.confidence == "low" or not match.source:
                summary["skipped_low_confidence"] += 1
                report.failures.append(
                    {
                        "sku": product.sku,
                        "name": product.name,
                        "category": product.category.slug,
                        "reason": match.reason,
                    }
                )
                continue
            if match.reason == "ambiguous_name_match":
                summary["ambiguous_matches"] += 1
                report.ambiguous_matches.append(
                    {
                        "sku": product.sku,
                        "name": product.name,
                        "category": product.category.slug,
                        "reason": match.reason,
                        "source_candidates": [candidate.to_dict() for candidate in match.alternatives],
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
                        "category": product.category.slug,
                        "reason": "no_usable_image",
                        "source_product_url": match.source.product_page_url,
                    }
                )
                continue

            gallery_urls = usable_urls[1:] if self.include_gallery_images else []
            plan_row = {
                "product_id": product.pk,
                "sku": product.sku,
                "name": product.name,
                "category": product.category.slug,
                "confidence": match.confidence,
                "match_reason": match.reason,
                "source": match.source.to_dict(),
                "previous_main_image": str(product.main_image.name or "").strip(),
                "main_image_url": usable_urls[0],
                "gallery_image_urls": gallery_urls,
            }
            planned_updates.append(plan_row)
            category_cover_candidates[product.category_id].append(plan_row)
            summary["matched_exact"] += 1 if match.reason == "exact_sku" else 0
            summary["matched_name"] += 1 if match.reason != "exact_sku" else 0

        for category in categories:
            curated_cover = curated_category_covers.get(category.slug)
            if curated_cover is None:
                continue
            category_cover_candidates[category.pk].append(self._build_curated_category_cover_plan(curated_cover))

        report_paths = self._save_debug_files(source_products, planned_updates)
        report.debug_files.update(report_paths)

        if self.apply_changes:
            updated_products = self._apply_product_updates(products, planned_updates, report, summary)
            self._apply_category_updates(categories, category_cover_candidates, report, summary)
            summary["updated_products"] = updated_products
        else:
            summary["planned_product_updates"] = len(planned_updates)
            summary["planned_category_updates"] = sum(
                1
                for category in categories
                if self._category_cover_needs_update(
                    category,
                    category_cover_candidates.get(category.pk) or [],
                    allowed_replace_images,
                )
            )

        report.summary = dict(summary)
        report_path = save_json_report(f"{self.report_prefix}/{self.run_id}/report.json", report.to_dict())
        report.debug_files["report"] = report_path
        return report

    def _validated_image_urls(self, source: SourceProduct) -> list[str]:
        usable: list[str] = []
        for url in self.image_manager.dedupe_urls(source.image_urls):
            check = self.image_manager.validate(url)
            if check.ok:
                usable.append(url)
        return usable

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

            with transaction.atomic():
                if product.main_image.name != main_image_name:
                    product.main_image = main_image_name
                    product.save()

                existing_gallery = {item.image.name: item for item in product.images.all()}
                for sort_order, image_name in enumerate(gallery_image_names, start=1):
                    existing = existing_gallery.get(image_name)
                    if existing is not None:
                        changed = False
                        if existing.sort_order != sort_order:
                            existing.sort_order = sort_order
                            changed = True
                        if existing.alt != product.name:
                            existing.alt = product.name
                            changed = True
                        if changed:
                            existing.save()
                        continue
                    ProductImage.objects.create(
                        product=product,
                        image=image_name,
                        alt=product.name,
                        sort_order=sort_order,
                    )

            report.updated_products.append(
                {
                    "sku": product.sku,
                    "name": product.name,
                    "category": product.category.slug,
                    "match_reason": row["match_reason"],
                    "confidence": row["confidence"],
                    "source_part_number": row["source"]["part_number"],
                    "source_product_url": row["source"]["product_page_url"],
                    "main_image": main_image_name,
                    "gallery_images": gallery_image_names,
                }
            )
            updated += 1
        return updated

    def _apply_category_updates(
        self,
        categories: list[Category],
        category_cover_candidates: dict[int, list[dict[str, Any]]],
        report: ImportReport,
        summary: defaultdict[str, int],
    ) -> None:
        allowed_replace_images = set(self.explicit_replace_images)
        allowed_replace_images.update(
            str(category.image.name or "").strip()
            for category in categories
            if self._category_image_is_replaceable_seed(category)
        )
        for category in categories:
            candidates = category_cover_candidates.get(category.pk) or []
            cover = self._select_category_cover_candidate(candidates)
            if cover is None:
                continue
            if not self._should_replace_category_image_for_source(
                category,
                allowed_replace_images,
                source_kind=str(cover.get("source_kind") or "product"),
            ):
                summary["skipped_existing_category_images"] += 1
                continue
            image_name = self.image_manager.storage_name(cover["main_image_url"])
            if category.image.name == image_name:
                continue
            image_name = self.image_manager.localize(cover["main_image_url"])
            if category.image.name != image_name:
                category.image = image_name
                category.save()
            report.updated_categories.append(
                self._build_category_update_report_row(category, cover, image_name)
            )
            summary["updated_categories"] += 1

    def _should_replace_product_image(self, product: Product, allowed_replace_images: set[str]) -> bool:
        current_name = str(product.main_image.name or "").strip()
        if not current_name:
            return True
        if product.main_image_is_placeholder:
            return True
        if current_name in allowed_replace_images:
            return True
        category_name = str(getattr(product.category.image, "name", "") or "").strip()
        if not category_name or category_name.startswith(f"{self.image_manager.storage_prefix}/"):
            return False
        return current_name == category_name

    def _should_replace_category_image(self, category: Category, allowed_replace_images: set[str]) -> bool:
        return self._should_replace_category_image_for_source(
            category,
            allowed_replace_images,
            source_kind="product",
        )

    def _should_replace_category_image_for_source(
        self,
        category: Category,
        allowed_replace_images: set[str],
        *,
        source_kind: str,
    ) -> bool:
        current_name = str(getattr(category.image, "name", "") or "").strip()
        if not current_name:
            return True
        placeholder_dir = "store/placeholders/"
        if current_name.startswith(placeholder_dir):
            return True
        if source_kind == "curated_page_asset" and current_name.startswith(f"{self.image_manager.storage_prefix}/"):
            return True
        return current_name in allowed_replace_images

    def _category_image_is_replaceable_seed(self, category: Category) -> bool:
        current_name = str(getattr(category.image, "name", "") or "").strip()
        if not current_name:
            return False
        if current_name.startswith(f"{self.image_manager.storage_prefix}/"):
            return False
        return True

    def _build_curated_category_cover_plan(self, asset: CuratedCategoryImage) -> dict[str, Any]:
        return {
            "source_kind": "curated_page_asset",
            "cover_priority": 100,
            "main_image_url": asset.image_url,
            "gallery_image_urls": [],
            "source_page_url": asset.source_page_url,
            "source_label": asset.label,
        }

    def _select_category_cover_candidate(self, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda item: (
                int(item.get("cover_priority", 0)),
                len(item.get("gallery_image_urls") or []),
                str(item.get("sku") or ""),
            ),
        )

    def _category_cover_needs_update(
        self,
        category: Category,
        candidates: list[dict[str, Any]],
        allowed_replace_images: set[str],
    ) -> bool:
        cover = self._select_category_cover_candidate(candidates)
        if cover is None:
            return False
        image_name = self.image_manager.storage_name(cover["main_image_url"])
        if str(getattr(category.image, "name", "") or "").strip() == image_name:
            return False
        return self._should_replace_category_image_for_source(
            category,
            allowed_replace_images,
            source_kind=str(cover.get("source_kind") or "product"),
        )

    def _build_category_update_report_row(
        self,
        category: Category,
        cover: dict[str, Any],
        image_name: str,
    ) -> dict[str, Any]:
        row = {
            "slug": category.slug,
            "name": category.name,
            "image": image_name,
            "source_kind": str(cover.get("source_kind") or "product"),
        }
        if row["source_kind"] == "curated_page_asset":
            row["source_label"] = cover.get("source_label") or ""
            row["source_page_url"] = cover.get("source_page_url") or ""
            return row
        row["source_product_sku"] = cover["sku"]
        row["source_part_number"] = cover["source"]["part_number"]
        row["source_product_url"] = cover["source"]["product_page_url"]
        return row

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
