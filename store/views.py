# store/views.py
from decimal import Decimal, ROUND_HALF_UP
import re
from typing import Dict, Iterable
import logging
import uuid
import json

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from core.email_templates import base_email_context, email_brand_name, join_text_sections, render_email_template
from core.emails import build_email_html, send_html_email
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from PIL import Image, UnidentifiedImageError
from square.client import Square, SquareEnvironment

from .models import (
    AbandonedCart,
    Category,
    Order,
    OrderItem,
    Product,
    ProductOption,
    CarMake,
    CarModel,
)
from .forms_store import ProductFilterForm, CustomFitmentRequestForm
from core.models import Payment, PaymentMethod, StorePageCopy
from core.utils import apply_dealer_discount, get_dealer_discount_percent
from notifications import services as notification_services

logger = logging.getLogger(__name__)

REFERENCE_IMAGE_MAX_MB = getattr(settings, "STORE_REFERENCE_IMAGE_MAX_MB", 8)
REFERENCE_IMAGE_MAX_BYTES = int(REFERENCE_IMAGE_MAX_MB * 1024 * 1024)

PAYMENT_QUANT = Decimal("0.01")


def _square_ready() -> bool:
    """
    Minimal flag to avoid trying to charge without credentials.
    """
    return bool(
        getattr(settings, "SQUARE_ACCESS_TOKEN", "")
        and getattr(settings, "SQUARE_LOCATION_ID", "")
        and getattr(settings, "SQUARE_APPLICATION_ID", "")
    )


def _square_client() -> Square:
    token = getattr(settings, "SQUARE_ACCESS_TOKEN", "")
    if not token:
        raise RuntimeError("Square access token is not configured.")
    env = getattr(settings, "SQUARE_ENVIRONMENT", "sandbox") or "sandbox"
    environment = SquareEnvironment.PRODUCTION if env.lower().startswith("prod") else SquareEnvironment.SANDBOX
    return Square(token=token, environment=environment)


def _get_decimal_setting(name: str, default: str) -> Decimal:
    """
    Safe Decimal coercion for numeric settings with a non-negative fallback.
    """
    try:
        raw = getattr(settings, name, default)
    except Exception:
        raw = default
    try:
        val = Decimal(str(raw))
    except Exception:
        val = Decimal(default)
    return val if val >= 0 else Decimal(default)


def _gross_up_with_fee(base: Decimal) -> tuple[Decimal, Decimal]:
    """
    Gross-up helper: returns (charge_amount, fee_component) so that after Square
    takes its fee you still net the target base amount.
    """
    if base <= 0:
        return Decimal("0.00"), Decimal("0.00")
    try:
        percent = Decimal(getattr(settings, "SQUARE_FEE_PERCENT", "0"))
    except Exception:
        percent = Decimal("0")
    # allow both 0.029 and 2.9 formats
    if percent >= 1:
        percent = percent / Decimal("100")

    fixed = getattr(settings, "SQUARE_FEE_FIXED", Decimal("0"))
    try:
        fixed = Decimal(fixed)
    except Exception:
        fixed = Decimal("0.00")

    denominator = Decimal("1.00") - percent
    if denominator <= 0:
        denominator = Decimal("1.00")
    gross = ((base + fixed) / denominator).quantize(PAYMENT_QUANT, rounding=ROUND_HALF_UP)
    fee = (gross - base).quantize(PAYMENT_QUANT, rounding=ROUND_HALF_UP)
    return gross, fee


def _charge_square(source_token: str, amount_cents: int, currency: str, *, note: str = "", buyer_email: str = ""):
    """
    Create a Square payment and return a dict with the key bits we need.
    """
    client = _square_client()
    payment = client.payments.create(
        source_id=source_token,
        idempotency_key=str(uuid.uuid4()),
        amount_money={"amount": amount_cents, "currency": currency},
        autocomplete=True,
        location_id=getattr(settings, "SQUARE_LOCATION_ID", ""),
        buyer_email_address=buyer_email or None,
        note=note[:500] if note else None,
    )
    if getattr(payment, "errors", None):
        errors = [getattr(err, "detail", None) or getattr(err, "category", None) for err in payment.errors]
        raise RuntimeError("; ".join([e for e in errors if e]) or "Payment was declined. Please try another card.")

    pay_obj = getattr(payment, "payment", None)
    if not pay_obj:
        raise RuntimeError("Payment was not created. Please try another card.")

    card_details = getattr(pay_obj, "card_details", None)
    card = getattr(card_details, "card", None) if card_details else None

    fee_money = None
    for fee in getattr(pay_obj, "processing_fee", None) or []:
        money = getattr(fee, "amount_money", None)
        fee_money = getattr(money, "amount", None)
        if fee_money is not None:
            break

    return {
        "id": getattr(pay_obj, "id", "") or "",
        "status": (getattr(pay_obj, "status", "") or "").lower(),
        "receipt_url": getattr(pay_obj, "receipt_url", "") or "",
        "card_brand": getattr(card, "card_brand", "") if card else "",
        "last_4": getattr(card, "last_4", "") if card else "",
        "fee_money": fee_money,
    }


def _record_payment_entry(
    order: Order,
    *,
    amount: Decimal,
    balance_due: Decimal,
    pay_mode: str,
    payment_resp: Dict,
    payment_fee: Decimal,
):
    """
    Persist a Payment row so it shows up in the admin Payments section.
    """
    try:
        method, _ = PaymentMethod.objects.get_or_create(name="Square")
    except Exception:
        logger.exception("Failed to get/create Square payment method")
        return

    currency = getattr(settings, "DEFAULT_CURRENCY_CODE", "CAD")
    fee_amount = Decimal("0.00")
    fee_cents = payment_resp.get("fee_money")
    if fee_cents is not None:
        try:
            fee_amount = (Decimal(str(fee_cents)) / Decimal("100")).quantize(PAYMENT_QUANT)
        except Exception:
            fee_amount = Decimal("0.00")
    elif payment_fee:
        try:
            fee_amount = Decimal(str(payment_fee)).quantize(PAYMENT_QUANT)
        except Exception:
            fee_amount = Decimal("0.00")

    try:
        Payment.objects.create(
            order=order,
            amount=Decimal(str(amount)),
            currency=currency,
            method=method,
            payment_mode=pay_mode,
            balance_due=Decimal(str(balance_due)) if balance_due is not None else Decimal("0.00"),
            processor="square",
            processor_payment_id=payment_resp.get("id", ""),
            receipt_url=payment_resp.get("receipt_url", ""),
            card_brand=payment_resp.get("card_brand", ""),
            card_last4=payment_resp.get("last_4", ""),
            fee_amount=fee_amount,
            created_at=getattr(order, "created_at", None) or None,
        )
    except Exception:
        logger.exception("Failed to record payment for order %s", getattr(order, "id", None))


# ────────────────────────── Публичные страницы ──────────────────────────

def _apply_filters(qs, form: ProductFilterForm):
    """
    Применяет фильтры категории/совместимости к QuerySet продуктов.
    """
    if not form.is_valid():
        return qs

    cat   = form.cleaned_data.get("category")
    make  = form.cleaned_data.get("make")
    model = form.cleaned_data.get("model")
    year  = form.cleaned_data.get("year")

    if cat:
        qs = qs.filter(category=cat)

    if model:
        qs = qs.filter(compatible_models=model)
    elif make:
        qs = qs.filter(compatible_models__make=make)

    if year:
        qs = qs.filter(
            compatible_models__year_from__lte=year
        ).filter(
            Q(compatible_models__year_to__isnull=True) | Q(compatible_models__year_to__gte=year)
        )

    return qs.distinct()


def _quote_notification_recipients() -> list[str]:
    """
    Resolve the notification list for custom fitment requests with sensible fallbacks.
    """
    recipients = getattr(settings, "STORE_QUOTE_RECIPIENTS", None)
    if isinstance(recipients, str):
        return [recipients]
    if recipients:
        return list(recipients)

    support_email = getattr(settings, "SUPPORT_EMAIL", None)
    if support_email:
        return [support_email]
    default = getattr(settings, "DEFAULT_FROM_EMAIL", None)
    if default:
        return [default]
    return ["support@badguymotors.com"]


def _notify_fitment_request(request_obj):
    """
    Send a concise email to the internal inbox so the sales team can follow up fast.
    """
    recipients = _quote_notification_recipients()
    if not recipients:
        return

    product_name = request_obj.product_name or "Custom build"
    context = base_email_context(
        {
            "product_name": product_name,
            "customer_name": request_obj.customer_name,
            "customer_email": request_obj.email,
            "customer_phone": request_obj.phone or "",
            "vehicle": request_obj.vehicle or "",
            "submodel": request_obj.submodel or "",
            "performance_goals": request_obj.performance_goals or "",
            "budget": request_obj.budget or "",
            "timeline": request_obj.timeline or "",
            "source_url": request_obj.source_url or "",
        }
    )
    template = render_email_template("fitment_request_internal", context)
    detail_lines = [
        f"Product: {request_obj.product_name or '—'}",
        f"Customer: {request_obj.customer_name}",
        f"Email: {request_obj.email}",
        f"Phone: {request_obj.phone or '—'}",
        f"Vehicle: {request_obj.vehicle or '—'}",
        f"Submodel: {request_obj.submodel or '—'}",
        f"Performance goals: {request_obj.performance_goals or '—'}",
        f"Budget: {request_obj.budget or '—'}",
        f"Timeline: {request_obj.timeline or '—'}",
    ]
    if request_obj.source_url:
        detail_lines.append(f"Source: {request_obj.source_url}")
    notice_lines = list(template.notice_lines)
    if request_obj.message:
        notice_lines.append(request_obj.message)
    elif not notice_lines:
        notice_lines.append("—")
    notice_text_lines = []
    if notice_lines:
        if template.notice_title:
            notice_text_lines = [f"{template.notice_title}: {line}" for line in notice_lines]
        else:
            notice_text_lines = notice_lines
    text_body = join_text_sections(
        [template.greeting],
        template.intro_lines,
        detail_lines,
        notice_text_lines,
        template.footer_lines,
    )

    sender = getattr(settings, "DEFAULT_FROM_EMAIL", None) or recipients[0]
    try:
        detail_rows = [
            ("Product", request_obj.product_name or "—"),
            ("Customer", request_obj.customer_name),
            ("Email", request_obj.email),
            ("Phone", request_obj.phone or "—"),
            ("Vehicle", request_obj.vehicle or "—"),
            ("Submodel", request_obj.submodel or "—"),
            ("Performance goals", request_obj.performance_goals or "—"),
            ("Budget", request_obj.budget or "—"),
            ("Timeline", request_obj.timeline or "—"),
        ]
        if request_obj.source_url:
            detail_rows.append(("Source", request_obj.source_url))
        notice_lines_html = list(template.notice_lines)
        if request_obj.message:
            notice_lines_html.append(request_obj.message)
        elif not notice_lines_html:
            notice_lines_html.append("—")
        html_body = build_email_html(
            title=template.title,
            preheader=template.preheader,
            greeting=template.greeting,
            intro_lines=template.intro_lines,
            detail_rows=detail_rows,
            notice_title=template.notice_title or None,
            notice_lines=notice_lines_html,
            footer_lines=template.footer_lines,
        )
        send_html_email(
            subject=template.subject,
            text_body=text_body,
            html_body=html_body,
            from_email=sender,
            recipient_list=recipients,
        )
    except Exception:
        logger.exception("Failed to notify about custom fitment request (id=%s)", request_obj.pk)


def _normalize_etransfer_email(raw: str | None) -> str:
    """
    Force legacy .com addresses to .ca to keep customer instructions current.
    """
    email = (raw or "").strip()
    if not email:
        return ""
    email = re.sub(r"(?i)@badguymotors\\.com$", "@badguymotors.ca", email)
    if email.lower() == "payments@badguymotors.ca":
        return "Payments@badguymotors.ca"
    return email


