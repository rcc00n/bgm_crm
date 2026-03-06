from __future__ import annotations

import hashlib
import json
import logging
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from core.models import Payment, PaymentMethod
from core.services.printful import (
    PrintfulAPIError,
    create_printful_order,
    find_printful_order_by_external_id,
    get_printful_order,
    quote_printful_shipping_rates,
    upsert_printful_webhook,
)
from store.models import Order, PrintfulWebhookEvent, ProductOption
from store.printful_catalog import parse_printful_product_id_from_sku, sync_printful_merch_product

logger = logging.getLogger(__name__)

PRINTFUL_WEBHOOK_TYPES = [
    "package_shipped",
    "package_returned",
    "order_updated",
    "order_put_hold",
    "order_remove_hold",
]

PAYMENT_QUANT = Decimal("0.01")

COUNTRY_CODE_ALIASES = {
    "ca": "CA",
    "can": "CA",
    "canada": "CA",
    "us": "US",
    "usa": "US",
    "united states": "US",
    "united states of america": "US",
    "mx": "MX",
    "mexico": "MX",
    "gb": "GB",
    "uk": "GB",
    "united kingdom": "GB",
    "au": "AU",
    "australia": "AU",
    "nz": "NZ",
    "new zealand": "NZ",
}

REGION_CODE_ALIASES = {
    "CA": {
        "alberta": "AB",
        "ab": "AB",
        "british columbia": "BC",
        "bc": "BC",
        "manitoba": "MB",
        "mb": "MB",
        "new brunswick": "NB",
        "nb": "NB",
        "newfoundland and labrador": "NL",
        "newfoundland": "NL",
        "nl": "NL",
        "nova scotia": "NS",
        "ns": "NS",
        "northwest territories": "NT",
        "nt": "NT",
        "nunavut": "NU",
        "nu": "NU",
        "ontario": "ON",
        "on": "ON",
        "prince edward island": "PE",
        "pei": "PE",
        "pe": "PE",
        "quebec": "QC",
        "qc": "QC",
        "saskatchewan": "SK",
        "sk": "SK",
        "yukon": "YT",
        "yt": "YT",
    },
    "US": {
        "alabama": "AL",
        "al": "AL",
        "alaska": "AK",
        "ak": "AK",
        "arizona": "AZ",
        "az": "AZ",
        "arkansas": "AR",
        "ar": "AR",
        "california": "CA",
        "ca": "CA",
        "colorado": "CO",
        "co": "CO",
        "connecticut": "CT",
        "ct": "CT",
        "delaware": "DE",
        "de": "DE",
        "district of columbia": "DC",
        "dc": "DC",
        "florida": "FL",
        "fl": "FL",
        "georgia": "GA",
        "ga": "GA",
        "hawaii": "HI",
        "hi": "HI",
        "idaho": "ID",
        "id": "ID",
        "illinois": "IL",
        "il": "IL",
        "indiana": "IN",
        "in": "IN",
        "iowa": "IA",
        "ia": "IA",
        "kansas": "KS",
        "ks": "KS",
        "kentucky": "KY",
        "ky": "KY",
        "louisiana": "LA",
        "la": "LA",
        "maine": "ME",
        "me": "ME",
        "maryland": "MD",
        "md": "MD",
        "massachusetts": "MA",
        "ma": "MA",
        "michigan": "MI",
        "mi": "MI",
        "minnesota": "MN",
        "mn": "MN",
        "mississippi": "MS",
        "ms": "MS",
        "missouri": "MO",
        "mo": "MO",
        "montana": "MT",
        "mt": "MT",
        "nebraska": "NE",
        "ne": "NE",
        "nevada": "NV",
        "nv": "NV",
        "new hampshire": "NH",
        "nh": "NH",
        "new jersey": "NJ",
        "nj": "NJ",
        "new mexico": "NM",
        "nm": "NM",
        "new york": "NY",
        "ny": "NY",
        "north carolina": "NC",
        "nc": "NC",
        "north dakota": "ND",
        "nd": "ND",
        "ohio": "OH",
        "oh": "OH",
        "oklahoma": "OK",
        "ok": "OK",
        "oregon": "OR",
        "or": "OR",
        "pennsylvania": "PA",
        "pa": "PA",
        "rhode island": "RI",
        "ri": "RI",
        "south carolina": "SC",
        "sc": "SC",
        "south dakota": "SD",
        "sd": "SD",
        "tennessee": "TN",
        "tn": "TN",
        "texas": "TX",
        "tx": "TX",
        "utah": "UT",
        "ut": "UT",
        "vermont": "VT",
        "vt": "VT",
        "virginia": "VA",
        "va": "VA",
        "washington": "WA",
        "wa": "WA",
        "west virginia": "WV",
        "wv": "WV",
        "wisconsin": "WI",
        "wi": "WI",
        "wyoming": "WY",
        "wy": "WY",
    },
}


