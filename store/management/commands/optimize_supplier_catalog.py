from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from store.models import Category, CleanupBatch, Product, ProductOption

GROUP_PARENT_SKU_PREFIX = "CAT-GRP-"
PLACEHOLDER_PREFIX = "store/placeholders/"
PRICE_QUANT = Decimal("0.01")


@dataclass(frozen=True)
class FamilyRule:
    category_name: str
    prefix: str
    parent_title: str
    split_platform: bool = False


@dataclass(frozen=True)
class PlatformRule:
    code: str
    label: str
    keywords: tuple[str, ...]


FAMILY_RULES: tuple[FamilyRule, ...] = (
    FamilyRule(
        category_name="FASS Fuel Systems & Series",
        prefix="FASS Titanium Signature Series Diesel Fuel Lift Pump",
        parent_title="FASS Titanium Signature Series Diesel Fuel Lift Pump",
        split_platform=True,
    ),
    FamilyRule(
        category_name="FASS Fuel Systems & Series",
        prefix="FASS Titanium Signature Series Fuel System",
        parent_title="FASS Titanium Signature Series Fuel System",
        split_platform=True,
    ),
    FamilyRule(
        category_name="FASS Fuel Systems & Series",
        prefix="FASS Titanium Diesel Fuel Lift Pump",
        parent_title="FASS Titanium Diesel Fuel Lift Pump",
        split_platform=True,
    ),
    FamilyRule(
        category_name="FASS Fuel Systems & Series",
        prefix="FASS Titanium Series Fuel System",
        parent_title="FASS Titanium Series Fuel System",
        split_platform=True,
    ),
    FamilyRule(
        category_name="FASS Fuel Systems & Series",
        prefix="FASS Adjustable Fuel Pressure Regulator Kit",
        parent_title="FASS Adjustable Fuel Pressure Regulator Kit",
        split_platform=True,
    ),
    FamilyRule(
        category_name="FASS Fuel Systems & Series",
        prefix="FASS 12V Fuel System",
        parent_title="FASS 12V Fuel System",
        split_platform=True,
    ),
    FamilyRule(
        category_name="Exhaust",
        prefix="Downpipe Back Exhaust - Single",
        parent_title="Downpipe Back Exhaust - Single",
        split_platform=True,
    ),
    FamilyRule(
        category_name="Exhaust",
        prefix="Turbo Back Exhaust - Single",
        parent_title="Turbo Back Exhaust - Single",
        split_platform=True,
    ),
    FamilyRule(
        category_name="Exhaust",
        prefix="Cat & DPF Race Pipe",
        parent_title="Cat & DPF Race Pipe",
        split_platform=True,
    ),
    FamilyRule(
        category_name="Motor Vehicle Engine Parts",
        prefix='Open Air 4" Intake Tube W/S&B Filter',
        parent_title='Open Air 4" Intake Tube W/S&B Filter',
        split_platform=True,
    ),
    FamilyRule(
        category_name="Motor Vehicle Engine Parts",
        prefix="Signature EGR Upgrade Kit",
        parent_title="Signature EGR Upgrade Kit",
        split_platform=True,
    ),
    FamilyRule(
        category_name="Motor Vehicle Engine Parts",
        prefix="Commander Tune Files",
        parent_title="Commander Tune Files",
        split_platform=True,
    ),
    FamilyRule(
        category_name="Motor Vehicle Engine Parts",
        prefix="EFI Live Tune Files",
        parent_title="EFI Live Tune Files",
        split_platform=True,
    ),
    FamilyRule(
        category_name="Motor Vehicle Engine Parts",
        prefix="EZ Lynk Tune Files",
        parent_title="EZ Lynk Tune Files",
        split_platform=True,
    ),
    FamilyRule(
        category_name="Motor Vehicle Engine Parts",
        prefix="MPVi4 Tune Files",
        parent_title="MPVi4 Tune Files",
        split_platform=True,
    ),
    FamilyRule(
        category_name="Motor Vehicle Engine Parts",
        prefix="SCT Tune Files",
        parent_title="SCT Tune Files",
        split_platform=True,
    ),
    FamilyRule(
        category_name="Motor Vehicle Engine Parts",
        prefix="CCV Upgrade Kit",
        parent_title="CCV Upgrade Kit",
        split_platform=True,
    ),
    FamilyRule(
        category_name="Motor Vehicle Engine Parts",
        prefix="EGR Upgrade Kit",
        parent_title="EGR Upgrade Kit",
        split_platform=True,
    ),
    FamilyRule(
        category_name="Motor Vehicle Engine Parts",
        prefix="Tune Files",
        parent_title="Tune Files",
        split_platform=True,
    ),
    FamilyRule(
        category_name="Electrical Switches",
        prefix="RBG LED Digital Switch",
        parent_title="RBG LED Digital Switch",
    ),
    FamilyRule(
        category_name="Electrical Switches",
        prefix="SOTF Harness",
        parent_title="SOTF Harness",
        split_platform=True,
    ),
    FamilyRule(
        category_name="Switch on the Fly Brackets",
        prefix="Rotary Switch Bracket",
        parent_title="Rotary Switch Bracket",
    ),
    FamilyRule(
        category_name="Drivetrain Parts",
        prefix="EFI Live Transmission Tune File",
        parent_title="EFI Live Transmission Tune File",
        split_platform=True,
    ),
    FamilyRule(
        category_name="Drivetrain Parts",
        prefix="GDP Transmission Tune File",
        parent_title="GDP Transmission Tune File",
        split_platform=True,
    ),
    FamilyRule(
        category_name="Drivetrain Parts",
        prefix="Transmission Tune File",
        parent_title="Transmission Tune File",
        split_platform=True,
    ),
    FamilyRule(
        category_name="Vehicle Repair & Specialty Tools",
        prefix="MM3 Touch Display and MM3 Controller - Blank",
        parent_title="MM3 Touch Display and MM3 Controller - Blank",
    ),
    FamilyRule(
        category_name="Software",
        prefix="MM3 VIN License",
        parent_title="MM3 VIN License",
    ),
    FamilyRule(
        category_name="Motor Vehicle Electronics",
        prefix="MPVi4 Tune Files",
        parent_title="MPVi4 Tune Files",
        split_platform=True,
    ),
    FamilyRule(
        category_name="FASS Install Kits & Accessories",
        prefix="FASS Cummins Filter Housing Delete",
        parent_title="FASS Cummins Filter Housing Delete",
        split_platform=True,
    ),
    FamilyRule(
        category_name="FASS Install Kits & Accessories",
        prefix="FASS 5/8 Suction Tube Kit",
        parent_title="FASS 5/8 Suction Tube Kit",
    ),
)

