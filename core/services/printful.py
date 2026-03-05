from __future__ import annotations

"""
Printful storefront and fulfillment integration.

This module handles the merch catalog sync plus the low-level API calls used for
live shipping-rate lookups, order submission, and webhook subscription sync.
"""

import json
import logging
import hashlib
import time
from pathlib import Path
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


def _printful_cache_dir() -> Path:
    root = getattr(settings, "MEDIA_ROOT", "") or ""
    if root:
        base = Path(root)
    else:
        base = Path(getattr(settings, "BASE_DIR", Path(__file__).resolve().parents[2])) / "media"
    return base / "cache"


def _last_good_payload_path(key: str) -> Path:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]
    return _printful_cache_dir() / f"printful_merch_{digest}.json"


def _read_last_good_payload(key: str) -> dict[str, Any] | None:
    try:
        path = _last_good_payload_path(key)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and payload.get("products"):
            return payload
    except Exception as exc:
        logger.warning("Failed to read cached Printful merch payload: %s", exc)
    return None


def _write_last_good_payload(payload: dict[str, Any], key: str, *, min_interval: int = 300) -> None:
    if not payload.get("products"):
        return
    try:
        path = _last_good_payload_path(key)
        if path.exists() and min_interval > 0:
            age = time.time() - path.stat().st_mtime
            if age < min_interval:
                return
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(path)
    except Exception as exc:
        logger.warning("Failed to write cached Printful merch payload: %s", exc)


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


def _api_request(
    method: str,
    path: str,
    *,
    query: dict[str, Any] | None = None,
    data: dict[str, Any] | list[Any] | None = None,
) -> dict[str, Any]:
    base_url = (getattr(settings, "PRINTFUL_API_BASE_URL", "https://api.printful.com") or "https://api.printful.com").strip()
    if not base_url:
        base_url = "https://api.printful.com"
    base_url = base_url.rstrip("/")
    url = f"{base_url}{path}"
    if query:
        url = f"{url}?{urlencode(query, doseq=True)}"

    headers = _build_headers()
    body = None
    if data is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(data).encode("utf-8")

    req = Request(url, data=body, headers=headers, method=(method or "GET").upper())
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


def _api_get(path: str, *, query: dict[str, Any] | None = None) -> dict[str, Any]:
    return _api_request("GET", path, query=query)


def _api_post(
    path: str,
    *,
    query: dict[str, Any] | None = None,
    data: dict[str, Any] | list[Any] | None = None,
) -> dict[str, Any]:
    return _api_request("POST", path, query=query, data=data)


def _api_delete(path: str, *, query: dict[str, Any] | None = None) -> dict[str, Any]:
    return _api_request("DELETE", path, query=query)


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


def _extract_catalog_variant_id(variant: dict[str, Any]) -> int:
    candidate = _coerce_int(variant.get("variant_id"))
    if candidate > 0:
        return candidate
    nested = variant.get("variant")
    if isinstance(nested, dict):
        candidate = _coerce_int(nested.get("id"))
        if candidate > 0:
            return candidate
    return 0


def _extract_variant_external_id(variant: dict[str, Any]) -> str:
    value = (variant.get("external_id") or "").strip()
    if value:
        return value[:140]
    nested = variant.get("variant")
    if isinstance(nested, dict):
        value = (nested.get("external_id") or "").strip()
        if value:
            return value[:140]
    return ""