def _is_merch_product(product) -> bool:
    if not product:
        return False
    category_slug = (getattr(getattr(product, "category", None), "slug", "") or "").strip().lower()
    sku = (getattr(product, "sku", "") or "").strip().upper()
    slug = (getattr(product, "slug", "") or "").strip().lower()
    return category_slug == "merch" or sku.startswith("PF-") or slug.startswith("merch-")


def cart_is_merch_only(positions: list[dict[str, Any]]) -> bool:
    products = [row.get("product") for row in (positions or []) if row.get("product")]
    return bool(products) and all(_is_merch_product(product) for product in products)


def normalize_country_code(value: str) -> str:
    raw = " ".join(str(value or "").strip().split()).lower()
    if not raw:
        return ""
    if len(raw) == 2 and raw.isalpha():
        return raw.upper()
    return COUNTRY_CODE_ALIASES.get(raw, "")


def normalize_region_code(country_code: str, value: str) -> str:
    normalized_country = (country_code or "").strip().upper()
    raw = " ".join(str(value or "").strip().split()).lower()
    if not raw:
        return ""
    if len(raw) == 2 and raw.isalpha():
        return raw.upper()
    return REGION_CODE_ALIASES.get(normalized_country, {}).get(raw, "")


def normalize_postal_code(value: str) -> str:
    cleaned = "".join(ch for ch in str(value or "").upper() if ch.isalnum())
    if len(cleaned) >= 6 and cleaned[:1].isalpha():
        return f"{cleaned[:3]} {cleaned[3:6]}"
    return cleaned


def _refresh_merch_option_mapping(product, option):
    if not product or not option:
        return option

    product_id = getattr(product, "printful_product_id", None) or parse_printful_product_id_from_sku(getattr(product, "sku", ""))
    if not product_id:
        return option

    option_pk = getattr(option, "pk", None) or getattr(option, "id", None)
    option_sku = (getattr(option, "sku", "") or "").strip()
    option_name = (getattr(option, "name", "") or "").strip()

    try:
        sync_printful_merch_product(product_id)
    except Exception:
        logger.exception(
            "Failed to refresh Printful variant mappings for merch product %s during checkout.",
            product_id,
        )
        return option

    refreshed = None
    if option_pk:
        refreshed = ProductOption.objects.filter(pk=option_pk).first()
    if refreshed is None and option_sku:
        refreshed = ProductOption.objects.filter(product=product, sku=option_sku).first()
    if refreshed is None and option_name:
        refreshed = ProductOption.objects.filter(product=product, name=option_name).first()
    return refreshed or option


