from decimal import Decimal

import html
import re

from django import template
from django.utils.html import strip_tags

from core.utils import apply_dealer_discount, dealer_discount_savings, format_currency

register = template.Library()


@register.filter
def dealer_price(value, percent):
    """
    Returns the discounted price for the provided percent. Falls back to the original value if no discount.
    """
    try:
        pct = int(percent or 0)
    except (TypeError, ValueError):
        pct = 0
    if pct <= 0:
        return value
    return apply_dealer_discount(value, pct)


@register.filter
def dealer_savings(value, percent):
    try:
        pct = int(percent or 0)
    except (TypeError, ValueError):
        pct = 0
    if pct <= 0:
        return Decimal("0.00")
    return dealer_discount_savings(value, pct)


@register.filter
def money(value, arg=None):
    """
    Formats a number using the default CAD currency.
    Pass “no_code” to hide the currency code and keep only the symbol.
    """
    include_code = True
    if arg:
        normalized = str(arg).strip().lower()
        if normalized in {"no", "nocode", "symbol", "short"}:
            include_code = False
    return format_currency(value, include_code=include_code)


@register.filter
def split_lines(value):
    if value is None:
        return []
    text = str(value)

    # Page copy often comes from CKEditor (HTML). Normalize common block/line break
    # markup into newline-delimited plain text before splitting.
    # This prevents users from seeing raw <p> tags or entities like &mdash;.
    text = re.sub(r"(?i)<\s*br\s*/?\s*>", "\n", text)
    text = re.sub(r"(?i)</\s*(p|li|div|h[1-6])\s*>", "\n", text)
    text = strip_tags(text)

    # Decode entities (twice to handle double-encoded input like &amp;mdash;).
    text = html.unescape(text)
    text = html.unescape(text)

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines
