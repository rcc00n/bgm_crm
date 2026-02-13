from __future__ import annotations

import csv
import sys
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from store.models import Product, ProductOption


MERCH_CATEGORY_SLUGS = {
    # BGM merch
    "merch",
    # Common vendor/apparel categories (defensive: user requested "do not touch merch").
    "apparel",
    "t-shirt",
    "tshirts",
    "hoodie",
    "hoodies",
    "hat",
    "hats",
    "sticker",
    "stickers",
    "sweater",
    "crewneck",
    "beanie",
}

MERCH_CATEGORY_NAME_HINTS = (
    "merch",
    "apparel",
    "t-shirt",
    "tshirt",
    "hoodie",
    "hat",
    "sticker",
    "sweater",
    "crewneck",
    "beanie",
)


def _is_merch_product(product: Product) -> bool:
    sku = (getattr(product, "sku", "") or "").strip().upper()
    slug = (getattr(product, "slug", "") or "").strip().lower()
    category = getattr(product, "category", None)
    category_slug = (getattr(category, "slug", "") or "").strip().lower()
    category_name = (getattr(category, "name", "") or "").strip().lower()
    tags = [str(t).strip().lower() for t in (getattr(product, "tags", None) or []) if str(t).strip()]

    if sku.startswith("PF-"):
        return True
    if slug.startswith("merch-"):
        return True
    if category_slug in MERCH_CATEGORY_SLUGS:
        return True
    if any(hint in category_name for hint in MERCH_CATEGORY_NAME_HINTS):
        return True
    if "merch" in tags or "apparel" in tags:
        return True
    return False


def _pick_primary_image_url(group: List[Dict[str, str]]) -> str:
    """
    Shopify-like imports can contain multiple rows per handle.
    We pick the best image deterministically:
    - Sort by Image Position (lowest wins), tie-breaking by earliest occurrence.
    - Deduplicate URLs while preserving the best-positioned occurrence.
    """
    best_by_url: Dict[str, Tuple[int, int]] = {}
    for idx, row in enumerate(group):
        raw = (row.get("Image Src") or row.get("Variant Image") or "").strip()
        if not raw:
            continue
        pos_raw = (row.get("Image Position") or "").strip()
        try:
            pos = int(pos_raw) if pos_raw else 10**9
        except Exception:
            pos = 10**9
        key = (pos, idx)
        if raw not in best_by_url or key < best_by_url[raw]:
            best_by_url[raw] = key
    if not best_by_url:
        return ""
    best_url, _key = min(best_by_url.items(), key=lambda kv: kv[1])
    return best_url


def _iter_candidate_skus(group: List[Dict[str, str]], *, limit: int = 50) -> List[str]:
    """
    Return unique SKU candidates from Shopify-like rows in stable order.
    We use these for fallback matching against Product.sku and ProductOption.sku.
    """
    out: List[str] = []
    seen = set()
    for row in group:
        sku = (row.get("SKU") or row.get("Variant SKU") or "").strip()
        if not sku or sku in seen:
            continue
        out.append(sku)
        seen.add(sku)
        if len(out) >= limit:
            break
    return out


def _iter_shopify_groups(rows: Iterable[Dict[str, str]]):
    grouped: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for row in rows:
        handle = (row.get("Handle") or row.get("handle") or "").strip()
        if not handle:
            handle = (row.get("Title") or row.get("title") or "").strip()
        if not handle:
            continue
        grouped[handle].append(row)
    return grouped.items()


@dataclass
class ImportStats:
    updated: int = 0
    unchanged: int = 0
    skipped_merch: int = 0
    skipped_missing: int = 0
    skipped_no_image: int = 0