def build_printful_recipient_from_form(form: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    country_code = normalize_country_code(form.get("country", ""))
    region_code = normalize_region_code(country_code, form.get("region", ""))
    postal_code = normalize_postal_code(form.get("postal_code", ""))
    errors: dict[str, str] = {}

    if not country_code:
        errors["country"] = "Enter a supported country for merch shipping."
    if not region_code and country_code in {"CA", "US"}:
        errors["region"] = "Enter a valid province/state code for merch shipping."
    if not postal_code:
        errors["postal_code"] = "Postal / ZIP code is required for merch shipping."

    recipient = {
        "name": (form.get("customer_name") or "").strip(),
        "address1": (form.get("address_line1") or "").strip(),
        "city": (form.get("city") or "").strip(),
        "state_code": region_code,
        "country_code": country_code,
        "zip": postal_code,
        "phone": (form.get("phone") or "").strip(),
        "email": (form.get("email") or "").strip(),
    }
    address2 = (form.get("address_line2") or "").strip()
    if address2:
        recipient["address2"] = address2
    return recipient, errors


def build_printful_shipping_items(positions: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    for entry in positions or []:
        product = entry.get("product")
        if not _is_merch_product(product):
            continue
        option = entry.get("option")
        qty = int(entry.get("qty") or 0)
        variant_id = getattr(option, "printful_variant_id", None) if option else None
        if option and not variant_id:
            option = _refresh_merch_option_mapping(product, option)
            variant_id = getattr(option, "printful_variant_id", None) if option else None
        if not option or not variant_id:
            label = getattr(product, "name", "Merch item")
            errors.append(f"{label} is missing a Printful shipping variant mapping.")
            continue
        items.append({"variant_id": int(variant_id), "quantity": max(1, qty)})
    return items, errors


def build_printful_order_items(order: Order) -> tuple[list[dict[str, Any]], list[str]]:
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    for order_item in order.items.select_related("product", "option").all():
        product = order_item.product
        if not _is_merch_product(product):
            continue
        option = order_item.option
        sync_variant_id = getattr(option, "printful_sync_variant_id", None) if option else None
        if option and not sync_variant_id:
            option = _refresh_merch_option_mapping(product, option)
            sync_variant_id = getattr(option, "printful_sync_variant_id", None) if option else None
        if not option or not sync_variant_id:
            errors.append(f"{product.name} is missing a Printful fulfillment variant mapping.")
            continue
        retail_price = order_item.price_at_moment or product.get_unit_price(option)
        payload = {
            "sync_variant_id": int(sync_variant_id),
            "quantity": int(order_item.qty or 1),
            "retail_price": str(Decimal(str(retail_price or "0.00")).quantize(PAYMENT_QUANT)),
        }
        if getattr(option, "printful_external_id", ""):
            payload["external_variant_id"] = option.printful_external_id[:140]
        items.append(payload)
    return items, errors


def get_checkout_printful_shipping(
    *,
    positions: list[dict[str, Any]],
    form: dict[str, Any],
    selected_rate_id: str = "",
    require_complete: bool = False,
) -> dict[str, Any]:
    if not cart_is_merch_only(positions):
        return {
            "rates": [],
            "selected_rate_id": "",
            "selected_rate": None,
            "shipping_cost": Decimal("0.00"),
            "shipping_name": "",
            "shipping_currency": "",
            "recipient": {},
            "errors": {},
            "error": "",
        }

    shipping_items, item_errors = build_printful_shipping_items(positions)
    if item_errors:
        return {
            "rates": [],
            "selected_rate_id": "",
            "selected_rate": None,
            "shipping_cost": Decimal("0.00"),
            "shipping_name": "",
            "shipping_currency": "",
            "recipient": {},
            "errors": {},
            "error": " ".join(item_errors),
        }

    recipient, recipient_errors = build_printful_recipient_from_form(form)
    quote_required_keys = ("address_line1", "city", "region", "postal_code", "country")
    incomplete = any(not (form.get(key) or "").strip() for key in quote_required_keys)
    missing_field_errors = {}
    if not (form.get("address_line1") or "").strip():
        missing_field_errors["address_line1"] = "Street and house/building are required for merch shipping."
    if not (form.get("city") or "").strip():
        missing_field_errors["city"] = "City is required for merch shipping."
    error_message = ""
    if recipient_errors and not incomplete:
        error_message = next(iter(recipient_errors.values()))
    elif incomplete and require_complete:
        error_message = "Complete the shipping address to get live merch rates."
    if incomplete or recipient_errors:
        return {
            "rates": [],
            "selected_rate_id": "",
            "selected_rate": None,
            "shipping_cost": Decimal("0.00"),
            "shipping_name": "",
            "shipping_currency": "",
            "recipient": recipient,
            "errors": {**missing_field_errors, **recipient_errors},
            "error": error_message,
        }

    try:
        rates = quote_printful_shipping_rates(
            recipient=recipient,
            items=shipping_items,
            currency=(getattr(settings, "DEFAULT_CURRENCY_CODE", "CAD") or "CAD").upper(),
        )
    except PrintfulAPIError as exc:
        logger.warning("Printful shipping-rate lookup failed: %s", exc)
        return {
            "rates": [],
            "selected_rate_id": "",
            "selected_rate": None,
            "shipping_cost": Decimal("0.00"),
            "shipping_name": "",
            "shipping_currency": "",
            "recipient": recipient,
            "errors": {},
            "error": "Live merch shipping is unavailable right now. Please try again in a moment.",
        }

    if not rates:
        return {
            "rates": [],
            "selected_rate_id": "",
            "selected_rate": None,
            "shipping_cost": Decimal("0.00"),
            "shipping_name": "",
            "shipping_currency": "",
            "recipient": recipient,
            "errors": {},
            "error": "No live merch shipping rates were returned for this address.",
        }

    normalized_selected_id = (selected_rate_id or "").strip()
    selected_rate = next((row for row in rates if row.get("id") == normalized_selected_id), None) or rates[0]
    shipping_cost = Decimal(str(selected_rate.get("rate") or "0.00")).quantize(PAYMENT_QUANT)
    return {
        "rates": rates,
        "selected_rate_id": selected_rate.get("id", ""),
        "selected_rate": selected_rate,
        "shipping_cost": shipping_cost,
        "shipping_name": selected_rate.get("name", ""),
        "shipping_currency": selected_rate.get("currency", ""),
        "recipient": recipient,
        "errors": {},
        "error": "",
    }


def build_printful_external_id(order: Order) -> str:
    existing = (order.printful_external_id or "").strip()
    if existing:
        return existing[:140]
    return f"bgm-order-{order.id}"[:140]


def _iter_tracking_payload_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []

    rows: list[dict[str, Any]] = []
    stack: list[dict[str, Any]] = [payload]
    seen: set[int] = set()
    while stack:
        candidate = stack.pop(0)
        marker = id(candidate)
        if marker in seen:
            continue
        seen.add(marker)
        rows.append(candidate)
        for key in ("result", "data", "order"):
            nested = candidate.get(key)
            if isinstance(nested, dict):
                stack.append(nested)
    return rows


def _shipment_text(shipment: dict[str, Any], *keys: str, max_length: int = 120) -> str:
    for key in keys:
        text = " ".join(str(shipment.get(key) or "").split())
        if text:
            return text[:max_length]
    return ""


def _normalize_tracking_events(value: Any) -> list[str]:
    rows: list[str] = []
    if not isinstance(value, list):
        return rows

    for raw_event in value:
        if isinstance(raw_event, dict):
            timestamp = _shipment_text(raw_event, "timestamp", "date", "datetime", "time", max_length=80)
            status = _shipment_text(raw_event, "status", "title", "state", max_length=80)
            message = _shipment_text(raw_event, "description", "message", "details", "detail", max_length=180)
            location = _shipment_text(raw_event, "location", "city", max_length=120)
            parts = [part for part in (status, message, location) if part]
            if timestamp and parts:
                rows.append(f"{timestamp}: {' - '.join(parts)}"[:240])
                continue
            if parts:
                rows.append(" - ".join(parts)[:240])
                continue
            fallback = " ".join(str(val or "").split() for val in raw_event.values() if str(val or "").strip())
            if fallback:
                rows.append(fallback[:240])
            continue

        text = " ".join(str(raw_event or "").split())
        if text:
            rows.append(text[:240])
    return rows


def _extract_tracking_entries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def _append_shipment(shipment: dict[str, Any]) -> None:
        numbers = shipment.get("tracking_number") or shipment.get("tracking_numbers") or shipment.get("tracking")
        urls = shipment.get("tracking_url") or shipment.get("tracking_urls") or shipment.get("url")
        number_list = numbers if isinstance(numbers, list) else [numbers]
        url_list = urls if isinstance(urls, list) else [urls]
        carrier = _shipment_text(shipment, "carrier", "carrier_name")
        estimated_delivery = _shipment_text(shipment, "estimated_delivery", "estimatedDelivery")
        shipment_date = _shipment_text(shipment, "shipment_date", "shipmentDate", "shipped_at")
        delivery_date = _shipment_text(shipment, "delivery_date", "deliveryDate", "delivered_at")
        tracking_events = _normalize_tracking_events(shipment.get("tracking_events") or shipment.get("trackingEvents"))
        if not any(" ".join(str(raw or "").split()) for raw in number_list) and shipment.get("tracking_number"):
            number_list = [shipment.get("tracking_number")]

        for idx, raw_number in enumerate(number_list):
            number = " ".join(str(raw_number or "").split())[:140]
            if not number:
                continue
            url = ""
            if idx < len(url_list):
                url = str(url_list[idx] or "").strip()[:500]
            if not url:
                url = str(shipment.get("tracking_url") or "").strip()[:500]
            key = (number, url)
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "number": number,
                    "url": url,
                    "carrier": carrier,
                    "estimated_delivery": estimated_delivery,
                    "shipment_date": shipment_date,
                    "delivery_date": delivery_date,
                    "tracking_events": tracking_events,
                }
            )

    for candidate in _iter_tracking_payload_candidates(payload):
        shipments = candidate.get("shipments")
        if isinstance(shipments, list):
            for shipment in shipments:
                if isinstance(shipment, dict):
                    _append_shipment(shipment)

        shipment = candidate.get("shipment")
        if isinstance(shipment, dict):
            _append_shipment(shipment)
    return rows


