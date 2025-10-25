from decimal import Decimal

from django import template

from core.utils import apply_dealer_discount, dealer_discount_savings

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
