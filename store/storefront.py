from __future__ import annotations

import json
from pathlib import Path
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse

from django.conf import settings
from django.db.models import Avg, Count
from django.forms import HiddenInput, Select, Textarea
from django.templatetags.static import static as static_url
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from core.services.lead_security import HONEYPOT_FIELD, build_form_token, ensure_session_key
from core.utils import apply_dealer_discount, format_currency

from .forms_store import CustomFitmentRequestForm, StoreReviewForm
from .models import Product, ProductOption, StoreInventorySettings, StoreShippingSettings, StoreReview


def request_wants_json(request) -> bool:
    if (request.GET.get("format") or "").strip().lower() == "json":
        return True
    accept = (request.headers.get("Accept") or "").lower()
    if "application/json" in accept:
        return True
    requested_with = (request.headers.get("X-Requested-With") or "").strip()
    return requested_with == "XMLHttpRequest"


def storefront_asset_version() -> str:
    asset_dir = Path(settings.BASE_DIR) / "static" / "storefront"
    asset_path = next(iter(sorted(asset_dir.glob("storefront-*.js"), reverse=True)), asset_dir / "storefront.js")
    try:
        return str(int(asset_path.stat().st_mtime))
    except (FileNotFoundError, OSError, ValueError):
        return "dev"


def _latest_storefront_asset(pattern: str, fallback_name: str) -> str:
    asset_dir = Path(settings.BASE_DIR) / "static" / "storefront"
    latest = next(iter(sorted(asset_dir.glob(pattern), reverse=True)), None)
    if latest is not None:
        return static_url(f"storefront/{latest.name}")
    return static_url(f"storefront/{fallback_name}")


def storefront_asset_urls() -> dict[str, str]:
    fallback = {
        "storefront_js_url": _latest_storefront_asset("storefront-*.js", "storefront.js"),
        "storefront_css_url": _latest_storefront_asset("storefront-*.css", "storefront.css"),
        "storefront_asset_version": storefront_asset_version(),
    }

    manifest_path = Path(settings.BASE_DIR) / "static" / "storefront" / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
        return fallback

    entry = manifest.get("frontend/storefront/src/main.jsx") or manifest.get("src/main.jsx")
    if not isinstance(entry, dict):
        entry = next(
            (
                item
                for item in manifest.values()
                if isinstance(item, dict) and item.get("isEntry") and str(item.get("src") or "").endswith("src/main.jsx")
            ),
            None,
        )
    if not isinstance(entry, dict):
        return fallback

    js_file = str(entry.get("file") or "").strip()
    css_files = [str(item).strip() for item in entry.get("css") or [] if str(item).strip()]
    if not css_files:
        style_entry = manifest.get("style.css")
        if isinstance(style_entry, dict):
            css_file = str(style_entry.get("file") or "").strip()
            if css_file:
                css_files = [css_file]
    if not css_files:
        css_files = [
            str(item.get("file") or "").strip()
            for item in manifest.values()
            if isinstance(item, dict) and str(item.get("file") or "").strip().endswith(".css")
        ]
    if not js_file:
        return fallback

    asset_context = {
        "storefront_js_url": static_url(f"storefront/{js_file}"),
        "storefront_css_url": static_url(f"storefront/{css_files[0]}") if css_files else fallback["storefront_css_url"],
        "storefront_asset_version": storefront_asset_version(),
    }
    return asset_context


def _to_decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0.00")


def _decimal_text(value: Any) -> str:
    return f"{_to_decimal(value):.2f}"


def _money_label(value: Any) -> str:
    return format_currency(value, include_code=False)


def _title_from_key(value: str) -> str:
    return (value or "").replace("_", " ").strip().title()


def _model_year_label(model) -> str:
    year_from = getattr(model, "year_from", None)
    year_to = getattr(model, "year_to", None)
    if year_from and year_to and year_from != year_to:
        return f"{year_from}-{year_to}"
    if year_from:
        return str(year_from)
    if year_to:
        return str(year_to)
    return ""


