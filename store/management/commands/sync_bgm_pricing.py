from __future__ import annotations

import csv
import re
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils.text import slugify

from store.models import Category, ImportBatch, Product, ProductOption

PRICE_QUANT = Decimal("0.01")
DEFAULT_INVENTORY = 100
FINISH_LABELS = {
    "ARM": "Armadillo",
    "BR": "Brushed",
    "PL": "Polished",
    "SCL": "Smooth Criminal",
}
DESCRIPTION_ORDER = {
    "Shorty": 1,
    "Long John": 2,
    "Base": 1,
    "Base + Winch Mount": 2,
    "Pre-Runner": 3,
    "Pre-Runner + Winch Mount": 4,
    "Full-Tube": 5,
    "Full-Tube + Winch Mount": 6,
    "Cab Length": 1,
    "Wheel to Wheel": 2,
}
FINISH_ORDER = {
    "ARM": 1,
    "BR": 2,
    "PL": 3,
    "SCL": 4,
}
SIZE_ORDER = {
    '12"': 12,
    '13"': 13,
    '14"': 14,
    '16"': 16,
    '24"': 24,
    '26"': 26,
    '28"': 28,
    "1500": 1500,
    "2500/3500": 2500,
    "Vehicle Specific": 9999,
}
PRODUCT_DEFINITIONS = {
    "Kickback Mudflap": {
        "product_name": "BGM Kickback Mudflap",
        "product_sku": "BGM-KICKBACK-CATALOG",
        "short_description": "Choose flap length, finish, size, and pair or complete set.",
        "description": (
            "In-house BGM kickback mudflaps with fixed retail, Tier 1, and Tier 2 pricing. "
            "Select the build style, finish, size, and whether you need a pair or a full set."
        ),
        "option_column_1_label": "Shorty",
        "option_column_2_label": "Long John",
    },
    "Dually Mudflap": {
        "product_name": "BGM Dually Mudflap",
        "product_sku": "BGM-DUALLY-CATALOG",
        "short_description": "Choose flap length, finish, and width for the dually setup.",
        "description": (
            "In-house BGM dually mudflaps with fixed retail, Tier 1, and Tier 2 pricing. "
            "Select the profile, finish, and width that matches the truck."
        ),
        "option_column_1_label": "Shorty",
        "option_column_2_label": "Long John",
    },
    "Front Bumper": {
        "product_name": "BGM Front Bumper",
        "product_sku": "BGM-FRONT-BUMPER-CATALOG",
        "short_description": "Vehicle-specific front bumpers with package, finish, and truck-class options.",
        "description": (
            "In-house BGM front bumpers with fixed retail, Tier 1, and Tier 2 pricing. "
            "Choose the bumper package, finish, and truck class."
        ),
        "option_column_1_label": "Armadillo",
        "option_column_2_label": "Smooth Criminal",
    },
    "Rear Bumper": {
        "product_name": "BGM Rear Bumper",
        "product_sku": "BGM-REAR-BUMPER-CATALOG",
        "short_description": "Vehicle-specific rear bumpers with finish and truck-class options.",
        "description": (
            "In-house BGM rear bumpers with fixed retail, Tier 1, and Tier 2 pricing. "
            "Choose the finish and truck class for the build."
        ),
        "option_column_1_label": "Armadillo",
        "option_column_2_label": "Smooth Criminal",
    },
    "Badland Bar": {
        "product_name": "BGM Badland Bar",
        "product_sku": "BGM-BADLAND-BAR-CATALOG",
        "short_description": "Vehicle-specific side steps available in cab-length or wheel-to-wheel layouts.",
        "description": (
            "In-house BGM Badland Bars with fixed retail, Tier 1, and Tier 2 pricing. "
            "Choose the step length that fits the truck."
        ),
        "option_column_1_label": "Options",
        "option_column_2_label": "",
    },
}
LEGACY_PRODUCT_FAMILY_FILTERS = {
    "Front Bumper": (
        {"category": "Bumpers", "name_prefix": "Front Bumpers -"},
    ),
    "Rear Bumper": (
        {"category": "Bumpers", "name_prefix": "Rear Bumpers -"},
    ),
}
CATALOG_IMAGE_DONORS = {
    "Kickback Mudflap": (
        {"category": "Kickback Mudflaps", "name": "Long JohnKickback Mudflaps"},
        {"category": "Kickback Mudflaps", "name": "Shorty Kickback Mudflaps"},
    ),
    "Dually Mudflap": (
        {"category": "Kickback Mudflaps", "name": "Shorty Kickback Mudflaps"},
        {"category": "Kickback Mudflaps", "name": "Long JohnKickback Mudflaps"},
    ),
    "Front Bumper": (
        {"category": "Bumpers", "name": "Front Bumpers - Armadillo"},
    ),
    "Rear Bumper": (
        {"category": "Bumpers", "name": "Rear Bumpers - Smooth Liner"},
        {"category": "Bumpers", "name": "Rear Bumpers - Armadillo"},
    ),
    "Badland Bar": (
        {"category": "Running Boards", "name": "Running Boards/ Step Bars"},
    ),
}


