import logging
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.emails import build_email_html, send_html_email
from store.models import AbandonedCart

logger = logging.getLogger(__name__)


def _to_decimal(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0.00")


def _format_money(amount, symbol: str, code: str, *, include_code: bool = True) -> str:
    quantized = _to_decimal(amount).quantize(Decimal("0.01"))
    formatted = f"{symbol}{quantized:,.2f}".strip()
    if include_code and code:
        return f"{code} {formatted}".strip()
    return formatted


def _base_url() -> str:
    base = (getattr(settings, "COMPANY_WEBSITE", "") or "").strip()
    if not base:
        return ""
    if not base.startswith(("http://", "https://")):
        base = f"https://{base}"
    return base.rstrip("/")


def _resolve_url(setting_name: str, fallback_path: str) -> str:
    base = _base_url()
    raw = (getattr(settings, setting_name, "") or "").strip()
    if raw:
        if raw.startswith(("http://", "https://")):
            return raw
        if base:
            return f"{base}/{raw.lstrip('/')}"
        return raw
    if fallback_path.startswith(("http://", "https://")):
        return fallback_path
    if base:
        return f"{base}/{fallback_path.lstrip('/')}"
    return fallback_path


def _link_bundle() -> dict[str, str]:
    return {
        "cart": _resolve_url("ABANDONED_CART_CART_URL", "/store/cart/"),
        "checkout": _resolve_url("ABANDONED_CART_CHECKOUT_URL", "/store/checkout/"),
        "store": _resolve_url("ABANDONED_CART_STORE_URL", "/store/"),
    }


def _sender() -> str:
    return (
        getattr(settings, "DEFAULT_FROM_EMAIL", None)
        or getattr(settings, "SUPPORT_EMAIL", None)
        or ""
    )


def _item_rows(cart: AbandonedCart) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    symbol = cart.currency_symbol or getattr(settings, "DEFAULT_CURRENCY_SYMBOL", "$")
    code = (cart.currency_code or getattr(settings, "DEFAULT_CURRENCY_CODE", "")).upper()
    for item in cart.cart_items or []:
        name = str(item.get("name") or "Item").strip()
        qty = int(item.get("qty") or 1)
        line_total = item.get("line_total")
        total_label = _format_money(line_total, symbol, code, include_code=False)
        rows.append((f"{name} x{qty}", total_label))
    return rows


def _summary_rows(cart: AbandonedCart) -> list[tuple[str, str]]:
    symbol = cart.currency_symbol or getattr(settings, "DEFAULT_CURRENCY_SYMBOL", "$")
    code = (cart.currency_code or getattr(settings, "DEFAULT_CURRENCY_CODE", "")).upper()
    return [("Cart total", _format_money(cart.cart_total, symbol, code, include_code=True))]


def _send_email(recipient: str, *, subject: str, text_body: str, html_body: str) -> bool:
    sender = _sender()
    if not sender or not recipient:
        return False
    try:
        send_html_email(
            subject=subject,
            text_body=text_body,
            html_body=html_body,
            from_email=sender,
            recipient_list=[recipient],
        )
    except Exception:
        logger.exception("Failed to send abandoned cart email to %s", recipient)
        return False
    return True


def _build_email_1(cart: AbandonedCart) -> tuple[str, str, str]:
    brand = getattr(settings, "SITE_BRAND_NAME", "Bad Guy Motors")
    links = _link_bundle()
    subject = f"{brand} - your cart is waiting"
    text_lines = [
        "Hi there,",
        "You left a few items in your cart. We saved them for you.",
        f"Resume checkout: {links['checkout']}",
        f"View cart: {links['cart']}",
        "",
        "Questions? Reply to this email and we will help.",
    ]
    html_body = build_email_html(
        title="Your cart is waiting",
        preheader="You left a few items behind. Resume checkout anytime.",
        greeting="Hi there,",
        intro_lines=[
            "You left a few items in your cart. We saved them for you.",
        ],
        item_rows=_item_rows(cart),
        summary_rows=_summary_rows(cart),
        link_rows=[
            ("Resume checkout", links["checkout"]),
            ("View cart", links["cart"]),
            ("Shop store", links["store"]),
        ],
        cta_label="Resume checkout",
        cta_url=links["checkout"],
        footer_lines=["Questions? Reply to this email and we will help."],
    )
    return subject, "\n".join(text_lines), html_body


def _build_email_2(cart: AbandonedCart) -> tuple[str, str, str]:
    brand = getattr(settings, "SITE_BRAND_NAME", "Bad Guy Motors")
    links = _link_bundle()
    subject = f"{brand} - still want these items?"
    text_lines = [
        "Hi there,",
        "Your cart is still saved. If you want us to help with fitment or shipping, reply here.",
        f"Checkout: {links['checkout']}",
        f"Cart: {links['cart']}",
        "",
        "Questions? Reply to this email and we will help.",
    ]
    html_body = build_email_html(
        title="Your cart is still saved",
        preheader="Finish checkout whenever you are ready.",
        greeting="Hi there,",
        intro_lines=[
            "Your cart is still saved. If you want help with fitment or shipping, reply here.",
        ],
        item_rows=_item_rows(cart),
        summary_rows=_summary_rows(cart),
        link_rows=[
            ("Checkout", links["checkout"]),
            ("View cart", links["cart"]),
            ("Shop store", links["store"]),
        ],
        cta_label="Go to checkout",
        cta_url=links["checkout"],
        footer_lines=["Questions? Reply to this email and we will help."],
    )
    return subject, "\n".join(text_lines), html_body


def _build_email_3(cart: AbandonedCart) -> tuple[str, str, str]:
    brand = getattr(settings, "SITE_BRAND_NAME", "Bad Guy Motors")
    links = _link_bundle()
    subject = f"{brand} - last reminder for your cart"
    text_lines = [
        "Hi there,",
        "Just a final reminder in case you still want these items.",
        f"Checkout: {links['checkout']}",
        f"Cart: {links['cart']}",
        "",
        "Questions? Reply to this email and we will help.",
    ]
    html_body = build_email_html(
        title="Last reminder for your cart",
        preheader="Your cart is ready if you still want these items.",
        greeting="Hi there,",
        intro_lines=[
            "Just a final reminder in case you still want these items.",
        ],
        item_rows=_item_rows(cart),
        summary_rows=_summary_rows(cart),
        link_rows=[
            ("Checkout", links["checkout"]),
            ("View cart", links["cart"]),
            ("Shop store", links["store"]),
        ],
        cta_label="Checkout now",
        cta_url=links["checkout"],
        footer_lines=["Questions? Reply to this email and we will help."],
    )
    return subject, "\n".join(text_lines), html_body


class Command(BaseCommand):
    help = "Send abandoned cart follow-up emails."

    def handle(self, *args, **options):
        now = timezone.now()
        delay_1 = int(getattr(settings, "ABANDONED_CART_EMAIL_1_DELAY_HOURS", 2))
        delay_2 = int(getattr(settings, "ABANDONED_CART_EMAIL_2_DELAY_HOURS", 24))
        delay_3 = int(getattr(settings, "ABANDONED_CART_EMAIL_3_DELAY_HOURS", 72))

        cutoff_1 = now - timedelta(hours=delay_1)
        cutoff_2 = now - timedelta(hours=delay_2)
        cutoff_3 = now - timedelta(hours=delay_3)

        sent_1 = 0
        sent_2 = 0
        sent_3 = 0

        for cart in AbandonedCart.objects.filter(
            recovered_at__isnull=True,
            email_1_sent_at__isnull=True,
            last_activity_at__lte=cutoff_1,
        ).order_by("last_activity_at"):
            if not cart.cart_items or cart.cart_total <= 0:
                continue
            subject, text_body, html_body = _build_email_1(cart)
            if _send_email(cart.email, subject=subject, text_body=text_body, html_body=html_body):
                cart.email_1_sent_at = now
                cart.save(update_fields=["email_1_sent_at"])
                sent_1 += 1

        for cart in AbandonedCart.objects.filter(
            recovered_at__isnull=True,
            email_1_sent_at__isnull=False,
            email_2_sent_at__isnull=True,
            last_activity_at__lte=cutoff_2,
        ).order_by("last_activity_at"):
            if not cart.cart_items or cart.cart_total <= 0:
                continue
            subject, text_body, html_body = _build_email_2(cart)
            if _send_email(cart.email, subject=subject, text_body=text_body, html_body=html_body):
                cart.email_2_sent_at = now
                cart.save(update_fields=["email_2_sent_at"])
                sent_2 += 1

        for cart in AbandonedCart.objects.filter(
            recovered_at__isnull=True,
            email_2_sent_at__isnull=False,
            email_3_sent_at__isnull=True,
            last_activity_at__lte=cutoff_3,
        ).order_by("last_activity_at"):
            if not cart.cart_items or cart.cart_total <= 0:
                continue
            subject, text_body, html_body = _build_email_3(cart)
            if _send_email(cart.email, subject=subject, text_body=text_body, html_body=html_body):
                cart.email_3_sent_at = now
                cart.save(update_fields=["email_3_sent_at"])
                sent_3 += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Abandoned cart emails sent: {sent_1} (1st), {sent_2} (2nd), {sent_3} (3rd)."
            )
        )
