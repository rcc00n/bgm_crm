from decimal import Decimal

from django import template

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