def _serialize_gallery(product: Product) -> list[dict[str, str]]:
    gallery: list[dict[str, str]] = []
    seen: set[str] = set()

    main_image_url = (getattr(product, "main_image_url", "") or "").strip()
    if main_image_url:
        gallery.append(
            {
                "src": main_image_url,
                "alt": (getattr(product, "name", "") or "Product").strip() or "Product",
            }
        )
        seen.add(main_image_url)

    image_items = getattr(product, "images", None)
    if image_items is None:
        return gallery

    for image in image_items.all():
        try:
            image_url = (image.image.url or "").strip()
        except Exception:
            image_url = ""
        if not image_url or image_url in seen:
            continue
        gallery.append(
            {
                "src": image_url,
                "alt": (getattr(image, "alt", "") or getattr(product, "name", "") or "Product image").strip(),
            }
        )
        seen.add(image_url)
    return gallery


def _serialize_specs(product: Product) -> list[dict[str, str]]:
    specs = getattr(product, "specs", None) or {}
    rows: list[dict[str, str]] = []
    if not isinstance(specs, dict):
        return rows
    for key, value in specs.items():
        if isinstance(value, (list, tuple)):
            display = ", ".join(str(item) for item in value if str(item).strip())
        elif isinstance(value, dict):
            display = ", ".join(f"{sub_key}: {sub_value}" for sub_key, sub_value in value.items())
        else:
            display = str(value or "").strip()
        if not display:
            continue
        rows.append({"label": _title_from_key(str(key)), "value": display})
    return rows


def _serialize_compatibility(product: Product, *, limit: int = 10) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    compatible_models = getattr(product, "compatible_models", None)
    if compatible_models is None:
        return rows

    for model in compatible_models.all()[:limit]:
        make_name = getattr(getattr(model, "make", None), "name", "") or ""
        model_name = getattr(model, "name", "") or ""
        years = _model_year_label(model)
        label = " ".join(part for part in (make_name, model_name, years) if part).strip()
        if not label:
            continue
        rows.append(
            {
                "label": label,
                "key": slugify(label)[:80] or str(getattr(model, "pk", "")),
            }
        )
    return rows


def _build_badges(product: Product) -> list[dict[str, str]]:
    badges: list[dict[str, str]] = []
    if getattr(product, "is_in_house", False):
        badges.append({"tone": "accent", "label": "In-house"})
    if getattr(product, "active_discount_percent", 0):
        badges.append({"tone": "sale", "label": f"{product.active_discount_percent}% off"})
    if getattr(product, "contact_for_estimate", False):
        badges.append({"tone": "neutral", "label": "Quote required"})
    elif getattr(product, "is_out_of_stock", False):
        badges.append({"tone": "warning", "label": "Out of stock"})
    elif getattr(product, "is_low_stock", False):
        badges.append({"tone": "warning", "label": f"Only {product.available_inventory} left"})
    if getattr(product, "is_merch_product", False):
        badges.append({"tone": "neutral", "label": "Merch"})
    return badges


