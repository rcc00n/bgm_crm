from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.utils.text import slugify

from core.services.printful import get_printful_merch_product
from store.models import Category, MerchCategory, Product, ProductOption
from store.utils_merch import normalize_merch_category


def printful_merch_limit_setting(default: int = 8) -> int:
    raw = getattr(settings, "PRINTFUL_MERCH_LIMIT", default)
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        parsed = default
    return max(0, parsed)


def parse_merch_decimal(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def build_printful_product_sku(product_id: int) -> str:
    return f"PF-{product_id}"


def parse_printful_product_id_from_sku(value: str) -> int:
    raw = (value or "").strip().upper()
    if not raw.startswith("PF-"):
        return 0
    try:
        return int(raw[3:])
    except (TypeError, ValueError):
        return 0


def build_printful_product_slug(product_id: int, name: str) -> str:
    base = slugify(name or "")[:140] or "item"
    return f"merch-{product_id}-{base}"[:200]


def _get_or_create_merch_category() -> Category:
    existing = Category.objects.filter(name__iexact="Merch").first() or Category.objects.filter(slug="merch").first()
    if existing:
        return existing
    return Category.objects.create(
        name="Merch",
        slug="merch",
        description="Printful merchandise catalog.",
    )


def _dedupe_option_name(name: str, *, index: int, used: set[str]) -> str:
    clean = (name or "").strip()[:120] or f"Option {index}"
    if clean not in used:
        used.add(clean)
        return clean

    attempt = 2
    while True:
        suffix = f" ({attempt})"
        candidate = f"{clean[: max(1, 120 - len(suffix))]}{suffix}"
        if candidate not in used:
            used.add(candidate)
            return candidate
        attempt += 1


def sync_printful_options_for_product(product: Product, variants: list[dict]) -> int | None:
    if not variants:
        ProductOption.objects.filter(product=product).update(is_active=False)
        return None

    seen_skus: list[str] = []
    used_names: set[str] = set()
    default_option_id = None

    for index, variant in enumerate(variants, start=1):
        raw_sku = str(variant.get("sku") or "").strip()[:64]
        variant_id = 0
        try:
            variant_id = int(variant.get("id") or 0)
        except (TypeError, ValueError):
            variant_id = 0

        option_sku = raw_sku or f"{product.sku}-VAR-{variant_id or index}"
        if option_sku in seen_skus:
            option_sku = f"{option_sku[:56]}-{index}"[:64]
        seen_skus.append(option_sku)

        option_name = _dedupe_option_name(str(variant.get("name") or ""), index=index, used=used_names)
        option_price = parse_merch_decimal(variant.get("price"))
        sync_variant_id = 0
        variant_id = 0
        try:
            sync_variant_id = int(variant.get("sync_variant_id") or variant.get("id") or 0)
        except (TypeError, ValueError):
            sync_variant_id = 0
        try:
            variant_id = int(variant.get("variant_id") or 0)
        except (TypeError, ValueError):
            variant_id = 0
        external_id = (str(variant.get("external_id") or "") or "").strip()[:140]

        option, _ = ProductOption.objects.update_or_create(
            sku=option_sku,
            defaults={
                "product": product,
                "name": option_name,
                "description": "",
                "is_separator": False,
                "option_column": 1,
                "price": option_price,
                "is_active": True,
                "sort_order": index,
                "printful_sync_variant_id": sync_variant_id or None,
                "printful_variant_id": variant_id or None,
                "printful_external_id": external_id,
            },
        )
        if default_option_id is None:
            default_option_id = option.id

    ProductOption.objects.filter(product=product).exclude(sku__in=seen_skus).update(is_active=False)
    return default_option_id


def sync_printful_merch_products(products: list[dict]) -> None:
    if not products:
        return

    category = _get_or_create_merch_category()
    sync_full_catalog = printful_merch_limit_setting() == 0
    default_currency = (getattr(settings, "DEFAULT_CURRENCY_CODE", "CAD") or "CAD").upper()
    merch_categories = list(MerchCategory.objects.all())
    merch_by_slug = {(cat.slug or "").strip().lower(): cat for cat in merch_categories if cat.slug}
    merch_by_name = {(cat.name or "").strip().lower(): cat for cat in merch_categories if cat.name}
    synced_skus: set[str] = set()

    def _resolve_merch_category(label_source: str) -> MerchCategory | None:
        source = (label_source or "").strip()
        if not source:
            return None
        category_key, category_label = normalize_merch_category(source)
        if not category_label:
            return None
        key = (category_key or "").strip().lower()
        name_key = category_label.strip().lower()
        existing = merch_by_slug.get(key) or merch_by_name.get(name_key)
        if existing:
            return existing
        created = MerchCategory.objects.create(
            name=category_label,
            slug=category_key or slugify(category_label)[:140],
            is_active=True,
        )
        merch_by_slug[(created.slug or "").strip().lower()] = created
        merch_by_name[(created.name or "").strip().lower()] = created
        return created

    for item in products:
        try:
            product_id = int(item.get("id") or 0)
        except (TypeError, ValueError):
            product_id = 0
        if product_id <= 0:
            continue

        name = (str(item.get("name") or "") or f"Merch item {product_id}").strip()[:180]
        sku = build_printful_product_sku(product_id)
        synced_skus.add(sku)
        slug = build_printful_product_slug(product_id, name)
        variants = [row for row in item.get("variants", []) if isinstance(row, dict)]

        variant_prices = []
        for variant in variants:
            price = parse_merch_decimal(variant.get("price"))
            if price is not None:
                variant_prices.append(price)

        base_price = parse_merch_decimal(item.get("base_price"))
        if base_price is None and variant_prices:
            base_price = min(variant_prices)
        if base_price is None:
            base_price = Decimal("0.00")

        currency = (str(item.get("currency") or "") or default_currency).strip().upper() or default_currency
        image_url = (str(item.get("image_url") or "") or "").strip()
        external_id = (str(item.get("external_id") or "") or "").strip()[:140]
        existing = Product.objects.filter(sku=sku).only("id", "is_active", "merch_category_id").first()
        merch_category = None
        if existing is None or not existing.merch_category_id:
            label_source = (item.get("category_label") or item.get("name") or "").strip()
            merch_category = _resolve_merch_category(label_source)
        defaults = {
            "slug": slug,
            "name": name,
            "category": category,
            "price": base_price,
            "is_in_house": True,
            "printful_product_id": product_id,
            "printful_external_id": external_id,
            "currency": currency,
            "inventory": 9999,
            # Printful catalog visibility is the source of truth for synced merch.
            "is_active": True,
            "short_description": "Fulfilled by Printful.",
            "description": f"Printful product #{product_id}",
            "contact_for_estimate": False,
            "estimate_from_price": None,
            "main_image": image_url,
        }
        if merch_category:
            defaults["merch_category"] = merch_category
        product, _ = Product.objects.update_or_create(sku=sku, defaults=defaults)
        sync_printful_options_for_product(product, variants)

    if sync_full_catalog and synced_skus:
        Product.objects.filter(sku__startswith="PF-", is_active=True).exclude(sku__in=synced_skus).update(is_active=False)


def sync_printful_merch_product(product_id: int) -> Product | None:
    try:
        normalized_product_id = int(product_id or 0)
    except (TypeError, ValueError):
        normalized_product_id = 0
    if normalized_product_id <= 0:
        return None

    payload = get_printful_merch_product(normalized_product_id)
    if not payload:
        return None

    sync_printful_merch_products([payload])
    return Product.objects.filter(sku=build_printful_product_sku(normalized_product_id)).first()