PLATFORM_RULES: tuple[PlatformRule, ...] = (
    PlatformRule(
        code="cummins",
        label="Cummins",
        keywords=(
            "cummins",
            "ram",
            "dodge",
            "2500",
            "3500",
            "4500",
            "5500",
        ),
    ),
    PlatformRule(
        code="duramax",
        label="Duramax",
        keywords=(
            "duramax",
            "silverado",
            "sierra",
            "chevrolet",
            "chevy",
            "gmc",
            "l5p",
            "lml",
            "lbz",
            "lmm",
        ),
    ),
    PlatformRule(
        code="powerstroke",
        label="Powerstroke",
        keywords=(
            "powerstroke",
            "ford",
            "super duty",
            "f-250",
            "f-350",
            "f-450",
            "f-550",
            "f250",
            "f350",
            "f450",
            "f550",
        ),
    ),
    PlatformRule(
        code="class8",
        label="Class 8 / Heavy Duty",
        keywords=(
            "class 8",
            "heavy duty",
            "freightliner",
            "kenworth",
            "peterbilt",
            "western star",
            "international",
            "mack",
            "volvo",
            "detroit",
            "caterpillar",
            "cat engine",
            "semi",
            "dd15",
            "dt466",
            "mx13",
            "mx-13",
            "isx",
            "c15",
            "n14",
        ),
    ),
)