def serialize_product_card(
    product: Product,
    *,
    dealer_discount: int = 0,
    mode: str = "store",
    category_label: str | None = None,
    category_key: str | None = None,
) -> dict[str, Any]:
    is_merch = bool(getattr(product, "is_merch_product", False))
    can_show_dealer = bool(dealer_discount and not is_merch and not getattr(product, "contact_for_estimate", False))
    public_price = _to_decimal(getattr(product, "public_price", Decimal("0.00")))
    display_price = _to_decimal(getattr(product, "display_price", public_price))
    dealer_price = apply_dealer_discount(display_price, dealer_discount) if can_show_dealer else public_price

    category = getattr(product, "category", None)
    compatibility_rows = _serialize_compatibility(product, limit=3)
    image_url = (getattr(product, "main_image_url", "") or "").strip()

    card = {
        "id": int(getattr(product, "pk", 0) or 0),
        "slug": getattr(product, "slug", "") or "",
        "mode": mode,
        "name": getattr(product, "name", "") or "",
        "shortDescription": (getattr(product, "short_description", "") or "").strip(),
        "description": (getattr(product, "description", "") or "").strip(),
        "sku": getattr(product, "sku", "") or "",
        "image": {
            "src": image_url,
            "alt": (getattr(product, "name", "") or "Product").strip() or "Product",
        },
        "category": {
            "label": category_label or getattr(category, "display_name", "") or "",
            "key": category_key or getattr(category, "slug", "") or "",
        },
        "price": {
            "contactForEstimate": bool(getattr(product, "contact_for_estimate", False)),
            "label": "Contact for estimate"
            if getattr(product, "contact_for_estimate", False)
            else _money_label(public_price),
            "value": _decimal_text(public_price),
            "hint": _money_label(getattr(product, "estimate_from_price", Decimal("0.00")))
            if getattr(product, "contact_for_estimate", False) and getattr(product, "estimate_from_price", None) is not None
            else ("From" if getattr(product, "has_option_price_overrides", False) else ""),
            "oldLabel": _money_label(getattr(product, "old_price"))
            if getattr(product, "old_price", None) is not None
            else "",
            "dealerLabel": _money_label(dealer_price) if can_show_dealer else "",
            "dealerSavingsLabel": _money_label(display_price - dealer_price) if can_show_dealer else "",
        },
        "badges": _build_badges(product),
        "compatibility": compatibility_rows,
        "hasOptions": bool(getattr(product, "has_active_options", False)),
        "detailUrl": product.get_absolute_url(),
        "fullDetailsUrl": product.get_absolute_url(),
        "quickView": True,
        "actionLabel": "Request quote"
        if getattr(product, "contact_for_estimate", False)
        else ("Choose options" if getattr(product, "has_active_options", False) else "View product"),
    }
    return card


def _slug_from_store_product_url(url: str) -> str:
    if not url:
        return ""
    path = urlparse(url).path.rstrip("/")
    marker = "/store/p/"
    if marker not in path:
        return ""
    return path.split(marker, 1)[-1].strip("/")


def serialize_merch_listing_row(row: dict[str, Any]) -> dict[str, Any]:
    store_product_url = (row.get("store_product_url") or row.get("url") or "").strip()
    product_slug = _slug_from_store_product_url(store_product_url)
    image_url = ""
    carousel_images = row.get("carousel_images")
    if isinstance(carousel_images, list) and carousel_images:
        image_url = str(carousel_images[0] or "").strip()
    if not image_url:
        image_url = str(row.get("image_url") or "").strip()

    base_price = _to_decimal(row.get("base_price") or "0.00")
    price_label = (row.get("price_label") or "").strip() or (_money_label(base_price) if base_price else "")
    category_label = (row.get("category_label") or "").strip()
    category_key = (row.get("category_key") or "").strip()
    badges: list[dict[str, str]] = [{"tone": "neutral", "label": "Merch"}]
    if category_label:
        badges.append({"tone": "accent", "label": category_label})

    return {
        "id": int(row.get("id") or 0),
        "slug": product_slug,
        "mode": "merch",
        "name": (row.get("name") or "").strip(),
        "shortDescription": category_label,
        "description": "",
        "sku": "",
        "image": {
            "src": image_url,
            "alt": (row.get("name") or "Merch").strip() or "Merch",
        },
        "category": {
            "label": category_label,
            "key": category_key,
        },
        "price": {
            "contactForEstimate": False,
            "label": price_label,
            "value": _decimal_text(base_price),
            "hint": "",
            "oldLabel": "",
            "dealerLabel": "",
            "dealerSavingsLabel": "",
        },
        "badges": badges,
        "compatibility": [],
        "hasOptions": bool(product_slug),
        "detailUrl": store_product_url,
        "fullDetailsUrl": store_product_url,
        "quickView": bool(product_slug),
        "actionLabel": (row.get("checkout_label") or ("Choose options" if product_slug else "View product")).strip(),
        "colorSwatches": row.get("color_swatches") if isinstance(row.get("color_swatches"), list) else [],
    }