def _send_order_confirmation(
    order: Order,
    *,
    payment_method: str,
    pay_mode: str,
    charge_amount: Decimal,
    balance_due: Decimal,
    order_total_with_fees: Decimal,
    currency_symbol: str,
    currency_code: str,
    etransfer_email: str = "",
    etransfer_memo_hint: str = "",
    receipt_url: str = "",
):
    """
    Notify the customer via email once checkout succeeds.
    """
    recipient = (getattr(order, "email", "") or "").strip()
    if not recipient:
        return

    brand = email_brand_name()
    pay_mode_label = "Pay in full" if pay_mode != Order.PaymentMode.DEPOSIT else "50% deposit"
    amount_now = (charge_amount or Decimal("0.00")).quantize(PAYMENT_QUANT, rounding=ROUND_HALF_UP)
    balance_left = (balance_due or Decimal("0.00")).quantize(PAYMENT_QUANT, rounding=ROUND_HALF_UP)
    total_with_fees = (order_total_with_fees or Decimal("0.00")).quantize(PAYMENT_QUANT, rounding=ROUND_HALF_UP)

    payment_method_label = "Interac e-Transfer" if payment_method == "etransfer" else "Card (Square)"
    context = base_email_context(
        {
            "brand": brand,
            "customer_name": order.customer_name,
            "order_id": order.id,
            "order_total": f"{currency_symbol}{total_with_fees} {currency_code}",
            "payment_option": pay_mode_label,
            "payment_method": payment_method_label,
        }
    )
    template = render_email_template("order_confirmation", context)
    detail_lines = [
        f"Order #: {order.id}",
        f"Payment option: {pay_mode_label}",
        f"Order total (incl. GST/fees): {currency_symbol}{total_with_fees} {currency_code}",
    ]
    payment_lines = [f"Payment method: {payment_method_label}."]
    if payment_method == "etransfer":
        send_to = _normalize_etransfer_email(etransfer_email or getattr(settings, "ETRANSFER_EMAIL", ""))
        payment_lines.append(f"Amount to send now: {currency_symbol}{amount_now} {currency_code}.")
        if send_to:
            payment_lines.append(f"Send to: {send_to}.")
        if etransfer_memo_hint:
            payment_lines.append(f"Include this message: Order #{order.id} — {etransfer_memo_hint}")
        else:
            payment_lines.append(f"Include your Order #{order.id} in the transfer message.")
        if balance_left > 0:
            payment_lines.append(f"Balance after this payment: {currency_symbol}{balance_left} {currency_code}.")
    else:
        receipt = receipt_url or getattr(order, "payment_receipt_url", "")
        payment_lines.append(f"Charged now: {currency_symbol}{amount_now} {currency_code}.")
        if balance_left > 0:
            payment_lines.append(
                f"Balance remaining: {currency_symbol}{balance_left} {currency_code}. "
                "We'll invoice this before delivery."
            )
        if receipt:
            payment_lines.append(f"Square receipt: {receipt}")

    try:
        items = list(order.items.select_related("product", "option").all())
    except Exception:
        items = []
    if items:
        item_lines = ["Items:"]
        for it in items:
            name = getattr(it.product, "name", "Item")
            if getattr(it, "option", None):
                name = f"{name} ({it.option.name})"
            item_lines.append(f"- {name} × {it.qty}")
    else:
        item_lines = []

    text_body = join_text_sections(
        [template.greeting],
        template.intro_lines,
        detail_lines,
        payment_lines,
        item_lines,
        template.footer_lines,
    )

    sender = (
        getattr(settings, "DEFAULT_FROM_EMAIL", None)
        or getattr(settings, "SUPPORT_EMAIL", None)
        or _normalize_etransfer_email(getattr(settings, "ETRANSFER_EMAIL", None))
    )
    try:
        detail_rows = [
            ("Order #", order.id),
            ("Payment option", pay_mode_label),
            ("Payment method", payment_method_label),
            ("Order total (incl. GST/fees)", f"{currency_symbol}{total_with_fees} {currency_code}"),
        ]
        summary_rows = []
        notice_title = None
        notice_lines = []
        if payment_method == "etransfer":
            summary_rows.append(("Amount to send now", f"{currency_symbol}{amount_now} {currency_code}"))
            if balance_left > 0:
                summary_rows.append(("Balance after payment", f"{currency_symbol}{balance_left} {currency_code}"))
            notice_title = "Payment instructions"
            if send_to:
                notice_lines.append(f"Send to: {send_to}.")
            if etransfer_memo_hint:
                notice_lines.append(f"Include: Order #{order.id} - {etransfer_memo_hint}")
            else:
                notice_lines.append(f"Include: Order #{order.id}")
        else:
            summary_rows.append(("Charged now", f"{currency_symbol}{amount_now} {currency_code}"))
            if balance_left > 0:
                summary_rows.append(("Balance remaining", f"{currency_symbol}{balance_left} {currency_code}"))
            if receipt:
                notice_title = "Receipt"
                notice_lines.append(f"Square receipt: {receipt}")

        item_rows = []
        if items:
            for it in items:
                name = getattr(it.product, "name", "Item")
                if getattr(it, "option", None):
                    name = f"{name} ({it.option.name})"
                item_rows.append((name, f"x {it.qty}"))

        html_body = build_email_html(
            title=template.title,
            preheader=template.preheader,
            greeting=template.greeting,
            intro_lines=template.intro_lines,
            detail_rows=detail_rows,
            item_rows=item_rows,
            summary_rows=summary_rows,
            notice_title=template.notice_title or notice_title,
            notice_lines=[*template.notice_lines, *notice_lines],
            footer_lines=template.footer_lines,
            cta_label=template.cta_label,
            cta_url=getattr(settings, "COMPANY_WEBSITE", ""),
        )
        send_html_email(
            subject=template.subject,
            text_body=text_body,
            html_body=html_body,
            from_email=sender,
            recipient_list=[recipient],
        )
    except Exception:
        logger.exception("Failed to send order confirmation email for order %s", getattr(order, "pk", None))