def sync_order_from_printful_payload(order: Order, payload: dict[str, Any]) -> Order:
    if not payload:
        return order

    tracking_entries = _extract_tracking_entries(payload)
    status = (payload.get("status") or "").strip()
    costs = payload.get("costs") if isinstance(payload.get("costs"), dict) else {}
    shipping_cost = Decimal(str(costs.get("shipping") or order.printful_shipping_cost or "0.00")).quantize(PAYMENT_QUANT)
    shipping_currency = (costs.get("currency") or order.printful_shipping_currency or "").strip().upper()

    update_fields = {
        "printful_order_id",
        "printful_external_id",
        "printful_status",
        "printful_shipping_cost",
        "printful_shipping_currency",
        "printful_shipping_name",
        "printful_tracking_data",
        "printful_last_synced_at",
        "printful_submitted_at",
        "printful_error",
    }
    order.printful_order_id = int(payload.get("id") or order.printful_order_id or 0) or None
    order.printful_external_id = (payload.get("external_id") or order.printful_external_id or "")[:140]
    order.printful_status = status[:40]
    order.printful_shipping_cost = shipping_cost
    order.printful_shipping_currency = shipping_currency
    order.printful_shipping_name = (payload.get("shipping_service_name") or payload.get("shipping") or order.printful_shipping_name or "")[:140]
    order.printful_tracking_data = tracking_entries
    order.printful_last_synced_at = timezone.now()
    if order.printful_order_id and not order.printful_submitted_at:
        order.printful_submitted_at = timezone.now()
    order.printful_error = (payload.get("error") or "")[:2000]

    if tracking_entries:
        numbers = []
        seen_numbers: set[str] = set()
        for entry in tracking_entries:
            number = (entry.get("number") or "").strip()
            if not number or number in seen_numbers:
                continue
            seen_numbers.add(number)
            numbers.append(number)
        if numbers:
            order.tracking_numbers = "\n".join(numbers)
            update_fields.add("tracking_numbers")
        first_url = next((entry.get("url") for entry in tracking_entries if entry.get("url")), "")
        if first_url:
            order.tracking_url = first_url[:500]
            update_fields.add("tracking_url")
        if order.status == Order.STATUS_PROCESSING:
            order.status = Order.STATUS_SHIPPED
            update_fields.update({"status", "shipped_at"})

    order.save(update_fields=list(update_fields))
    return order