def serialize_store_category(category, *, product_count: int = 0) -> dict[str, Any]:
    image_url = ""
    try:
        if getattr(category, "image", None):
            image_url = category.image.url
    except Exception:
        image_url = ""
    return {
        "id": int(getattr(category, "pk", 0) or 0),
        "slug": getattr(category, "slug", "") or "",
        "label": getattr(category, "display_name", "") or getattr(category, "name", "") or "",
        "description": (getattr(category, "description", "") or "").strip(),
        "imageUrl": image_url,
        "productCount": int(product_count or 0),
    }


def serialize_merch_category_card(card: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": (card.get("key") or "").strip(),
        "label": (card.get("label") or "").strip(),
        "description": (card.get("description") or "").strip(),
        "imageUrl": (card.get("cover_url") or "").strip(),
        "productCount": int(card.get("count") or 0),
        "isAll": bool(card.get("is_all")),
    }


def _serialize_form_field(bound_field, *, full_width_names: set[str] | None = None) -> dict[str, Any]:
    widget = bound_field.field.widget
    attrs = getattr(widget, "attrs", {}) or {}
    input_type = getattr(widget, "input_type", "text")
    if isinstance(widget, Textarea):
        input_type = "textarea"
    elif isinstance(widget, Select):
        input_type = "select"
    elif isinstance(widget, HiddenInput):
        input_type = "hidden"

    options: list[dict[str, str]] = []
    if input_type == "select":
        for value, label in getattr(bound_field.field, "choices", []):
            options.append(
                {
                    "value": "" if value is None else str(value),
                    "label": str(label),
                }
            )

    value = bound_field.value()
    if value is None:
        normalized_value = ""
    elif isinstance(value, (list, tuple)):
        normalized_value = [str(item) for item in value]
    else:
        normalized_value = str(value)

    return {
        "name": bound_field.name,
        "label": bound_field.label or _title_from_key(bound_field.name),
        "id": bound_field.id_for_label or bound_field.auto_id or "",
        "inputType": input_type,
        "required": bool(bound_field.field.required),
        "placeholder": attrs.get("placeholder", "") or "",
        "autocomplete": attrs.get("autocomplete", "") or "",
        "accept": attrs.get("accept", "") or "",
        "rows": int(attrs.get("rows") or 0) if str(attrs.get("rows") or "").isdigit() else 0,
        "value": normalized_value,
        "fullWidth": bool(full_width_names and bound_field.name in full_width_names),
        "options": options,
    }


def _lead_security_payload(request, *, purpose: str) -> dict[str, str]:
    if request is None:
        return {"honeypotName": HONEYPOT_FIELD, "formToken": ""}

    session_key = ensure_session_key(request)
    if session_key and "lead_first_seen_at" not in request.session:
        request.session["lead_first_seen_at"] = timezone.now().isoformat()

    token = build_form_token(session_key=session_key, purpose=purpose) if session_key else ""
    return {
        "honeypotName": HONEYPOT_FIELD,
        "formToken": token,
    }


def storefront_lead_security_payload(request, *, purpose: str) -> dict[str, str]:
    return _lead_security_payload(request, purpose=purpose)


def _serialize_fitment_request_form(product: Product, *, request) -> dict[str, Any]:
    if getattr(product, "is_merch_product", False):
        return {"enabled": False}

    form = CustomFitmentRequestForm(
        initial={
            "product": getattr(product, "pk", None),
            "source_url": request.build_absolute_uri(product.get_absolute_url()) if request is not None else product.get_absolute_url(),
        }
    )
    full_width_names = {"message", "reference_image"}
    fields = [
        _serialize_form_field(form[name], full_width_names=full_width_names)
        for name in (
            "customer_name",
            "email",
            "phone",
            "vehicle",
            "submodel",
            "performance_goals",
            "budget",
            "timeline",
            "message",
            "reference_image",
        )
    ]
    return {
        "enabled": True,
        "actionUrl": product.get_absolute_url(),
        "eyebrow": "Custom fitment brief",
        "title": "Share the inputs, we'll send the plan",
        "intro": (
            "Outline your vehicle, performance targets, and timeline. "
            "The build desk will confirm availability, pricing, and next steps in writing."
        ),
        "submitLabel": "Submit request",
        "footnote": "Response time: 1-2 business days to reply.",
        "leadSecurity": storefront_lead_security_payload(request, purpose="fitment_request"),
        "fields": fields,
    }