def _build_variants_payload(variants: list[dict[str, Any]], *, product_name: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, variant in enumerate(variants, start=1):
        price = _coerce_decimal(variant.get("retail_price") or variant.get("price"))
        sku = (variant.get("sku") or "").strip()
        sync_variant_id = _coerce_int(variant.get("id"))
        row = {
            "id": sync_variant_id,
            "sync_variant_id": sync_variant_id,
            "variant_id": _extract_catalog_variant_id(variant),
            "external_id": _extract_variant_external_id(variant),
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
    last_good_key = f"{_CACHE_PREFIX}:last_good:{store_id}:{limit}:{int(show_prices)}"
    disk_key = f"{store_id}:{limit}:{int(show_prices)}"
    disk_payload: dict[str, Any] | None = None

    if cache_seconds > 0 and not force_refresh:
        cached = cache.get(cache_key)
        if isinstance(cached, dict):
            if cached.get("products") or not cached.get("error"):
                _write_last_good_payload(cached, disk_key, min_interval=cache_seconds or 300)
                return cached
            last_good = cache.get(last_good_key)
            if isinstance(last_good, dict) and last_good.get("products"):
                _write_last_good_payload(last_good, disk_key, min_interval=cache_seconds or 300)
                return last_good
            disk_payload = _read_last_good_payload(disk_key)
            if isinstance(disk_payload, dict):
                return disk_payload
        # Keep a disk snapshot as a fallback, but still attempt a live fetch first.
        disk_payload = _read_last_good_payload(disk_key)

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
                        "sync_product_id": product_id,
                        "external_id": str(item.get("external_id") or "")[:140],
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

    if payload.get("error"):
        last_good = cache.get(last_good_key)
        if isinstance(last_good, dict) and last_good.get("products"):
            _write_last_good_payload(last_good, disk_key, min_interval=cache_seconds or 300)
            return last_good
        if isinstance(disk_payload, dict):
            return disk_payload
        disk_payload = _read_last_good_payload(disk_key)
        if isinstance(disk_payload, dict):
            return disk_payload

    if cache_seconds > 0:
        ttl = cache_seconds
        if payload.get("error"):
            ttl = max(30, min(cache_seconds, 90))
        cache.set(cache_key, payload, ttl)
        if payload.get("products"):
            cache.set(last_good_key, payload, max(cache_seconds, 1800))
            _write_last_good_payload(payload, disk_key, min_interval=cache_seconds or 300)

    return payload


def printful_is_enabled() -> bool:
    return bool((getattr(settings, "PRINTFUL_TOKEN", "") or "").strip())


def _shipping_rates_cache_key(*, recipient: dict[str, Any], items: list[dict[str, Any]], currency: str) -> str:
    digest = hashlib.sha256(
        json.dumps(
            {
                "recipient": recipient,
                "items": items,
                "currency": currency,
                "store_id": (getattr(settings, "PRINTFUL_STORE_ID", "") or "").strip(),
            },
            sort_keys=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    return f"{_CACHE_PREFIX}:shipping_rates:{digest}"


def quote_printful_shipping_rates(
    *,
    recipient: dict[str, Any],
    items: list[dict[str, Any]],
    currency: str = "",
    force_refresh: bool = False,
) -> list[dict[str, Any]]:
    if not printful_is_enabled():
        raise PrintfulAPIError("disabled")

    normalized_currency = (currency or "").strip().upper()
    payload: dict[str, Any] = {
        "recipient": recipient,
        "items": items,
    }
    if normalized_currency:
        payload["currency"] = normalized_currency

    cache_key = _shipping_rates_cache_key(recipient=recipient, items=items, currency=normalized_currency)
    cache_seconds = _int_setting("PRINTFUL_MERCH_CACHE_SECONDS", 300, min_value=0)
    if cache_seconds > 0 and not force_refresh:
        cached = cache.get(cache_key)
        if isinstance(cached, list):
            return cached

    response = _api_post("/shipping/rates", data=payload)
    result = response.get("result")
    rows = result if isinstance(result, list) else []

    normalized_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        amount = _coerce_decimal(
            row.get("rate")
            or row.get("price")
            or row.get("cost")
            or row.get("amount")
        )
        rate_id = " ".join(
            str(
                row.get("id")
                or row.get("shipping")
                or row.get("service_code")
                or row.get("code")
                or ""
            ).split()
        )[:80]
        name = " ".join(
            str(
                row.get("name")
                or row.get("title")
                or row.get("shipping_service_name")
                or row.get("shipping")
                or rate_id
            ).split()
        )[:160]
        if not rate_id or not name or amount is None:
            continue
        normalized_rows.append(
            {
                "id": rate_id,
                "name": name,
                "rate": str(amount.quantize(Decimal("0.01"))),
                "currency": (row.get("currency") or normalized_currency or "").strip().upper(),
                "min_delivery_days": _coerce_int(row.get("minDeliveryDays")),
                "max_delivery_days": _coerce_int(row.get("maxDeliveryDays")),
                "min_delivery_date": (row.get("minDeliveryDate") or "").strip(),
                "max_delivery_date": (row.get("maxDeliveryDate") or "").strip(),
            }
        )

    normalized_rows.sort(key=lambda item: (_coerce_decimal(item.get("rate")) or Decimal("0.00"), item.get("name") or ""))
    if cache_seconds > 0:
        cache.set(cache_key, normalized_rows, min(cache_seconds, 300))
    return normalized_rows


def create_printful_order(
    *,
    recipient: dict[str, Any],
    items: list[dict[str, Any]],
    shipping: str = "",
    external_id: str = "",
    notes: str = "",
    retail_costs: dict[str, Any] | None = None,
    confirm: bool = True,
) -> dict[str, Any]:
    if not printful_is_enabled():
        raise PrintfulAPIError("disabled")

    payload: dict[str, Any] = {
        "recipient": recipient,
        "items": items,
    }
    if shipping:
        payload["shipping"] = shipping
    if external_id:
        payload["external_id"] = external_id[:140]
    if notes:
        payload["notes"] = notes[:6000]
    if retail_costs:
        payload["retail_costs"] = retail_costs

    response = _api_post("/orders", query={"confirm": 1 if confirm else 0}, data=payload)
    result = response.get("result")
    return result if isinstance(result, dict) else {}


def get_printful_order(order_id: int) -> dict[str, Any]:
    if not order_id:
        return {}
    response = _api_get(f"/orders/{int(order_id)}")
    result = response.get("result")
    return result if isinstance(result, dict) else {}


def find_printful_order_by_external_id(
    external_id: str,
    *,
    page_size: int = 100,
    max_pages: int = 10,
) -> dict[str, Any]:
    normalized_external_id = (external_id or "").strip()[:140]
    if not normalized_external_id:
        return {}

    normalized_page_size = max(1, min(int(page_size or 100), 100))
    normalized_max_pages = max(1, int(max_pages or 10))
    offset = 0

    for _ in range(normalized_max_pages):
        response = _api_get("/orders", query={"limit": normalized_page_size, "offset": offset})
        result = response.get("result")
        rows = result if isinstance(result, list) else []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("external_id") or "").strip()[:140] == normalized_external_id:
                return row

        paging = response.get("paging") if isinstance(response.get("paging"), dict) else {}
        total = _coerce_int(paging.get("total"), default=0)
        if len(rows) < normalized_page_size:
            break
        offset += normalized_page_size
        if total and offset >= total:
            break

    return {}


def cancel_printful_order(order_id: int) -> dict[str, Any]:
    if not order_id:
        return {}
    response = _api_delete(f"/orders/{int(order_id)}")
    result = response.get("result")
    return result if isinstance(result, dict) else {}


def get_printful_webhook() -> dict[str, Any]:
    response = _api_get("/webhooks")
    result = response.get("result")
    return result if isinstance(result, dict) else {}


def upsert_printful_webhook(*, url: str, types: list[str], params: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    payload = {
        "url": (url or "").strip(),
        "types": [str(item).strip() for item in (types or []) if str(item).strip()],
        "params": params or [],
    }
    response = _api_post("/webhooks", data=payload)
    result = response.get("result")
    return result if isinstance(result, dict) else {}