def submit_paid_merch_order(order: Order) -> Order:
    if order.payment_status != Order.PaymentStatus.PAID:
        return order
    if order.printful_order_id:
        return order
    if order.delivery_method != "shipping":
        raise PrintfulAPIError("invalid_delivery_method")

    items, item_errors = build_printful_order_items(order)
    if item_errors:
        raise PrintfulAPIError("missing_variant_mapping")
    recipient, recipient_errors = build_printful_recipient_from_form(
        {
            "customer_name": order.customer_name,
            "email": order.email,
            "phone": order.phone,
            "address_line1": order.address_line1,
            "address_line2": order.address_line2,
            "city": order.city,
            "region": order.region,
            "postal_code": order.postal_code,
            "country": order.country,
        }
    )
    if recipient_errors:
        raise PrintfulAPIError("invalid_recipient")
    shipping_code = (order.printful_shipping_rate_id or "").strip()
    if not shipping_code:
        raise PrintfulAPIError("missing_shipping_rate")
    external_id = build_printful_external_id(order)
    if order.printful_external_id != external_id:
        order.printful_external_id = external_id
        order.save(update_fields=["printful_external_id"])

    existing_payload = find_printful_order_by_external_id(external_id)
    if existing_payload:
        return sync_order_from_printful_payload(order, existing_payload)

    try:
        payload = create_printful_order(
            recipient=recipient,
            items=items,
            shipping=shipping_code,
            external_id=external_id,
            notes=(order.notes or "")[:1000],
            confirm=True,
        )
    except PrintfulAPIError:
        recovered_payload = find_printful_order_by_external_id(external_id)
        if recovered_payload:
            return sync_order_from_printful_payload(order, recovered_payload)
        raise
    if not payload:
        recovered_payload = find_printful_order_by_external_id(external_id)
        if recovered_payload:
            return sync_order_from_printful_payload(order, recovered_payload)
        raise PrintfulAPIError("empty_order_response")

    return sync_order_from_printful_payload(order, payload)