def _normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _normalized_key(value: str | None) -> str:
    return _normalize_text(value).lower()


def _decimal_or_zero(value) -> Decimal:
    try:
        return Decimal(value).quantize(PRICE_QUANT)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0.00")


def _image_source_rank(image_name: str) -> int:
    value = str(image_name or "").strip().lower()
    if not value:
        return 99
    if value.startswith("store/imports/"):
        return 0
    if value.startswith("store/products/imported/"):
        return 1
    if value.startswith("store/products/"):
        return 2
    return 3


def _product_image_name(product: Product) -> str:
    image_name = str(getattr(product, "main_image_name", "") or "").strip()
    if not image_name or image_name.startswith(("http://", "https://")):
        return ""
    if image_name.startswith(PLACEHOLDER_PREFIX):
        return ""
    return image_name


def _best_image_name(products: list[Product]) -> str:
    candidates = [product for product in products if _product_image_name(product)]
    if not candidates:
        return ""
    candidates.sort(
        key=lambda product: (
            _image_source_rank(_product_image_name(product)),
            0 if bool(getattr(product, "is_in_house", False)) else 1,
            -int(getattr(product, "inventory", 0) or 0),
            -int(getattr(product, "pk", 0) or 0),
        )
    )
    return _product_image_name(candidates[0])


def _longest_text(*values: str | None) -> str:
    cleaned = [_normalize_text(value) for value in values if _normalize_text(value)]
    if not cleaned:
        return ""
    return max(cleaned, key=len)


def _keyword_score(haystack: str, keyword: str) -> int:
    text = haystack.lower()
    needle = keyword.lower().strip()
    if not needle:
        return 0
    if re.match(r"^[a-z0-9]+$", needle):
        return 1 if re.search(rf"\b{re.escape(needle)}\b", text) else 0
    return 1 if needle in text else 0


def _product_platform(product: Product) -> tuple[str, str]:
    fragments = [
        getattr(product, "name", ""),
        getattr(product, "short_description", ""),
        getattr(product, "description", ""),
        getattr(product, "compatibility", ""),
    ]
    compatible_models = getattr(product, "_prefetched_objects_cache", {}).get("compatible_models", [])
    for model in compatible_models:
        fragments.append(getattr(getattr(model, "make", None), "name", ""))
        fragments.append(getattr(model, "name", ""))
    haystack = _normalize_text(" ".join(fragment for fragment in fragments if fragment)).lower()
    ranked: list[tuple[int, int, PlatformRule]] = []
    for priority, rule in enumerate(PLATFORM_RULES):
        score = sum(_keyword_score(haystack, keyword) for keyword in rule.keywords)
        if score > 0:
            ranked.append((-score, priority, rule))
    if not ranked:
        return ("universal", "Universal / Misc")
    ranked.sort()
    rule = ranked[0][2]
    return (rule.code, rule.label)


def _match_family_rule(product: Product) -> FamilyRule | None:
    product_name = _normalize_text(getattr(product, "name", ""))
    category_name = getattr(getattr(product, "category", None), "name", "")
    for rule in sorted(FAMILY_RULES, key=lambda item: len(item.prefix), reverse=True):
        if category_name != rule.category_name:
            continue
        if product_name.startswith(rule.prefix):
            return rule
    return None


def _group_name(rule: FamilyRule, platform_label: str) -> str:
    if rule.split_platform and platform_label and platform_label != "Universal / Misc":
        return f"{rule.parent_title} - {platform_label}"
    return rule.parent_title


def _group_identity(rule: FamilyRule, platform_code: str) -> str:
    return f"{rule.category_name}|{rule.parent_title}|{platform_code or 'universal'}"


def _group_sku(rule: FamilyRule, platform_code: str) -> str:
    raw_key = _group_identity(rule, platform_code)
    digest = hashlib.sha1(raw_key.encode("utf-8")).hexdigest()[:8].upper()
    base = slugify(f"{rule.category_name}-{rule.parent_title}-{platform_code or 'universal'}").upper()
    base = base.replace("-", "")
    trimmed = base[: max(12, 64 - len(GROUP_PARENT_SKU_PREFIX) - 9)]
    return f"{GROUP_PARENT_SKU_PREFIX}{trimmed}-{digest}"