def store_home(request):
    categories = Category.objects.filter(products__is_active=True).distinct()
    form = ProductFilterForm(request.GET or None)

    base_qs = (
        Product.objects.filter(is_active=True)
        .select_related("category")
        .prefetch_related("compatible_models", "options")
        .order_by("-created_at")
    )

    filtered_qs = _apply_filters(base_qs, form)

    # Блок "New arrivals" показываем только если фильтр НЕ применён
    filters_active = form.is_valid() and any(form.cleaned_data.values())
    new_arrivals = None if filters_active else base_qs[:8]

    # Секции по всем категориям
    sections = []
    for c in categories:
        cat_base = (
            Product.objects.filter(is_active=True, category=c)
            .select_related("category")
            .prefetch_related("options")
            .order_by("-created_at")
        )
        if cat_base.exists():
            sections.append((c, cat_base[:8]))

    context = {
        "categories": categories,
        "filter_form": form,
        "filters_active": filters_active,
        "products": filtered_qs[:24],  # общий грид результатов при активных фильтрах
        "new_arrivals": new_arrivals,
        "sections": sections,
        "store_copy": StorePageCopy.get_solo(),
    }
    return render(request, "store/store_home.html", context)


def category_list(request, slug):
    category = get_object_or_404(Category, slug=slug)
    form = ProductFilterForm(request.GET or None, initial={"category": category.id})

    base_qs = (
        Product.objects.filter(is_active=True, category=category)
        .select_related("category")
        .prefetch_related("compatible_models", "options")
        .order_by("-created_at")
    )
    products = _apply_filters(base_qs, form)

    context = {
        "category": category,
        "filter_form": form,
        "products": products,
        "filters_active": True,
        "store_copy": StorePageCopy.get_solo(),
    }
    return render(request, "store/category_list.html", context)


def product_detail(request, slug: str):
    product = get_object_or_404(
        Product.objects.select_related("category").prefetch_related("options", "compatible_models"),
        slug=slug,
        is_active=True
    )
    options = product.get_active_options()
    default_option = next((opt for opt in options if not getattr(opt, "is_separator", False)), None)
    related = (
        Product.objects.filter(is_active=True, category=product.category)
        .exclude(pk=product.pk)
        .order_by("-created_at")[:8]
    )
    go_along = product.get_companion_items(limit=3)
    quote_initial = {
        "product": product.pk,
        "source_url": request.build_absolute_uri(),
    }
    quote_form = CustomFitmentRequestForm(initial=quote_initial)

    if request.method == "POST" and request.POST.get("form_type") == "custom_fitment":
        form_data = request.POST.copy()
        form_data["product"] = product.pk
        form_data.setdefault("source_url", request.build_absolute_uri())
        quote_form = CustomFitmentRequestForm(form_data)
        if quote_form.is_valid():
            fitment_request = quote_form.save(commit=False)
            fitment_request._skip_telegram_notify = True  # avoid duplicate signal send
            fitment_request.save()
            _notify_fitment_request(fitment_request)
            transaction.on_commit(
                lambda: notification_services.notify_about_fitment_request(fitment_request.pk)
            )
            messages.success(
                request,
                "Thanks! Your build notes reached our team. Expect a reply within 1-2 business days.",
            )
            return redirect(product.get_absolute_url() + "#quote-request")
        messages.error(request, "Please correct the fields highlighted below.")

    return render(
        request,
        "store/product_detail.html",
        {
            "product": product,
            "related": related,
            "product_options": options,
            "default_option_id": default_option.id if default_option else None,
            "go_along": go_along,
            "quote_form": quote_form,
            "store_copy": StorePageCopy.get_solo(),
        },
    )


# ──────────────────────────── Корзина (сессии) ───────────────────────────

CART_KEY = "cart_items"  # backwards-compatible key

def _cart(session) -> Dict[str, list]:
    """
    Normalized cart representation: {"items": [{"product_id": int, "option_id": int|None, "qty": int}, ...]}
    """
    data = session.get(CART_KEY)
    if not data:
        data = {"items": []}
    elif isinstance(data, dict) and "items" not in data:
        # legacy shape {product_id: qty}
        items = []
        for pid, qty in data.items():
            try:
                product_id = int(pid)
                quantity = max(1, int(qty))
            except (TypeError, ValueError):
                continue
            items.append({"product_id": product_id, "option_id": None, "qty": quantity})
        data = {"items": items}
    elif isinstance(data, list):
        data = {"items": data}
    else:
        data.setdefault("items", [])

    normalized = []
    for entry in data.get("items", []):
        try:
            product_id = int(entry.get("product_id"))
            qty = max(1, int(entry.get("qty", 1)))
        except (TypeError, ValueError):
            continue
        option_id = entry.get("option_id")
        if option_id in ("", None):
            option_id = None
        else:
            try:
                option_id = int(option_id)
            except (TypeError, ValueError):
                option_id = None
        normalized.append({"product_id": product_id, "option_id": option_id, "qty": qty})

    data["items"] = normalized
    session[CART_KEY] = data
    return data


def _cart_add_item(session, *, product_id: int, qty: int, option_id: int | None = None):
    qty = max(1, int(qty))
    cart = _cart(session)
    for item in cart["items"]:
        if item["product_id"] == product_id and item["option_id"] == option_id:
            item["qty"] += qty
            break
    else:
        cart["items"].append(
            {
                "product_id": product_id,
                "option_id": option_id,
                "qty": qty,
            }
        )
    session.modified = True
    return cart


def _cart_positions(session, *, dealer_discount: int = 0):
    """
    Build hydrated cart positions for rendering/checkout.
    Returns (positions, dealer_total, retail_total).
    """
    cart = _cart(session)
    items = cart.get("items", [])
    if not items:
        return [], Decimal("0.00"), Decimal("0.00")

    quant = Decimal("0.01")
    product_ids = {it["product_id"] for it in items}
    option_ids = {it["option_id"] for it in items if it.get("option_id")}

    products = {
        p.id: p
        for p in Product.objects.filter(id__in=product_ids).select_related("category")
    }
    options = {
        opt.id: opt
        for opt in ProductOption.objects.filter(id__in=option_ids)
    } if option_ids else {}

    positions = []
    total = Decimal("0.00")
    retail_total = Decimal("0.00")
    dealer_discount = int(dealer_discount or 0)

    for entry in items:
        product = products.get(entry["product_id"])
        if not product:
            continue  # silently drop missing products
        option = options.get(entry["option_id"])
        if option and option.product_id != product.id:
            option = None
        if option and not getattr(option, "is_active", True):
            option = None
        qty = entry["qty"]
        unit = product.get_unit_price(option)
        retail_unit = unit
        retail_line = (retail_unit * qty).quantize(quant)

        discounted_unit = retail_unit
        if dealer_discount:
            discounted_unit = apply_dealer_discount(retail_unit, dealer_discount)
        line_total = (discounted_unit * qty).quantize(quant)

        total += line_total
        retail_total += retail_line
        positions.append(
            {
                "product": product,
                "option": option,
                "qty": qty,
                "unit_price": discounted_unit,
                "retail_unit_price": retail_unit,
                "line_total": line_total,
                "retail_line_total": retail_line,
                "savings": (retail_line - line_total).quantize(quant),
                "discount_percent": dealer_discount if dealer_discount else 0,
                "option_id": entry["option_id"],
            }
        )

    total_quantized = total.quantize(quant) if positions else Decimal("0.00")
    retail_quantized = retail_total.quantize(quant) if positions else Decimal("0.00")
    return positions, total_quantized, retail_quantized