@dataclass(frozen=True)
class PricingRow:
    sku: str
    category: str
    description: str
    finish: str
    size_class: str
    unit: str
    msrp: Decimal
    tier_1_price: Decimal
    tier_2_price: Decimal
    est_cost: Decimal | None = None
    notes: str = ""

    @property
    def key(self) -> tuple[str, str, str, str, str, str]:
        return (
            self.sku,
            self.category,
            self.description,
            self.finish,
            self.size_class,
            self.unit,
        )


def _parse_decimal(value: str | None) -> Decimal | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    cleaned = re.sub(r"[^0-9.\-]", "", raw.replace(",", ""))
    if not cleaned:
        return None
    try:
        return Decimal(cleaned).quantize(PRICE_QUANT)
    except (InvalidOperation, TypeError, ValueError):
        return None


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _normalize_unit(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"2", "pair", "pairs"}:
        return "Pair"
    if raw in {"4", "set", "sets"}:
        return "Set"
    if raw in {"each", "ea"}:
        return "Each"
    return str(value or "").strip()


def _normalized_row(raw: dict[str, str]) -> dict[str, str] | None:
    sku = str(raw.get("SKU") or "").strip()
    category = str(raw.get("Category") or "").strip()
    if not sku.startswith("BGM-") or not category:
        return None
    return {
        "sku": sku,
        "category": category,
        "description": str(raw.get("Description") or "").strip(),
        "finish": str(raw.get("Finish") or "").strip().upper(),
        "size_class": str(raw.get("Size/Class") or "").strip(),
        "unit": _normalize_unit(raw.get("Unit")),
        "notes": str(raw.get("Notes") or "").strip(),
    }


def _row_key(row: dict[str, str]) -> tuple[str, str, str, str, str, str]:
    return (
        row["sku"],
        row["category"],
        row["description"],
        row["finish"],
        row["size_class"],
        row["unit"],
    )


def _tier_price_column(fieldnames: list[str] | None, needle: str) -> str:
    for field in fieldnames or []:
        if needle.lower() in str(field or "").lower():
            return field
    raise CommandError(f"Could not find a pricing column containing '{needle}'.")


def _finish_label(code: str) -> str:
    return FINISH_LABELS.get(code or "", code or "")


def _unit_label(row: PricingRow) -> str:
    unit = _normalize_unit(row.unit).lower()
    if row.category == "Kickback Mudflap" and unit == "set":
        return "Complete Set"
    if unit == "pair":
        return "Pair"
    if unit == "set":
        return "Set"
    if unit == "each":
        return "Each"
    return _normalize_unit(row.unit)


def _option_name(row: PricingRow) -> str:
    if row.category in {"Kickback Mudflap", "Dually Mudflap"}:
        return f"{row.description} · {_finish_label(row.finish)} · {row.size_class} · {_unit_label(row)}"
    if row.category == "Front Bumper":
        return f"{row.description} · {_finish_label(row.finish)} · {row.size_class}"
    if row.category == "Rear Bumper":
        return f"{row.description} · {_finish_label(row.finish)} · {row.size_class}"
    if row.category == "Badland Bar":
        return f"{row.description} · {_finish_label(row.finish)}"
    return " · ".join(
        part for part in (row.description, _finish_label(row.finish), row.size_class, _unit_label(row)) if part
    )


def _option_column(row: PricingRow) -> int:
    if row.category in {"Kickback Mudflap", "Dually Mudflap"}:
        return 1 if row.description == "Shorty" else 2
    if row.category in {"Front Bumper", "Rear Bumper"}:
        return 1 if row.finish == "ARM" else 2
    return 1