def _serialize_review_payload(product: Product, *, request) -> dict[str, Any]:
    review_initial: dict[str, str] = {}
    if request is not None and getattr(getattr(request, "user", None), "is_authenticated", False):
        review_initial = {
            "reviewer_name": request.user.get_full_name() or request.user.username or "",
            "reviewer_email": request.user.email or "",
        }

    form = StoreReviewForm(initial=review_initial)
    full_width_names = {"title", "body"}
    fields = [
        _serialize_form_field(form[name], full_width_names=full_width_names)
        for name in (
            "reviewer_name",
            "reviewer_email",
            "reviewer_title",
            "rating",
            "title",
            "body",
        )
    ]

    approved_reviews_qs = StoreReview.objects.filter(
        product=product,
        status=StoreReview.Status.APPROVED,
    ).order_by("-approved_at", "-created_at")
    stats = approved_reviews_qs.aggregate(avg=Avg("rating"), count=Count("id"))
    items = [
        {
            "id": int(review.pk or 0),
            "rating": int(review.rating or 0),
            "stars": "★" * int(review.rating or 0),
            "title": (review.title or "").strip(),
            "body": (review.body or "").strip(),
            "reviewerName": (review.reviewer_name or "").strip(),
            "reviewerTitle": (review.reviewer_title or "").strip(),
        }
        for review in approved_reviews_qs[:6]
    ]

    return {
        "enabled": True,
        "actionUrl": product.get_absolute_url(),
        "submitLabel": "Submit review",
        "successMessage": "Thanks for the review. It's in the approval queue now.",
        "leadSecurity": storefront_lead_security_payload(request, purpose="store_review"),
        "stats": {
            "average": float(stats["avg"]) if stats.get("avg") is not None else None,
            "count": int(stats.get("count") or 0),
        },
        "items": items,
        "fields": fields,
    }