def _ensure_etransfer_payment_entry(order: Order) -> None:
    if (order.payment_processor or "").strip().lower() != "etransfer":
        return
    if order.payments.filter(processor="etransfer").exists():
        return

    paid_amount = Decimal(str(order.payment_balance_due or order.payment_amount or "0.00")).quantize(PAYMENT_QUANT)
    if paid_amount <= 0:
        paid_amount = Decimal("0.00")

    method, _ = PaymentMethod.objects.get_or_create(name="Interac e-Transfer")
    Payment.objects.create(
        order=order,
        amount=paid_amount,
        currency=getattr(settings, "DEFAULT_CURRENCY_CODE", "CAD"),
        method=method,
        payment_mode=Payment.PaymentMode.FULL,
        balance_due=Decimal("0.00"),
        processor="etransfer",
        fee_amount=Decimal("0.00"),
    )

    order.payment_amount = paid_amount
    order.payment_balance_due = Decimal("0.00")
    order.save(update_fields=["payment_amount", "payment_balance_due"])


def handle_paid_order(order: Order) -> Order:
    _ensure_etransfer_payment_entry(order)
    merch_items = [item for item in order.items.select_related("product").all() if _is_merch_product(item.product)]
    if not merch_items:
        return order
    return submit_paid_merch_order(order)