def _ensure_session_key(request) -> str:
    if not request.session.session_key:
        request.session.save()
    return request.session.session_key or ""


def _build_abandoned_cart_items(positions: list[dict]) -> list[dict]:
    items = []
    for entry in positions:
        product = entry.get("product")
        if not product:
            continue
        option = entry.get("option")
        name = product.name
        if option:
            name = f"{name} ({option.name})"
        items.append(
            {
                "name": name,
                "qty": int(entry.get("qty") or 1),
                "line_total": str(entry.get("line_total") or "0.00"),
            }
        )
    return items


def _record_abandoned_cart(request, *, email: str, positions: list[dict], total: Decimal):
    if not email or not positions:
        return
    now = timezone.now()
    session_key = _ensure_session_key(request)
    items = _build_abandoned_cart_items(positions)
    if not items:
        return
    defaults = {
        "user": request.user if request.user.is_authenticated else None,
        "cart_items": items,
        "cart_total": total or Decimal("0.00"),
        "currency_code": getattr(settings, "DEFAULT_CURRENCY_CODE", ""),
        "currency_symbol": getattr(settings, "DEFAULT_CURRENCY_SYMBOL", ""),
        "last_activity_at": now,
    }
    existing = AbandonedCart.objects.filter(
        recovered_at__isnull=True,
        email__iexact=email,
        session_key=session_key,
    ).order_by("-updated_at").first()
    if existing:
        if defaults["user"] and existing.user_id is None:
            existing.user = defaults["user"]
        existing.cart_items = defaults["cart_items"]
        existing.cart_total = defaults["cart_total"]
        existing.currency_code = defaults["currency_code"]
        existing.currency_symbol = defaults["currency_symbol"]
        existing.last_activity_at = defaults["last_activity_at"]
        existing.save(
            update_fields=[
                "user",
                "cart_items",
                "cart_total",
                "currency_code",
                "currency_symbol",
                "last_activity_at",
                "updated_at",
            ]
        )
    else:
        AbandonedCart.objects.create(
            email=email,
            session_key=session_key,
            **defaults,
        )


def _mark_abandoned_cart_recovered(email: str):
    if not email:
        return
    AbandonedCart.objects.filter(
        recovered_at__isnull=True,
        email__iexact=email,
    ).update(recovered_at=timezone.now())

@require_POST
def cart_add(request, slug: str):
    product = get_object_or_404(Product, slug=slug, is_active=True)

    if product.contact_for_estimate:
        messages.error(request, "This build is quoted individually. Please contact us to get an estimate.")
        return redirect("store:store-product", slug=product.slug)

    try:
        qty = int(request.POST.get("qty", 1))
    except (TypeError, ValueError):
        qty = 1
    qty = max(1, qty)

    option = None
    option_id_raw = request.POST.get("option_id")
    if option_id_raw:
        try:
            option_id = int(option_id_raw)
        except (TypeError, ValueError):
            option_id = None
        if option_id:
            option = get_object_or_404(ProductOption, id=option_id, product=product)
            if not option.is_active:
                messages.error(request, "This option is currently unavailable.")
                return redirect("store:store-product", slug=product.slug)
            if getattr(option, "is_separator", False):
                messages.error(request, "Please select a valid option.")
                return redirect("store:store-product", slug=product.slug)
    elif product.has_active_options:
        messages.error(request, "Please select an option before adding the product to the cart.")
        return redirect("store:store-product", slug=product.slug)

    _cart_add_item(
        request.session,
        product_id=product.id,
        qty=qty,
        option_id=option.id if option else None,
    )

    if request.POST.get("buy_now") == "1":
        messages.success(request, f'"{product.name}" added. Redirecting to checkout.')
        return redirect("store:store-checkout")

    opt_suffix = f" ({option.name})" if option else ""
    messages.success(request, f'Added to cart: "{product.name}{opt_suffix}".')
    return redirect("store:store-product", slug=product.slug)


def cart_view(request):
    dealer_discount = get_dealer_discount_percent(request.user) if request.user.is_authenticated else 0
    positions, total, retail_total = _cart_positions(request.session, dealer_discount=dealer_discount)
    savings = (retail_total - total) if retail_total and total else Decimal("0.00")
    context = {
        "positions": positions,
        "total": total,
        "retail_total": retail_total,
        "cart_savings": savings,
        "dealer_discount_percent": dealer_discount,
        "store_copy": StorePageCopy.get_solo(),
    }
    return render(request, "store/cart.html", context)


@require_POST
def cart_remove(request, slug: str):
    product = get_object_or_404(Product, slug=slug)
    option_id_raw = request.POST.get("option_id")
    option_pk = None
    if option_id_raw not in (None, "", "null"):
        try:
            option_pk = int(option_id_raw)
        except (TypeError, ValueError):
            option_pk = None

    cart = _cart(request.session)
    before = len(cart["items"])
    cart["items"] = [
        item for item in cart["items"]
        if not (item["product_id"] == product.id and item.get("option_id") == option_pk)
    ]
    removed = before - len(cart["items"])
    if removed:
        request.session.modified = True
        option_label = ""
        if option_pk:
            opt = ProductOption.objects.filter(id=option_pk, product=product).first()
            if opt:
                option_label = f" ({opt.name})"
        messages.info(request, f'Removed from cart: "{product.name}{option_label}".')
    return redirect("store:store-cart")