def serialize_product_detail(product: Product, *, request, dealer_discount: int = 0) -> dict[str, Any]:
    options = list(product.get_active_options())
    default_option = next((opt for opt in options if not getattr(opt, "is_separator", False)), None)
    allow_out_of_stock_orders = StoreInventorySettings.get_allow_out_of_stock_orders()
    can_show_dealer = bool(
        dealer_discount and not getattr(product, "is_merch_product", False) and not getattr(product, "contact_for_estimate", False)
    )

    inventory_notice = ""
    if not getattr(product, "contact_for_estimate", False):
        if not allow_out_of_stock_orders and getattr(product, "is_out_of_stock", False):
            inventory_notice = "Out of stock right now. This item cannot be ordered until inventory is updated."
        elif getattr(product, "is_low_stock", False):
            inventory_notice = f"Only {product.available_inventory} left in stock."

    compatible_rows = _serialize_compatibility(product, limit=18)
    gallery = _serialize_gallery(product)
    specs = _serialize_specs(product)
    related = [
        serialize_product_card(item, dealer_discount=dealer_discount)
        for item in product.get_companion_items(limit=4)
    ]

    option_payload = []
    for option in options:
        if getattr(option, "is_separator", False):
            option_payload.append(
                {
                    "id": int(getattr(option, "pk", 0) or 0),
                    "name": getattr(option, "name", "") or "",
                    "description": "",
                    "isSeparator": True,
                    "column": int(getattr(option, "option_column", 1) or 1),
                    "priceLabel": "",
                    "dealerPriceLabel": "",
                    "selected": False,
                }
            )
            continue

        option_price = _to_decimal(getattr(option, "discounted_price", Decimal("0.00")))
        dealer_price = apply_dealer_discount(_to_decimal(getattr(option, "unit_price", option_price)), dealer_discount)
        option_payload.append(
            {
                "id": int(getattr(option, "pk", 0) or 0),
                "name": getattr(option, "name", "") or "",
                "description": (getattr(option, "description", "") or "").strip(),
                "isSeparator": False,
                "column": int(getattr(option, "option_column", 1) or 1),
                "priceLabel": _money_label(option_price),
                "priceValue": _decimal_text(option_price),
                "dealerPriceLabel": _money_label(dealer_price) if can_show_dealer else "",
                "selected": bool(default_option and option.pk == default_option.pk),
            }
        )

    has_column_two = any(
        not option["isSeparator"] and int(option.get("column") or 1) == 2
        for option in option_payload
    )
    selectable_option_count = sum(1 for option in option_payload if not option["isSeparator"])
    if option_payload and not has_column_two and selectable_option_count >= 10:
        midpoint = max(1, (len(option_payload) + 1) // 2)
        for index, option in enumerate(option_payload):
            option["column"] = 1 if index < midpoint else 2

    free_shipping_threshold = StoreShippingSettings.get_free_shipping_threshold_cad()

    return {
        "product": serialize_product_card(product, dealer_discount=dealer_discount),
        "gallery": gallery,
        "description": (getattr(product, "description", "") or "").strip(),
        "specs": specs,
        "compatibility": {
            "note": (getattr(product, "compatibility", "") or "").strip(),
            "items": compatible_rows,
        },
        "options": option_payload,
        "optionLabels": {
            "column1": (getattr(product, "option_column_1_label", "") or "").strip() or "Options",
            "column2": (getattr(product, "option_column_2_label", "") or "").strip() or "More options",
        },
        "purchase": {
            "contactMode": bool(getattr(product, "contact_for_estimate", False)),
            "requiresOptionSelection": bool(getattr(product, "has_active_options", False) and not getattr(product, "contact_for_estimate", False)),
            "canAddToCart": bool(
                getattr(product, "contact_for_estimate", False)
                or allow_out_of_stock_orders
                or not getattr(product, "is_out_of_stock", False)
            ),
            "inventoryNotice": inventory_notice,
            "qtyMin": 1,
            "qtyMax": None if allow_out_of_stock_orders else int(getattr(product, "available_inventory", 0) or 0),
            "defaultOptionId": int(getattr(default_option, "pk", 0) or 0) if default_option else None,
            "cartActionUrl": reverse("store-cart-add", kwargs={"slug": product.slug}),
            "cartUrl": reverse("store-cart"),
            "checkoutUrl": reverse("store-checkout"),
            "contactUrl": f"{reverse('home')}#contact",
            "fullDetailsUrl": product.get_absolute_url(),
            "referenceUpload": {
                "enabled": True,
                "requiresLogin": not bool(getattr(getattr(request, "user", None), "is_authenticated", False)),
                "accept": "image/*",
            },
            "freeShippingHint": _money_label(free_shipping_threshold)
            if free_shipping_threshold and getattr(product, "is_merch_product", False)
            else "",
        },
        "fitmentRequest": _serialize_fitment_request_form(product, request=request),
        "reviews": _serialize_review_payload(product, request=request),
        "relatedProducts": related,
    }


def storefront_shell_payload(*, mode: str, listing_url: str, cart_item_count: int = 0, cart_line_count: int = 0) -> dict[str, Any]:
    return {
        "mode": mode,
        "endpoints": {
            "listing": listing_url,
            "cart": reverse("store-cart"),
            "checkout": reverse("store-checkout"),
        },
        "cart": {
            "itemCount": int(cart_item_count or 0),
            "lineCount": int(cart_line_count or 0),
        },
        "currency": {
            "code": (getattr(settings, "DEFAULT_CURRENCY_CODE", "CAD") or "CAD").upper(),
            "symbol": getattr(settings, "DEFAULT_CURRENCY_SYMBOL", "$") or "$",
        },
    }