class Command(BaseCommand):
    help = (
        "Import product main images from a Shopify-like CSV (e.g. DDC load file). "
        "Updates existing products only and stores remote URLs directly in Product.main_image."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv",
            dest="csv_path",
            default="",
            help="Path to a CSV file (inside the container). Use --stdin to stream data instead.",
        )
        parser.add_argument(
            "--stdin",
            action="store_true",
            help="Read CSV from stdin (recommended for Dokku runs).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse + match, but do not write to the database.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Optional max number of products to update (0 = no limit).",
        )
        parser.add_argument(
            "--show",
            type=int,
            default=25,
            help="Show up to N planned updates/misses in output (default: 25).",
        )

    def handle(self, *args, **options):
        csv_path = (options.get("csv_path") or "").strip()
        use_stdin = bool(options.get("stdin"))
        dry_run = bool(options.get("dry_run"))
        limit = int(options.get("limit") or 0)
        show = int(options.get("show") or 0)

        if not use_stdin and not csv_path:
            raise CommandError("Provide --csv PATH or use --stdin.")

        raw = ""
        if use_stdin:
            raw = sys.stdin.read()
            if not raw.strip():
                raise CommandError("No CSV data on stdin.")
        else:
            try:
                with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
                    raw = f.read()
            except FileNotFoundError as exc:
                raise CommandError(str(exc)) from exc
            if not raw.strip():
                raise CommandError(f"CSV file is empty: {csv_path}")

        # csv.DictReader expects a file-like object.
        fp = raw.splitlines(True)
        reader = csv.DictReader(fp)

        fieldnames = [str(n).strip() for n in (reader.fieldnames or [])]
        if "Handle" not in fieldnames and "Title" not in fieldnames:
            raise CommandError("CSV missing Handle/Title columns (Shopify-like format expected).")
        if "Image Src" not in fieldnames and "Variant Image" not in fieldnames:
            raise CommandError("CSV missing Image Src/Variant Image column.")

        stats = ImportStats()
        planned_updates: List[Tuple[Product, str]] = []
        missing: List[Tuple[str, str, str]] = []  # (handle, slug, sku_sample)

        # Preload all products by slug for fast lookups.
        products_by_slug: Dict[str, Product] = {
            p.slug: p for p in Product.objects.select_related("category").all()
        }

        for handle, group in _iter_shopify_groups(reader):
            if limit and len(planned_updates) >= limit:
                break

            image_url = _pick_primary_image_url(group)
            if not image_url:
                stats.skipped_no_image += 1
                continue

            handle_slug = slugify(handle)
            product = products_by_slug.get(handle_slug)

            if not product:
                candidate_skus = _iter_candidate_skus(group)
                sku_sample = candidate_skus[0] if candidate_skus else ""

                # Fallback 1: try product SKU directly.
                if candidate_skus:
                    product = (
                        Product.objects.select_related("category")
                        .filter(sku__in=candidate_skus)
                        .first()
                    )

                # Fallback 2: try option SKU -> product.
                if not product and candidate_skus:
                    opt = (
                        ProductOption.objects.select_related("product__category")
                        .filter(sku__in=candidate_skus)
                        .first()
                    )
                    product = getattr(opt, "product", None)

                if not product:
                    stats.skipped_missing += 1
                    missing.append((handle, handle_slug, sku_sample))
                    continue

            if _is_merch_product(product):
                stats.skipped_merch += 1
                continue

            current = str(getattr(product, "main_image", "") or "").strip()
            if current == image_url:
                stats.unchanged += 1
                continue

            product.main_image = image_url
            planned_updates.append((product, image_url))

        if show:
            self.stdout.write("")
            self.stdout.write("Planned updates (sample):")
            for product, url in planned_updates[:show]:
                cat = getattr(getattr(product, "category", None), "slug", "") or ""
                self.stdout.write(f"- {product.slug} (sku={product.sku}, cat={cat}) -> {url}")
            if missing:
                self.stdout.write("")
                self.stdout.write("Missing products (sample):")
                for handle, slug, sku in missing[:show]:
                    self.stdout.write(f"- handle={handle!r} slug={slug!r} sku={sku!r}")

        if dry_run:
            self.stdout.write("")
            self.stdout.write("Dry run: no database changes were made.")
            self._print_summary(stats, planned_updates)
            return

        if not planned_updates:
            self.stdout.write("No updates to apply.")
            self._print_summary(stats, planned_updates)
            return

        # Persist changes efficiently.
        with transaction.atomic():
            Product.objects.bulk_update([p for p, _ in planned_updates], ["main_image"])

        stats.updated = len(planned_updates)
        self.stdout.write("Applied updates.")
        self._print_summary(stats, planned_updates)

    def _print_summary(self, stats: ImportStats, planned_updates: List[Tuple[Product, str]]):
        self.stdout.write("")
        self.stdout.write("Summary:")
        self.stdout.write(f"- will_update/updated: {len(planned_updates)}")
        self.stdout.write(f"- unchanged: {stats.unchanged}")
        self.stdout.write(f"- skipped_merch: {stats.skipped_merch}")
        self.stdout.write(f"- skipped_no_image: {stats.skipped_no_image}")
        self.stdout.write(f"- skipped_missing_product: {stats.skipped_missing}")