def _sort_order(row: PricingRow) -> int:
    desc_rank = DESCRIPTION_ORDER.get(row.description, 99)
    finish_rank = FINISH_ORDER.get(row.finish, 99)
    size_rank = SIZE_ORDER.get(row.size_class, 999)
    unit_rank = 2 if _unit_label(row) == "Complete Set" else 1
    return (desc_rank * 10000) + (finish_rank * 1000) + (size_rank * 10) + unit_rank


def _inventory_value(existing: Product | None) -> int:
    if existing is None:
        return DEFAULT_INVENTORY
    try:
        return max(int(existing.inventory or 0), DEFAULT_INVENTORY)
    except (TypeError, ValueError):
        return DEFAULT_INVENTORY


def _find_catalog_image(category_name: str) -> str:
    for donor_filter in CATALOG_IMAGE_DONORS.get(category_name, ()):
        donor = (
            Product.objects.filter(
                is_in_house=True,
                category__name=donor_filter["category"],
                name=donor_filter["name"],
            )
            .exclude(main_image="")
            .exclude(main_image__isnull=True)
            .first()
        )
        if donor and donor.main_image_name:
            return donor.main_image_name
    return ""


def _unique_option_sku(base_sku: str, row: PricingRow, used: set[str]) -> str:
    candidate = base_sku.strip()
    if candidate not in used:
        return candidate

    parts = [
        row.size_class,
        row.description,
        row.finish,
        row.unit,
    ]
    suffix_parts: list[str] = []
    for part in parts:
        normalized = slugify(str(part or "").replace('"', "in")).upper()
        if not normalized or normalized in suffix_parts:
            continue
        suffix_parts.append(normalized)
        candidate = f"{base_sku}-{ '-'.join(suffix_parts) }"
        if candidate not in used:
            return candidate

    index = 2
    while True:
        candidate = f"{base_sku}-{index}"
        if candidate not in used:
            return candidate
        index += 1