def _group_slug(category: Category, group_name: str, sku: str) -> str:
    base = slugify(f"{category.slug}-{group_name}")[:180].strip("-")
    digest = hashlib.sha1(sku.encode("utf-8")).hexdigest()[:8]
    return f"{base}-{digest}" if base else digest


def _group_short_description(rule: FamilyRule, platform_label: str) -> str:
    if rule.split_platform and platform_label and platform_label != "Universal / Misc":
        return f"{rule.parent_title} grouped by options for {platform_label} fitment."
    return f"{rule.parent_title} grouped by options to keep the catalog cleaner."


def _group_description(rule: FamilyRule, platform_label: str) -> str:
    if rule.split_platform and platform_label and platform_label != "Universal / Misc":
        return (
            f"Grouped {rule.parent_title.lower()} listing for {platform_label} applications. "
            "Use the option list to pick the exact fitment and variant."
        )
    return (
        f"Grouped {rule.parent_title.lower()} listing. "
        "Use the option list to pick the exact fitment and variant."
    )


def _option_label(rule: FamilyRule, product: Product) -> str:
    name = _normalize_text(getattr(product, "name", ""))
    suffix = _normalize_text(name[len(rule.prefix) :]) if name.startswith(rule.prefix) else name
    suffix = re.sub(r"^[\s\-–—:|/]+", "", suffix)
    suffix = _normalize_text(suffix)
    return suffix or (getattr(product, "sku", "") or "Standard")


def _product_score(product: Product) -> tuple[int, int, int, int, int]:
    option_count = len(
        [
            option
            for option in getattr(product, "_prefetched_objects_cache", {}).get("options", [])
            if bool(getattr(option, "is_active", False))
        ]
    )
    compat_count = len(getattr(product, "_prefetched_objects_cache", {}).get("compatible_models", []))
    return (
        1 if _product_image_name(product) else 0,
        1 if option_count else 0,
        compat_count,
        int(getattr(product, "inventory", 0) or 0),
        int(getattr(product, "pk", 0) or 0),
    )


def _merge_option_onto_target(target: ProductOption, source: ProductOption) -> bool:
    changed = False
    merged_description = _longest_text(getattr(target, "description", ""), getattr(source, "description", ""))[:240]
    if merged_description != getattr(target, "description", ""):
        target.description = merged_description
        changed = True
    merged_price = min(
        [_decimal_or_zero(value) for value in (getattr(target, "price", None), getattr(source, "price", None)) if value is not None],
        default=None,
    )
    if merged_price is not None and getattr(target, "price", None) != merged_price:
        target.price = merged_price
        changed = True
    if bool(getattr(source, "is_active", False)) and not bool(getattr(target, "is_active", False)):
        target.is_active = True
        changed = True
    if bool(getattr(source, "is_separator", False)) != bool(getattr(target, "is_separator", False)):
        target.is_separator = bool(getattr(target, "is_separator", False)) and bool(getattr(source, "is_separator", False))
        changed = True
    target_sort_order = int(getattr(target, "sort_order", 0) or 0)
    source_sort_order = int(getattr(source, "sort_order", 0) or 0)
    merged_sort_order = min(target_sort_order, source_sort_order)
    if target_sort_order != merged_sort_order:
        target.sort_order = merged_sort_order
        changed = True
    return changed


def _reassign_options(source_product: Product, target_product: Product) -> int:
    moved = 0
    for option in source_product.options.all():
        existing = target_product.options.filter(name=option.name).first()
        if existing is None and getattr(option, "sku", None):
            existing = target_product.options.filter(sku=option.sku).first()
        if existing is None:
            option.product = target_product
            option.save(update_fields=["product"])
            moved += 1
            continue
        if existing.pk == option.pk:
            continue
        if _merge_option_onto_target(existing, option):
            existing.save()
    return moved


