from __future__ import annotations

import json
import logging
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.cache import cache
from django.utils.text import slugify

from core.utils import format_currency

logger = logging.getLogger(__name__)

_CACHE_PREFIX = "printful_merch_v1"


class PrintfulAPIError(RuntimeError):
    """Raised when a Printful API request fails."""


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError, TypeError):
        return None


def _int_setting(name: str, default: int, *, min_value: int | None = None, max_value: int | None = None) -> int:
    raw = getattr(settings, name, default)
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        parsed = default
    if min_value is not None:
        parsed = max(min_value, parsed)
    if max_value is not None:
        parsed = min(max_value, parsed)
    return parsed


def _float_setting(name: str, default: float, *, min_value: float | None = None) -> float:
    raw = getattr(settings, name, default)
    try:
        parsed = float(raw)
    except (TypeError, ValueError):
        parsed = default
    if min_value is not None:
        parsed = max(min_value, parsed)
    return parsed


def _build_headers() -> dict[str, str]:
    token = (getattr(settings, "PRINTFUL_TOKEN", "") or "").strip()
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "BGM-CRM/1.0",
    }
    store_id = (getattr(settings, "PRINTFUL_STORE_ID", "") or "").strip()
    if store_id:
        headers["X-PF-Store-Id"] = store_id
    return headers


def _api_get(path: str, *, query: dict[str, Any] | None = None) -> dict[str, Any]:
    base_url = (getattr(settings, "PRINTFUL_API_BASE_URL", "https://api.printful.com") or "https://api.printful.com").strip()
    if not base_url:
        base_url = "https://api.printful.com"
    base_url = base_url.rstrip("/")
    url = f"{base_url}{path}"
    if query:
        url = f"{url}?{urlencode(query, doseq=True)}"

    req = Request(url, headers=_build_headers())
    timeout = _float_setting("PRINTFUL_TIMEOUT_SECONDS", 4.0, min_value=0.5)

    try:
        with urlopen(req, timeout=timeout) as resp:
            status = int(getattr(resp, "status", 200) or 200)
            raw = resp.read(1024 * 1024)
    except HTTPError as exc:
        detail = ""
        try:
            detail = exc.read(512).decode("utf-8", errors="ignore")
        except Exception:
            detail = ""
        logger.warning("Printful HTTP error %s on %s: %s", exc.code, path, detail)
        raise PrintfulAPIError(f"http_{exc.code}") from exc
    except URLError as exc:
        logger.warning("Printful network error on %s: %s", path, exc)
        raise PrintfulAPIError("network_error") from exc
    except Exception as exc:
        logger.warning("Printful request failed on %s: %s", path, exc)
        raise PrintfulAPIError("request_failed") from exc

    if status >= 400:
        raise PrintfulAPIError(f"http_{status}")

    try:
        payload = json.loads(raw.decode("utf-8", errors="ignore"))
    except (TypeError, ValueError) as exc:
        raise PrintfulAPIError("invalid_json") from exc

    if isinstance(payload, dict):
        api_code = _coerce_int(payload.get("code"), default=200)
        if api_code >= 400:
            raise PrintfulAPIError(f"api_{api_code}")
        if payload.get("error"):
            raise PrintfulAPIError("api_error")
    return payload if isinstance(payload, dict) else {}


def _extract_result_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    result = payload.get("result")
    if isinstance(result, list):
        return [row for row in result if isinstance(row, dict)]
    if isinstance(result, dict):
        for key in ("items", "data", "products", "result"):
            candidate = result.get(key)
            if isinstance(candidate, list):
                return [row for row in candidate if isinstance(row, dict)]
    return []


def _extract_product(row: dict[str, Any]) -> dict[str, Any]:
    sync_product = row.get("sync_product")
    if isinstance(sync_product, dict):
        merged = dict(sync_product)
        for key in (
            "thumbnail_url",
            "external_id",
            "name",
            "id",
            "variants",
            "synced",
            "is_ignored",
            "category_label",
            "main_category_name",
            "category_name",
            "main_category",
            "type_name",
            "product_type_name",
            "type",
            "category",
            "product",
        ):
            if key not in merged and key in row:
                merged[key] = row.get(key)
        if "sync_variants" not in merged and isinstance(row.get("sync_variants"), list):
            merged["sync_variants"] = row.get("sync_variants")
        return merged
    return row


def _clean_category_label(value: Any) -> str:
    text = " ".join(str(value or "").strip().split())
    if not text:
        return ""
    return text[:80]