def get_printful_webhook_secret() -> str:
    configured = (getattr(settings, "PRINTFUL_WEBHOOK_SECRET", "") or "").strip()
    if configured:
        return configured
    return hashlib.sha256(f"{settings.SECRET_KEY}:printful-webhook".encode("utf-8")).hexdigest()[:32]


def build_printful_webhook_url() -> str:
    base = (getattr(settings, "COMPANY_WEBSITE", "") or "").strip()
    if not base:
        return ""
    if not base.startswith(("http://", "https://")):
        base = f"https://{base}"
    return f"{base.rstrip('/')}{reverse('store:store-printful-webhook', kwargs={'secret': get_printful_webhook_secret()})}"


def sync_printful_webhook_subscription() -> dict[str, Any]:
    url = build_printful_webhook_url()
    if not url:
        raise PrintfulAPIError("missing_company_website")
    return upsert_printful_webhook(url=url, types=PRINTFUL_WEBHOOK_TYPES)


def _extract_order_refs_from_webhook(payload: dict[str, Any]) -> tuple[int, str]:
    nested_candidates: list[dict[str, Any]] = []
    for key in ("result", "data", "order"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            nested_candidates.append(nested)

    for candidate in nested_candidates:
        for key in ("order_id", "id"):
            value = candidate.get(key)
            try:
                parsed = int(value or 0)
            except (TypeError, ValueError):
                parsed = 0
            if parsed > 0:
                return parsed, str(candidate.get("external_id") or "").strip()[:140]

    top_level_order_id = payload.get("order_id")
    try:
        parsed_top_level = int(top_level_order_id or 0)
    except (TypeError, ValueError):
        parsed_top_level = 0
    if parsed_top_level > 0:
        return parsed_top_level, str(payload.get("external_id") or "").strip()[:140]

    for candidate in [*nested_candidates, payload]:
        external_id = str(candidate.get("external_id") or "").strip()[:140]
        if external_id:
            return 0, external_id
    return 0, ""


def record_printful_webhook(payload: dict[str, Any]) -> tuple[PrintfulWebhookEvent, Order | None]:
    serialized = json.dumps(payload, sort_keys=True, default=str)
    event_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    event_type = (
        payload.get("type")
        or payload.get("event")
        or payload.get("topic")
        or payload.get("name")
        or "printful"
    )

    printful_order_id, external_id = _extract_order_refs_from_webhook(payload)
    order = None
    if printful_order_id:
        order = Order.objects.filter(printful_order_id=printful_order_id).first()
    if order is None and external_id:
        order = Order.objects.filter(printful_external_id=external_id).first()

    event, created = PrintfulWebhookEvent.objects.get_or_create(
        event_hash=event_hash,
        defaults={
            "event_type": str(event_type)[:80],
            "order": order,
            "payload": payload,
        },
    )
    if not created:
        return event, order

    try:
        live_payload = {}
        if printful_order_id:
            live_payload = get_printful_order(printful_order_id)
        elif order and order.printful_order_id:
            live_payload = get_printful_order(order.printful_order_id)
        if order and live_payload:
            order = sync_order_from_printful_payload(order, live_payload)
        if order and (not live_payload or not order.tracking_entries) and _extract_tracking_entries(payload):
            order = sync_order_from_printful_payload(order, payload)
    except Exception:
        logger.exception("Failed to sync local order from Printful webhook payload")

    if order and event.order_id != order.id:
        event.order = order
        event.save(update_fields=["order"])
    return event, order


def handle_order_payment_status_transition(order_id: int) -> None:
    order = Order.objects.prefetch_related("payments").select_related("user").filter(pk=order_id).first()
    if not order or order.payment_status != Order.PaymentStatus.PAID:
        return
    try:
        handle_paid_order(order)
    except Exception as exc:
        logger.exception("Failed to process paid-order fulfillment hooks for order=%s", order_id)
        Order.objects.filter(pk=order_id).update(printful_error=str(exc)[:2000])