# ─────────────────────────────── Вспомогалки ─────────────────────────────

def _model_field_names(model) -> set:
    names = set()
    for f in model._meta.get_fields():
        if getattr(f, "concrete", False) and not getattr(f, "many_to_many", False) and not getattr(f, "one_to_many", False):
            names.add(f.name)
    return names

def _first_present(model_fields: set, candidates: Iterable[str]):
    for name in candidates:
        if name in model_fields:
            return name
    return None


# ─────────────────────────────── Checkout ────────────────────────────────

def checkout(request):
    # собрать позиции заказа из корзины
    dealer_discount = get_dealer_discount_percent(request.user) if request.user.is_authenticated else 0
    positions, total, retail_total = _cart_positions(request.session, dealer_discount=dealer_discount)

    gst_rate = _get_decimal_setting("STORE_GST_RATE", "0.05")
    processing_rate = _get_decimal_setting("STORE_PROCESSING_FEE_RATE", "0.035")
    if gst_rate >= 1:
        gst_rate = gst_rate / Decimal("100")
    if processing_rate >= 1:
        processing_rate = processing_rate / Decimal("100")

    order_gst = (total * gst_rate).quantize(PAYMENT_QUANT, rounding=ROUND_HALF_UP) if total else Decimal("0.00")
    order_processing = (total * processing_rate).quantize(PAYMENT_QUANT, rounding=ROUND_HALF_UP) if total else Decimal("0.00")
    order_total_with_fees = (total + order_gst + order_processing).quantize(PAYMENT_QUANT, rounding=ROUND_HALF_UP)
    currency_code = getattr(settings, "DEFAULT_CURRENCY_CODE", "CAD")
    currency_symbol = getattr(settings, "DEFAULT_CURRENCY_SYMBOL", "$")
    etransfer_email = _normalize_etransfer_email(getattr(settings, "ETRANSFER_EMAIL", "")) or "Payments@badguymotors.ca"
    etransfer_memo_hint = getattr(settings, "ETRANSFER_MEMO_HINT", "")

    def payment_plan(label: str, portion: Decimal):
        base_portion = (total * portion).quantize(PAYMENT_QUANT, rounding=ROUND_HALF_UP) if total else Decimal("0.00")
        gst_portion = (base_portion * gst_rate).quantize(PAYMENT_QUANT, rounding=ROUND_HALF_UP) if base_portion else Decimal("0.00")
        processing_portion = (base_portion * processing_rate).quantize(PAYMENT_QUANT, rounding=ROUND_HALF_UP) if base_portion else Decimal("0.00")
        charge_amount = (base_portion + gst_portion + processing_portion).quantize(PAYMENT_QUANT, rounding=ROUND_HALF_UP)
        balance_due = (order_total_with_fees - charge_amount).quantize(PAYMENT_QUANT, rounding=ROUND_HALF_UP)
        if balance_due < 0:
            balance_due = Decimal("0.00")
        return {
            "label": label,
            "base": base_portion,
            "gst": gst_portion,
            "processing_fee": processing_portion,
            "charge": charge_amount,
            "balance_due": balance_due,
            "order_subtotal": total,
            "order_gst": order_gst,
            "order_processing": order_processing,
            "order_total_with_fees": order_total_with_fees,
        }

    payment_options = {
        "full": payment_plan("Pay 100% now", Decimal("1.0")),
        "deposit_50": payment_plan("Pay 50% deposit", Decimal("0.5")),
    }

    pay_mode = request.POST.get("pay_mode") or request.GET.get("pay_mode") or "full"
    if pay_mode not in payment_options:
        pay_mode = "full"
    payment_method = request.POST.get("payment_method") or request.GET.get("payment_method") or "card"
    if payment_method not in ("card", "etransfer"):
        payment_method = "card"

    reference_file = None
    if request.method == "POST" and not positions:
        messages.error(request, "The cart is empty.")
        return redirect("store:store-cart")

    form = {"delivery_method": "shipping", "pay_mode": pay_mode, "payment_method": payment_method}
    errors: Dict[str, str] = {}

    if request.method == "POST":
        def val(name, default=""):
            return (request.POST.get(name) or default).strip()

        def normalize_postal_code(raw: str) -> str:
            cleaned = "".join(ch for ch in (raw or "").upper() if ch.isalnum())
            if len(cleaned) >= 6:
                cleaned = cleaned[:6]
                return f"{cleaned[:3]} {cleaned[3:]}"
            return cleaned

        reference_file = request.FILES.get("reference_image")
        form = {
            "customer_name": val("customer_name"),
            "email": val("email"),
            "phone": val("phone"),
            "delivery_method": val("delivery_method", "shipping"),
            "address_line1": val("address_line1"),
            "address_line2": val("address_line2"),
            "city": val("city"),
            "region": val("region"),
            "postal_code": normalize_postal_code(val("postal_code")),
            "country": val("country") or "Canada",
            "pickup_notes": val("pickup_notes"),
            "comment": val("comment"),
            "agree": request.POST.get("agree") == "1",
            "pay_mode": pay_mode,
            "payment_method": payment_method,
        }
        payment_method = val("payment_method", payment_method) or "card"
        if payment_method not in ("card", "etransfer"):
            payment_method = "card"
        form["payment_method"] = payment_method

        # валидация
        if not form["customer_name"]:
            errors["customer_name"] = "Please provide your full name."
        if not form["phone"]:
            errors["phone"] = "Please provide a phone number."
        try:
            validate_email(form["email"])
        except ValidationError:
            errors["email"] = "Enter a valid email."

        is_pickup = form["delivery_method"] == "pickup"
        if not is_pickup:
            if not form["address_line1"]:
                errors["address_line1"] = "Street and house/building are required."
            if not form["city"]:
                errors["city"] = "City is required."
            if not form["region"]:
                errors["region"] = "State/region is required."
            if not form["postal_code"]:
                errors["postal_code"] = "Postal code is required."
        if not form["country"]:
            errors["country"] = "Country is required."

        if not form["agree"]:
            errors["agree"] = "You must agree to the terms."

        if reference_file:
            if reference_file.size > REFERENCE_IMAGE_MAX_BYTES:
                errors["reference_image"] = f"Image is too large. Limit: {REFERENCE_IMAGE_MAX_MB} MB."
            elif not (reference_file.content_type or "").lower().startswith("image/"):
                errors["reference_image"] = "Please upload an image file."
            else:
                try:
                    with Image.open(reference_file) as img:
                        img.verify()
                    reference_file.seek(0)
                except (UnidentifiedImageError, OSError):
                    errors["reference_image"] = "Unsupported image. Use JPG, PNG, or WEBP."

        if any(getattr(it["product"], "contact_for_estimate", False) for it in positions):
            errors["payment"] = "Items that require an estimate must be invoiced manually. Please remove them to pay online."

        selected_payment = payment_options[pay_mode]
        charge_amount = selected_payment["charge"]
        charge_processing_fee = selected_payment["processing_fee"]
        balance_due = selected_payment["balance_due"]
        square_token = request.POST.get("square_payment_token")
        is_etransfer = payment_method == "etransfer"

        if charge_amount <= 0:
            errors["payment"] = "Order total is zero — nothing to charge."
        if not errors and is_etransfer:
            if not getattr(settings, "ETRANSFER_EMAIL", ""):
                errors["payment"] = "Interac e-Transfer is not available right now. Please choose card or contact support."
        if not errors and not is_etransfer and not square_token:
            errors["payment"] = "Please enter your card details to complete payment."
        if not errors and not is_etransfer and not _square_ready():
            errors["payment"] = "Square credentials are not configured. Please contact support."

        cents = 0
        if not errors and not is_etransfer:
            try:
                cents = int((charge_amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            except Exception:
                cents = 0
            if cents <= 0:
                errors["payment"] = "Charge amount is invalid."

        payment_resp = {}
        if not errors and not is_etransfer:
            try:
                payment_resp = _charge_square(
                    square_token,
                    cents,
                    currency_code,
                    note=f"BGM store order ({pay_mode}) — {form['customer_name']}",
                    buyer_email=form["email"],
                )
            except Exception as exc:
                logger.exception("Square payment failed")
                errors["payment"] = str(exc) or "Card was declined. Please try again."

        if not errors:
            o_fields = _model_field_names(Order)

            order_kwargs = {}
            for key in ["customer_name", "email", "phone"]:
                if key in o_fields:
                    order_kwargs[key] = form[key]

            # Если в модели есть поле total — положим туда сумму (иначе total будет считаться @property)
            if "total" in o_fields:
                order_kwargs["total"] = total
            if "payment_mode" in o_fields:
                order_kwargs["payment_mode"] = pay_mode
            if "payment_amount" in o_fields:
                order_kwargs["payment_amount"] = Decimal("0.00") if is_etransfer else charge_amount
            if "payment_fee" in o_fields:
                order_kwargs["payment_fee"] = Decimal("0.00") if is_etransfer else charge_processing_fee
            if "payment_balance_due" in o_fields:
                order_kwargs["payment_balance_due"] = order_total_with_fees if is_etransfer else balance_due
            if "payment_processor" in o_fields:
                order_kwargs["payment_processor"] = "etransfer" if is_etransfer else "square"
            if "payment_id" in o_fields and not is_etransfer:
                order_kwargs["payment_id"] = payment_resp.get("id", "")
            if "payment_receipt_url" in o_fields and not is_etransfer:
                order_kwargs["payment_receipt_url"] = payment_resp.get("receipt_url", "")
            if "payment_card_brand" in o_fields and not is_etransfer:
                order_kwargs["payment_card_brand"] = payment_resp.get("card_brand", "")
            if "payment_last4" in o_fields and not is_etransfer:
                order_kwargs["payment_last4"] = payment_resp.get("last_4", "")
            if "payment_status" in o_fields:
                order_kwargs["payment_status"] = (
                    Order.PaymentStatus.UNPAID if is_etransfer else Order.PaymentStatus.PAID
                )

            # способ доставки
            name = _first_present(o_fields, ["delivery_method", "shipping_method"])
            if name:
                order_kwargs[name] = form["delivery_method"]

            # адресные поля (маппинг на разные варианты имен полей)
            mapping = {
                "address_line1": ["address_line1", "address1", "shipping_address1", "address", "shipping_address"],
                "address_line2": ["address_line2", "address2", "shipping_address2"],
                "city": ["city", "shipping_city"],
                "region": ["region", "state", "province", "shipping_region", "shipping_state", "shipping_province"],
                "postal_code": ["postal_code", "zip_code", "zip", "postcode"],
                "country": ["country", "shipping_country"],
            }
            for src, cands in mapping.items():
                dst = _first_present(o_fields, cands)
                if dst and form[src]:
                    order_kwargs[dst] = form[src]

            # комментарии/примечания
            comment_field = _first_present(
                o_fields,
                ["comment", "comments", "notes", "note", "customer_note", "customer_notes"]
            )
            if comment_field:
                extra_blocks = []
                if form["comment"]:
                    extra_blocks.append(form["comment"])
                if is_pickup and form["pickup_notes"]:
                    extra_blocks.append(f"[Pickup] {form['pickup_notes']}")
                if not is_pickup:
                    addr_pushed = all(
                        _first_present(o_fields, mapping[k])
                        for k in ["address_line1", "city", "region", "postal_code", "country"]
                    )
                    if not addr_pushed:
                        addr_text = ", ".join(
                            [form["address_line1"], form["address_line2"], form["city"],
                             form["region"], form["postal_code"], form["country"]]
                        ).strip(", ").replace("  ", " ")
                        extra_blocks.append(f"[Delivery] {addr_text}")
                if is_etransfer:
                    et_email = etransfer_email
                    memo_hint = etransfer_memo_hint
                    payment_note_parts = [
                        f"Customer chose Interac e-Transfer ({pay_mode}).",
                        f"Amount requested now: {charge_amount} {currency_code}.",
                    ]
                    if et_email:
                        payment_note_parts.append(f"Send to {et_email}.")
                    if memo_hint:
                        payment_note_parts.append(memo_hint)
                    extra_blocks.append("[Payment] " + " ".join(payment_note_parts))
                if extra_blocks:
                    order_kwargs[comment_field] = "\n".join(extra_blocks)

            # <<< ВАЖНО: Привязка к текущему пользователю, если он вошёл в систему >>>
            if request.user.is_authenticated:
                if "user" in o_fields:
                    order_kwargs["user"] = request.user
                # для совместимости также проставим created_by, если есть и пусто
                if "created_by" in o_fields:
                    order_kwargs.setdefault("created_by", request.user)

            if reference_file and "reference_image" in o_fields:
                order_kwargs["reference_image"] = reference_file

            with transaction.atomic():
                order = Order.objects.create(**order_kwargs)

                # ── создание позиций ──
                i_fields = _model_field_names(OrderItem)

                product_field = _first_present(i_fields, ["product", "item", "sku_product"])
                qty_field     = _first_present(i_fields, ["quantity", "qty", "count", "amount", "quantity_ordered"])
                price_field   = _first_present(i_fields, ["price_at_moment", "unit_price", "price", "unit", "price_snapshot"])
                line_field    = _first_present(i_fields, ["total", "line_total", "subtotal", "line_price", "price_total"])
                currency_field= _first_present(i_fields, ["currency", "currency_code"])

                option_field = _first_present(i_fields, ["option", "product_option"])

                for it in positions:
                    p = it["product"]
                    qty = int(it["qty"])
                    unit_source = it.get("unit_price")
                    if unit_source is None:
                        unit_source = p.get_unit_price()
                    unit = Decimal(str(unit_source))
                    line_total = Decimal(str(it.get("line_total", unit * qty)))

                    kwargs = {"order": order}
                    if product_field:
                        kwargs[product_field] = p
                    if qty_field:
                        kwargs[qty_field] = qty
                    if price_field:
                        kwargs[price_field] = unit  # важно: NOT NULL
                    if line_field:
                        kwargs[line_field] = line_total
                    if currency_field:
                        kwargs[currency_field] = getattr(p, "currency", settings.DEFAULT_CURRENCY_CODE)
                    if option_field and it.get("option"):
                        kwargs[option_field] = it["option"]

                    OrderItem.objects.create(**kwargs)

                if not is_etransfer:
                    _record_payment_entry(
                        order=order,
                        amount=charge_amount,
                        balance_due=balance_due,
                        pay_mode=pay_mode,
                        payment_resp=payment_resp,
                        payment_fee=charge_processing_fee,
                    )

                # очистить корзину
                request.session[CART_KEY] = {"items": []}
                request.session.modified = True

                transaction.on_commit(lambda: _send_order_confirmation(
                    order=order,
                    payment_method=payment_method,
                    pay_mode=pay_mode,
                    charge_amount=charge_amount,
                    balance_due=balance_due,
                    order_total_with_fees=order_total_with_fees,
                    currency_symbol=currency_symbol,
                    currency_code=currency_code,
                    etransfer_email=etransfer_email,
                    etransfer_memo_hint=etransfer_memo_hint,
                    receipt_url=payment_resp.get("receipt_url", ""),
                ))
                transaction.on_commit(lambda: _mark_abandoned_cart_recovered(form.get("email", "")))

            if is_etransfer:
                et_email = etransfer_email
                memo_hint = etransfer_memo_hint
                amount_str = f"{currency_symbol}{charge_amount.quantize(PAYMENT_QUANT)}"
                memo_suffix = (
                    f" with “Order #{order.id} — {memo_hint}”."
                    if memo_hint else
                    f" and include Order #{order.id} in the transfer message."
                )
                messages.success(
                    request,
                    f"Order created. Order #: {order.id}. Send {amount_str} via Interac e-Transfer to {et_email or 'our payments email'}{memo_suffix}",
                )
            else:
                messages.success(request, f"Order created successfully. Thank you! Order #: {order.id}")
            return redirect("store:store")

    selected_payment = payment_options.get(pay_mode, payment_options["full"])
    payment_options_payload = {
        key: {
            "label": data["label"],
            "base": float(data["base"]),
            "gst": float(data["gst"]),
            "processing_fee": float(data["processing_fee"]),
            "charge": float(data["charge"]),
            "balance_due": float(data["balance_due"]),
            "order_subtotal": float(data["order_subtotal"]),
            "order_gst": float(data["order_gst"]),
            "order_processing": float(data["order_processing"]),
            "order_total_with_fees": float(data["order_total_with_fees"]),
        } for key, data in payment_options.items()
    }

    if (
        request.method == "POST"
        and positions
        and form.get("email")
        and "email" not in errors
    ):
        _record_abandoned_cart(
            request,
            email=form.get("email", ""),
            positions=positions,
            total=total,
        )

    return render(
        request,
        "store/checkout.html",
        {
            "positions": positions,
            "total": total,
            "form": form,
            "errors": errors,
            "reference_image_limit_mb": REFERENCE_IMAGE_MAX_MB,
            "retail_total": retail_total,
            "cart_savings": (retail_total - total) if retail_total and total else Decimal("0.00"),
            "dealer_discount_percent": dealer_discount,
            "pay_mode": pay_mode,
            "payment_method": payment_method,
            "payment_options": payment_options,
            "order_gst": order_gst,
            "order_processing": order_processing,
            "order_total_with_fees": order_total_with_fees,
            "gst_rate_percent": (gst_rate * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            "processing_rate_percent": (processing_rate * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            "square_application_id": getattr(settings, "SQUARE_APPLICATION_ID", ""),
            "square_location_id": getattr(settings, "SQUARE_LOCATION_ID", ""),
            "square_env": getattr(settings, "SQUARE_ENVIRONMENT", "sandbox"),
            "square_ready": _square_ready(),
            "square_is_sandbox": str(getattr(settings, "SQUARE_ENVIRONMENT", "sandbox")).lower().startswith("sandbox"),
            "payment_options_json": json.dumps(payment_options_payload),
            "currency_symbol": currency_symbol,
            "currency_code": currency_code,
            "selected_payment": selected_payment,
            "etransfer_email": etransfer_email,
            "etransfer_memo_hint": etransfer_memo_hint,
            "store_copy": StorePageCopy.get_solo(),
        },
    )