def _extract_product_category_label(product: dict[str, Any]) -> str:
    candidates: list[Any] = [
        product.get("category_label"),
        product.get("main_category_name"),
        product.get("category_name"),
        product.get("type_name"),
        product.get("product_type_name"),
        product.get("type"),
        product.get("category"),
    ]

    main_category = product.get("main_category")
    if isinstance(main_category, dict):
        candidates.insert(0, main_category.get("name"))
        candidates.append(main_category.get("title"))

    nested_product = product.get("product")
    if isinstance(nested_product, dict):
        candidates.extend(
            [
                nested_product.get("type_name"),
                nested_product.get("product_type_name"),
                nested_product.get("type"),
                nested_product.get("category"),
            ]
        )

    for raw in candidates:
        label = _clean_category_label(raw)
        if label:
            return label
    return ""


def _extract_variants(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(payload.get("sync_variants"), list):
        return [row for row in payload["sync_variants"] if isinstance(row, dict)]
    if isinstance(payload.get("variants"), list):
        return [row for row in payload["variants"] if isinstance(row, dict)]

    result = payload.get("result")
    if isinstance(result, dict):
        if isinstance(result.get("sync_variants"), list):
            return [row for row in result["sync_variants"] if isinstance(row, dict)]
        if isinstance(result.get("variants"), list):
            return [row for row in result["variants"] if isinstance(row, dict)]
    return []


def _build_price_label(variants: list[dict[str, Any]]) -> str:
    prices: list[Decimal] = []
    for variant in variants:
        price = _coerce_decimal(variant.get("retail_price") or variant.get("price"))
        if price is not None:
            prices.append(price)

    if not prices:
        return ""

    low = min(prices)
    high = max(prices)
    if low == high:
        return format_currency(low, include_code=False)
    return f"From {format_currency(low, include_code=False)}"


def _build_base_price(variants: list[dict[str, Any]]) -> str:
    prices: list[Decimal] = []
    for variant in variants:
        price = _coerce_decimal(variant.get("retail_price") or variant.get("price"))
        if price is not None:
            prices.append(price)
    if not prices:
        return ""
    return str(min(prices))


def _variant_option_name(product_name: str, variant_name: str, index: int) -> str:
    source = (variant_name or "").strip()
    if not source:
        return f"Option {index}"

    product = (product_name or "").strip()
    if product and source.lower().startswith(product.lower()):
        trimmed = source[len(product):].strip(" /-")
        if trimmed:
            return trimmed[:120]
    return source[:120]


def _extract_variant_image_url(variant: dict[str, Any]) -> str:
    """
    Best-effort extraction for a variant preview image URL.
    Printful payload shapes vary depending on endpoint/store type, so this is intentionally defensive.
    """
    for key in (
        "thumbnail_url",
        "image_url",
        "preview_url",
        "mockup_url",
        "url",
    ):
        candidate = (variant.get(key) or "").strip()
        if candidate:
            return candidate

    files = variant.get("files")
    if isinstance(files, list):
        for file_row in files:
            if not isinstance(file_row, dict):
                continue
            for key in ("preview_url", "thumbnail_url", "url"):
                candidate = (file_row.get(key) or "").strip()
                if candidate:
                    return candidate
    return ""


def _extract_variant_color_label(variant: dict[str, Any]) -> str:
    for key in ("color", "colour", "color_name", "colour_name"):
        candidate = " ".join(str(variant.get(key) or "").strip().split())
        if candidate:
            return candidate[:60]

    for nested_key in ("options", "variant"):
        nested = variant.get(nested_key)
        if not isinstance(nested, dict):
            continue
        for option_key, option_value in nested.items():
            if "color" in str(option_key).lower() or "colour" in str(option_key).lower():
                candidate = " ".join(str(option_value or "").strip().split())
                if candidate:
                    return candidate[:60]
    return ""


def _build_variants_payload(variants: list[dict[str, Any]], *, product_name: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, variant in enumerate(variants, start=1):
        price = _coerce_decimal(variant.get("retail_price") or variant.get("price"))
        sku = (variant.get("sku") or "").strip()
        row = {
            "id": _coerce_int(variant.get("id")),
            "name": _variant_option_name(product_name, str(variant.get("name") or ""), index),
            "sku": sku,
            "price": str(price) if price is not None else "",
            "currency": (variant.get("currency") or "").strip().upper(),
            # Optional extra metadata for richer merch listing UI.
            "image_url": _extract_variant_image_url(variant),
            "color": _extract_variant_color_label(variant),
        }
        rows.append(row)
    return rows


def _variant_currency(variants: list[dict[str, Any]]) -> str:
    for variant in variants:
        code = (variant.get("currency") or "").strip().upper()
        if code:
            return code
    return ""


def _build_variant_skus(variants: list[dict[str, Any]]) -> list[str]:
    skus: list[str] = []
    seen: set[str] = set()
    for variant in variants:
        raw = (variant.get("sku") or "").strip()
        if not raw:
            continue
        key = raw.lower()
        if key in seen:
            continue
        seen.add(key)
        skus.append(raw)
    return skus


def _build_product_url(*, product_id: int, name: str, external_id: str, catalog_url: str) -> str:
    ext = (external_id or "").strip()
    if ext.startswith("http://") or ext.startswith("https://"):
        return ext

    template = (getattr(settings, "PRINTFUL_MERCH_PRODUCT_URL_TEMPLATE", "") or "").strip()
    if template:
        try:
            return template.format(
                product_id=product_id,
                external_id=ext,
                slug=slugify(name or "") or f"item-{product_id}",
            )
        except Exception:
            logger.warning("Invalid PRINTFUL_MERCH_PRODUCT_URL_TEMPLATE: %s", template)

    return catalog_url


def _fetch_product_detail_variants(product_id: int) -> list[dict[str, Any]]:
    if not product_id:
        return []
    payload = _api_get(f"/sync/products/{product_id}")
    return _extract_variants(payload)


def get_printful_merch_feed(*, force_refresh: bool = False) -> dict[str, Any]:
    """
    Returns a normalized catalog payload for the merch page.
    """
    token = (getattr(settings, "PRINTFUL_TOKEN", "") or "").strip()
    catalog_url = (getattr(settings, "PRINTFUL_MERCH_CATALOG_URL", "") or "").strip()

    if not token:
        return {
            "enabled": False,
            "catalog_url": catalog_url,
            "products": [],
            "error": "",
        }

    limit = _int_setting("PRINTFUL_MERCH_LIMIT", 8, min_value=0)
    show_prices = bool(getattr(settings, "PRINTFUL_MERCH_SHOW_PRICE", True))
    cache_seconds = _int_setting("PRINTFUL_MERCH_CACHE_SECONDS", 300, min_value=0)
    store_id = (getattr(settings, "PRINTFUL_STORE_ID", "") or "").strip()
    cache_key = f"{_CACHE_PREFIX}:{store_id}:{limit}:{int(show_prices)}"

    if cache_seconds > 0 and not force_refresh:
        cached = cache.get(cache_key)
        if isinstance(cached, dict):
            return cached

    payload = {
        "enabled": True,
        "catalog_url": catalog_url,
        "products": [],
        "error": "",
    }

    try:
        # /sync/products works across connected platforms (Wix/Shopify/etc).
        # /store/products is limited to Manual Order / API stores.
        max_items = limit if limit > 0 else None
        page_size = min(max(limit or 24, 1), 24)
        offset = 0
        products: list[dict[str, Any]] = []

        while True:
            listing_payload = _api_get("/sync/products", query={"limit": page_size, "offset": offset})
            items = _extract_result_items(listing_payload)
            if not items:
                break

            for raw_item in items:
                item = _extract_product(raw_item)
                if not isinstance(item, dict):
                    continue
                if item.get("is_ignored") is True:
                    continue

                product_id = _coerce_int(item.get("id"))
                name = (item.get("name") or "").strip()
                if not product_id or not name:
                    continue

                variants = _extract_variants(item)
                if not variants:
                    try:
                        variants = _fetch_product_detail_variants(product_id)
                    except PrintfulAPIError:
                        variants = []

                variant_count = _coerce_int(item.get("variants"), default=len(variants))
                if variant_count <= 0 and variants:
                    variant_count = len(variants)

                products.append(
                    {
                        "id": product_id,
                        "name": name,
                        "category_label": _extract_product_category_label(item),
                        "image_url": (item.get("thumbnail_url") or "").strip(),
                        "price_label": _build_price_label(variants) if show_prices else "",
                        "base_price": _build_base_price(variants),
                        "variant_label": f"{variant_count} variants" if variant_count > 1 else "",
                        "currency": _variant_currency(variants),
                        "skus": _build_variant_skus(variants),
                        "variants": _build_variants_payload(variants, product_name=name),
                        "url": _build_product_url(
                            product_id=product_id,
                            name=name,
                            external_id=str(item.get("external_id") or ""),
                            catalog_url=catalog_url,
                        ),
                    }
                )

                if max_items is not None and len(products) >= max_items:
                    break

            if max_items is not None and len(products) >= max_items:
                break
            if len(items) < page_size:
                break
            offset += page_size

        payload["products"] = products
    except PrintfulAPIError as exc:
        payload["error"] = str(exc)
        logger.warning("Printful merch sync failed: %s", exc)

    if cache_seconds > 0:
        ttl = cache_seconds
        if payload.get("error"):
            ttl = max(30, min(cache_seconds, 90))
        cache.set(cache_key, payload, ttl)

    return payload