class Command(BaseCommand):
    help = (
        "Consolidates non-in-house supplier products into option-based parents, "
        "deactivates exact copies, and fills missing category images."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Apply the catalog cleanup. Without this flag the command prints a dry-run report.",
        )

    def handle(self, *args, **options):
        apply_changes = bool(options["apply"])
        if apply_changes:
            with transaction.atomic():
                batch = CleanupBatch.objects.create(
                    criteria="supplier-catalog optimization (options + duplicate cleanup + category images)",
                )
                summary = self._run_cleanup(batch=batch, apply_changes=True)
                batch.matched_products = summary["matched_products"]
                batch.deactivated_products = summary["deactivated_products"]
                batch.save(update_fields=["matched_products", "deactivated_products"])
        else:
            summary = self._run_cleanup(batch=None, apply_changes=False)

        mode_label = "Applied" if apply_changes else "Dry run"
        self.stdout.write(
            self.style.SUCCESS(
                f"{mode_label}: grouped_parents={summary['grouped_parents']} "
                f"created_options={summary['created_options']} "
                f"updated_options={summary['updated_options']} "
                f"deactivated_products={summary['deactivated_products']} "
                f"duplicate_groups={summary['duplicate_groups']} "
                f"filled_category_images={summary['filled_category_images']}"
            )
        )
        for line in summary["details"][:50]:
            self.stdout.write(line)
        if len(summary["details"]) > 50:
            self.stdout.write(f"... {len(summary['details']) - 50} more detail rows")

    def _run_cleanup(self, *, batch: CleanupBatch | None, apply_changes: bool) -> dict[str, object]:
        summary: dict[str, object] = {
            "matched_products": 0,
            "grouped_parents": 0,
            "created_options": 0,
            "updated_options": 0,
            "deactivated_products": 0,
            "duplicate_groups": 0,
            "filled_category_images": 0,
            "details": [],
        }
        summary["matched_products"] = int(
            Product.objects.filter(is_active=True, is_in_house=False).exclude(sku__startswith=GROUP_PARENT_SKU_PREFIX).count()
        )

        family_categories = sorted({rule.category_name for rule in FAMILY_RULES})
        family_candidates = list(
            Product.objects.filter(
                is_in_house=False,
                category__name__in=family_categories,
            )
            .exclude(sku__startswith=GROUP_PARENT_SKU_PREFIX)
            .select_related("category")
            .prefetch_related("compatible_models__make", "options")
        )

        grouped_source_ids: set[int] = set()
        groups: dict[str, dict[str, object]] = {}
        for product in family_candidates:
            if not bool(getattr(product, "is_active", False)):
                continue
            rule = _match_family_rule(product)
            if rule is None:
                continue
            platform_code, platform_label = _product_platform(product) if rule.split_platform else ("all", "")
            identity = _group_identity(rule, platform_code)
            bucket = groups.setdefault(
                identity,
                {
                    "rule": rule,
                    "platform_code": platform_code,
                    "platform_label": platform_label,
                    "products": [],
                },
            )
            bucket["products"].append(product)
            grouped_source_ids.add(product.pk)

        for identity in sorted(groups):
            bucket = groups[identity]
            grouped_sources = list(bucket["products"])
            if not grouped_sources:
                continue
            rule = bucket["rule"]
            category = grouped_sources[0].category
            platform_code = str(bucket["platform_code"])
            platform_label = str(bucket["platform_label"])
            parent_sku = _group_sku(rule, platform_code)
            parent_name = _group_name(rule, platform_label)
            existing_parent = Product.objects.filter(sku=parent_sku).first()
            parent_defaults = {
                "name": parent_name,
                "slug": _group_slug(category, parent_name, parent_sku),
                "category": category,
                "price": min(_decimal_or_zero(product.price) for product in grouped_sources),
                "unit_cost": min(
                    (_decimal_or_zero(product.unit_cost) for product in grouped_sources if getattr(product, "unit_cost", None) is not None),
                    default=None,
                ),
                "inventory": sum(max(int(getattr(product, "inventory", 0) or 0), 0) for product in grouped_sources),
                "is_active": True,
                "is_in_house": False,
                "short_description": _group_short_description(rule, platform_label),
                "description": _group_description(rule, platform_label),
                "contact_for_estimate": any(bool(getattr(product, "contact_for_estimate", False)) for product in grouped_sources),
                "estimate_from_price": None,
                "option_column_1_label": "Options",
                "option_column_2_label": "",
            }
            if apply_changes:
                parent, created = Product.objects.update_or_create(
                    sku=parent_sku,
                    defaults=parent_defaults,
                )
                if not _product_image_name(parent):
                    image_name = _best_image_name(grouped_sources)
                    if image_name:
                        parent.main_image = image_name
                        parent.save(update_fields=["main_image"])
                parent.compatible_models.set(
                    sorted(
                        {
                            model_id
                            for product in grouped_sources
                            for model_id in product.compatible_models.values_list("id", flat=True)
                        }
                    )
                )
            else:
                parent = existing_parent or Product(sku=parent_sku, **parent_defaults)
                created = existing_parent is None

            summary["grouped_parents"] = int(summary["grouped_parents"]) + (1 if created else 0)
            summary["details"].append(
                f"group {parent_name}: {len(grouped_sources)} source product(s) -> {parent_sku}"
            )

            grouped_sources.sort(key=lambda product: (_option_label(rule, product).lower(), -int(product.pk or 0)))
            option_buckets: dict[str, list[Product]] = defaultdict(list)
            for product in grouped_sources:
                option_buckets[_option_label(rule, product)].append(product)

            kept_option_ids: set[int] = set()
            for sort_order, option_name in enumerate(sorted(option_buckets), start=1):
                option_sources = option_buckets[option_name]
                representative = sorted(option_sources, key=_product_score, reverse=True)[0]
                option_defaults = {
                    "name": option_name,
                    "sku": getattr(representative, "sku", "") or None,
                    "description": _longest_text(
                        *(getattr(product, "short_description", "") for product in option_sources),
                        *(getattr(product, "compatibility", "") for product in option_sources),
                    )[:240],
                    "is_separator": False,
                    "option_column": 1,
                    "price": min(_decimal_or_zero(product.price) for product in option_sources),
                    "is_active": True,
                    "sort_order": sort_order,
                }
                if apply_changes:
                    option = parent.options.filter(name=option_name).first()
                    if option is None and option_defaults["sku"]:
                        option = ProductOption.objects.filter(sku=option_defaults["sku"]).first()
                    if option is None:
                        option = ProductOption.objects.create(product=parent, **option_defaults)
                        summary["created_options"] = int(summary["created_options"]) + 1
                    else:
                        changed = False
                        if option.product_id != parent.id:
                            option.product = parent
                            changed = True
                        for field, value in option_defaults.items():
                            if getattr(option, field) != value:
                                setattr(option, field, value)
                                changed = True
                        if changed:
                            option.save()
                            summary["updated_options"] = int(summary["updated_options"]) + 1
                    kept_option_ids.add(option.id)
                else:
                    existing = False
                    if parent.pk:
                        existing = parent.options.filter(name=option_name).exists()
                    if existing:
                        summary["updated_options"] = int(summary["updated_options"]) + 1
                    else:
                        summary["created_options"] = int(summary["created_options"]) + 1

            if apply_changes:
                parent.options.exclude(id__in=kept_option_ids).update(is_active=False)
                deactivated = Product.objects.filter(pk__in=[product.pk for product in grouped_sources]).exclude(pk=parent.pk).update(
                    is_active=False,
                    cleanup_batch=batch,
                )
                summary["deactivated_products"] = int(summary["deactivated_products"]) + int(deactivated)

        active_products = list(
            Product.objects.filter(is_active=True, is_in_house=False)
            .exclude(sku__startswith=GROUP_PARENT_SKU_PREFIX)
            .exclude(pk__in=grouped_source_ids)
            .select_related("category")
            .prefetch_related("compatible_models__make", "options")
        )
        duplicate_groups: dict[tuple[int, str], list[Product]] = defaultdict(list)
        for product in active_products:
            key = (product.category_id, _normalized_key(getattr(product, "name", "")))
            if key[1]:
                duplicate_groups[key].append(product)

        for products in duplicate_groups.values():
            if len(products) <= 1:
                continue
            keeper = sorted(products, key=_product_score, reverse=True)[0]
            duplicates = [product for product in products if product.pk != keeper.pk]
            if not duplicates:
                continue
            summary["duplicate_groups"] = int(summary["duplicate_groups"]) + 1
            summary["details"].append(
                f"dedupe {keeper.category.name} / {keeper.name}: {len(duplicates)} duplicate(s) removed"
            )

            if not apply_changes:
                summary["deactivated_products"] = int(summary["deactivated_products"]) + len(duplicates)
                continue

            changed_fields: list[str] = []
            moved_option_count = 0
            best_image = _best_image_name(products)
            if not _product_image_name(keeper) and best_image:
                keeper.main_image = best_image
                changed_fields.append("main_image")
            merged_short = _longest_text(keeper.short_description, *(product.short_description for product in duplicates))
            if merged_short and merged_short != keeper.short_description:
                keeper.short_description = merged_short[:240]
                changed_fields.append("short_description")
            merged_description = _longest_text(keeper.description, *(product.description for product in duplicates))
            if merged_description and merged_description != keeper.description:
                keeper.description = merged_description
                changed_fields.append("description")
            merged_inventory = max(sum(max(int(getattr(product, "inventory", 0) or 0), 0) for product in products), int(keeper.inventory or 0))
            if merged_inventory != keeper.inventory:
                keeper.inventory = merged_inventory
                changed_fields.append("inventory")
            merged_price = min(_decimal_or_zero(product.price) for product in products)
            if merged_price != _decimal_or_zero(keeper.price):
                keeper.price = merged_price
                changed_fields.append("price")
            merged_unit_costs = [_decimal_or_zero(product.unit_cost) for product in products if getattr(product, "unit_cost", None) is not None]
            if merged_unit_costs:
                merged_unit_cost = min(merged_unit_costs)
                if keeper.unit_cost != merged_unit_cost:
                    keeper.unit_cost = merged_unit_cost
                    changed_fields.append("unit_cost")
            if any(bool(getattr(product, "contact_for_estimate", False)) for product in products) and not keeper.contact_for_estimate:
                keeper.contact_for_estimate = True
                changed_fields.append("contact_for_estimate")
            if changed_fields:
                keeper.save(update_fields=sorted(set(changed_fields + ["updated_at"])))
            keeper.compatible_models.set(
                sorted(
                    {
                        model_id
                        for product in products
                        for model_id in product.compatible_models.values_list("id", flat=True)
                    }
                )
            )
            for duplicate in duplicates:
                moved_option_count += _reassign_options(duplicate, keeper)
            if moved_option_count:
                summary["details"].append(
                    f"dedupe {keeper.category.name} / {keeper.name}: moved {moved_option_count} option(s) to keeper"
                )

            deactivated = Product.objects.filter(pk__in=[product.pk for product in duplicates]).update(
                is_active=False,
                cleanup_batch=batch,
            )
            summary["deactivated_products"] = int(summary["deactivated_products"]) + int(deactivated)

        fallback_products = list(
            Product.objects.filter(is_active=True)
            .select_related("category")
            .order_by("-is_in_house", "-created_at")
        )
        fallback_image = _best_image_name(fallback_products)
        categories = list(
            Category.objects.filter(products__is_active=True).distinct().order_by("name")
        )
        for category in categories:
            current_image = str(getattr(category.image, "name", "") or "").strip()
            if current_image:
                continue
            category_products = list(category.products.filter(is_active=True).order_by("-is_in_house", "-created_at"))
            image_name = _best_image_name(category_products) or fallback_image
            if not image_name:
                continue
            summary["filled_category_images"] = int(summary["filled_category_images"]) + 1
            summary["details"].append(f"category image {category.name}: {image_name}")
            if apply_changes:
                category.image = image_name
                category.save(update_fields=["image"])

        return summary