class Command(BaseCommand):
    help = "Syncs the in-house BGM catalog from MSRP, Tier 1, and Tier 2 CSV price lists."

    def add_arguments(self, parser):
        parser.add_argument(
            "--msrp",
            default="BGM_Master_Pricelist_MSRP (CSV).csv",
            help="Path to the MSRP CSV.",
        )
        parser.add_argument(
            "--tier1",
            default="BGM_B2B_Tier1_10k_Plus.csv",
            help="Path to the Tier 1 CSV.",
        )
        parser.add_argument(
            "--tier2",
            default="BGM_B2B_Tier2_50k_Plus.csv",
            help="Path to the Tier 2 CSV.",
        )
        parser.add_argument(
            "--deactivate-obsolete",
            action="store_true",
            help="Deactivate legacy BGM product records in the managed categories that are not part of this sync.",
        )

    def handle(self, *args, **options):
        msrp_path = Path(options["msrp"])
        tier1_path = Path(options["tier1"])
        tier2_path = Path(options["tier2"])
        for path in (msrp_path, tier1_path, tier2_path):
            if not path.exists():
                raise CommandError(f"File not found: {path}")

        merged_rows = self._load_rows(msrp_path=msrp_path, tier1_path=tier1_path, tier2_path=tier2_path)
        grouped_rows: dict[str, list[PricingRow]] = defaultdict(list)
        for row in merged_rows:
            grouped_rows[row.category].append(row)

        unknown_categories = sorted(set(grouped_rows) - set(PRODUCT_DEFINITIONS))
        if unknown_categories:
            raise CommandError(f"Unhandled BGM categories in CSV: {', '.join(unknown_categories)}")

        source_label = ", ".join(path.name for path in (msrp_path, tier1_path, tier2_path))
        with transaction.atomic():
            batch = ImportBatch.objects.create(
                source_filename=source_label,
                mode="sync-bgm-pricing",
                is_dry_run=False,
            )
            summary = self._sync_catalog(
                grouped_rows=grouped_rows,
                batch=batch,
                deactivate_obsolete=bool(options["deactivate_obsolete"]),
            )
            for field, value in summary.items():
                setattr(batch, field, value)
            batch.save(
                update_fields=[
                    "created_categories",
                    "created_products",
                    "updated_products",
                    "created_options",
                    "updated_options",
                    "skipped_options",
                    "source_filename",
                    "mode",
                    "is_dry_run",
                ]
            )

        self.stdout.write(self.style.SUCCESS("BGM pricing sync completed."))
        self.stdout.write(
            f"Categories: +{summary['created_categories']} | "
            f"Products: +{summary['created_products']} / ~{summary['updated_products']} | "
            f"Options: +{summary['created_options']} / ~{summary['updated_options']} / skipped {summary['skipped_options']}"
        )

    def _load_rows(self, *, msrp_path: Path, tier1_path: Path, tier2_path: Path) -> list[PricingRow]:
        msrp_rows_raw = _read_csv(msrp_path)
        tier1_rows_raw = _read_csv(tier1_path)
        tier2_rows_raw = _read_csv(tier2_path)

        tier1_column = _tier_price_column(list(tier1_rows_raw[0].keys()) if tier1_rows_raw else [], "Tier 1 Price")
        tier2_column = _tier_price_column(list(tier2_rows_raw[0].keys()) if tier2_rows_raw else [], "Tier 2 Price")

        msrp_rows: dict[tuple[str, str, str, str, str, str], dict[str, str]] = {}
        tier1_rows: dict[tuple[str, str, str, str, str, str], dict[str, str]] = {}
        tier2_rows: dict[tuple[str, str, str, str, str, str], dict[str, str]] = {}

        for raw in msrp_rows_raw:
            normalized = _normalized_row(raw)
            if not normalized:
                continue
            normalized["msrp"] = raw.get("MSRP", "")
            normalized["est_cost"] = raw.get("Est Cost", "")
            normalized["notes"] = normalized["notes"] or str(raw.get("Notes") or "").strip()
            msrp_rows[_row_key(normalized)] = normalized

        for raw in tier1_rows_raw:
            normalized = _normalized_row(raw)
            if not normalized:
                continue
            normalized["msrp"] = raw.get("MSRP", "")
            normalized["tier_1_price"] = raw.get(tier1_column, "")
            normalized["notes"] = normalized["notes"] or str(raw.get("Notes") or "").strip()
            tier1_rows[_row_key(normalized)] = normalized

        for raw in tier2_rows_raw:
            normalized = _normalized_row(raw)
            if not normalized:
                continue
            normalized["msrp"] = raw.get("MSRP", "")
            normalized["tier_2_price"] = raw.get(tier2_column, "")
            normalized["notes"] = normalized["notes"] or str(raw.get("Notes") or "").strip()
            tier2_rows[_row_key(normalized)] = normalized

        all_keys = sorted(set(msrp_rows) | set(tier1_rows) | set(tier2_rows))
        merged: list[PricingRow] = []
        missing_keys: list[str] = []
        for key in all_keys:
            msrp_row = msrp_rows.get(key)
            tier1_row = tier1_rows.get(key)
            tier2_row = tier2_rows.get(key)
            if not msrp_row or not tier1_row or not tier2_row:
                missing_keys.append(" | ".join(key))
                continue

            msrp = _parse_decimal(msrp_row.get("msrp") or tier1_row.get("msrp") or tier2_row.get("msrp"))
            tier_1_price = _parse_decimal(tier1_row.get("tier_1_price"))
            tier_2_price = _parse_decimal(tier2_row.get("tier_2_price"))
            if msrp is None or tier_1_price is None or tier_2_price is None:
                missing_keys.append(" | ".join(key))
                continue

            merged.append(
                PricingRow(
                    sku=key[0],
                    category=key[1],
                    description=key[2],
                    finish=key[3],
                    size_class=key[4],
                    unit=key[5],
                    msrp=msrp,
                    tier_1_price=tier_1_price,
                    tier_2_price=tier_2_price,
                    est_cost=_parse_decimal(msrp_row.get("est_cost")),
                    notes=msrp_row.get("notes") or tier1_row.get("notes") or tier2_row.get("notes") or "",
                )
            )

        if missing_keys:
            preview = "; ".join(missing_keys[:5])
            raise CommandError(
                f"Pricing rows are incomplete across the CSV inputs ({len(missing_keys)} rows). Sample: {preview}"
            )
        if not merged:
            raise CommandError("No BGM pricing rows were found in the provided CSV files.")
        return merged

    def _sync_catalog(self, *, grouped_rows: dict[str, list[PricingRow]], batch: ImportBatch, deactivate_obsolete: bool) -> dict[str, int]:
        summary = {
            "created_categories": 0,
            "created_products": 0,
            "updated_products": 0,
            "created_options": 0,
            "updated_options": 0,
            "skipped_options": 0,
        }
        managed_product_skus: set[str] = set()
        managed_categories: set[str] = set()

        for category_name, rows in grouped_rows.items():
            definition = PRODUCT_DEFINITIONS[category_name]
            managed_categories.add(category_name)
            category, category_created = Category.objects.get_or_create(
                name=category_name,
                defaults={
                    "slug": slugify(category_name),
                    "description": definition["short_description"],
                },
            )
            if category_created:
                summary["created_categories"] += 1
            elif not category.description:
                category.description = definition["short_description"]
                category.save(update_fields=["description"])

            product_defaults = {
                "name": definition["product_name"],
                "slug": slugify(definition["product_name"]),
                "category": category,
                "price": min(row.msrp for row in rows),
                "dealer_tier_1_price": min(row.tier_1_price for row in rows),
                "dealer_tier_2_price": min(row.tier_2_price for row in rows),
                "unit_cost": min((row.est_cost for row in rows if row.est_cost is not None), default=None),
                "inventory": _inventory_value(Product.objects.filter(sku=definition["product_sku"]).first()),
                "currency": getattr(settings, "DEFAULT_CURRENCY_CODE", "CAD"),
                "is_active": True,
                "is_in_house": True,
                "import_batch": batch,
                "short_description": definition["short_description"],
                "description": definition["description"],
                "contact_for_estimate": False,
                "estimate_from_price": None,
                "option_column_1_label": definition["option_column_1_label"],
                "option_column_2_label": definition["option_column_2_label"],
            }
            product, created = Product.objects.update_or_create(
                sku=definition["product_sku"],
                defaults=product_defaults,
            )
            if not product.main_image_name:
                catalog_image = _find_catalog_image(category_name)
                if catalog_image:
                    product.main_image = catalog_image
                    product.save(update_fields=["main_image"])
            managed_product_skus.add(product.sku)
            if created:
                summary["created_products"] += 1
            else:
                summary["updated_products"] += 1

            used_skus: set[str] = set()
            kept_option_ids: set[int] = set()
            for row in sorted(rows, key=_sort_order):
                option_sku = _unique_option_sku(row.sku, row, used_skus)
                used_skus.add(option_sku)
                option_name = _option_name(row)
                existing = ProductOption.objects.filter(sku=option_sku).first()
                if existing is None:
                    existing = product.options.filter(name=option_name).first()

                reassigned = False
                if existing and existing.product_id != product.id:
                    existing.product = product
                    reassigned = True

                option_defaults = {
                    "name": option_name,
                    "sku": option_sku,
                    "description": "",
                    "price": row.msrp,
                    "dealer_tier_1_price": row.tier_1_price,
                    "dealer_tier_2_price": row.tier_2_price,
                    "is_separator": False,
                    "option_column": _option_column(row),
                    "is_active": True,
                    "import_batch": batch,
                    "sort_order": _sort_order(row),
                }
                if existing:
                    changed = False
                    for field, value in option_defaults.items():
                        if getattr(existing, field) != value:
                            setattr(existing, field, value)
                            changed = True
                    if changed or reassigned:
                        existing.save()
                        summary["updated_options"] += 1
                    else:
                        summary["skipped_options"] += 1
                    option = existing
                else:
                    option = ProductOption.objects.create(product=product, **option_defaults)
                    summary["created_options"] += 1
                kept_option_ids.add(option.id)

            product.options.exclude(id__in=kept_option_ids).update(is_active=False, import_batch=batch)

        if deactivate_obsolete and managed_categories:
            obsolete_scope = Q(category__name__in=managed_categories)
            for category_name in grouped_rows:
                for legacy_filter in LEGACY_PRODUCT_FAMILY_FILTERS.get(category_name, ()):
                    obsolete_scope |= Q(
                        category__name=legacy_filter["category"],
                        name__startswith=legacy_filter["name_prefix"],
                    )

            Product.objects.filter(
                obsolete_scope,
                is_in_house=True,
                sku__startswith="BGM-",
            ).exclude(
                sku__in=managed_product_skus
            ).update(
                is_active=False,
                import_batch=batch,
            )

        return summary
