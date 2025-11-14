# core/utils.py
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db.models import Q

from .models import CustomUserDisplay, UserRole

MONEY_QUANT = Decimal("0.01")

def assign_role(user, role):
    """
    Создаёт/обновляет связь User ↔ Role
    + автоматически включает доступ в админку для Admin/Master.
    """
    UserRole.objects.update_or_create(user=user, role=role)
    if role.name in {"Admin", "Master"}:
        if not user.is_staff:
            user.is_staff = True
            user.save(update_fields=["is_staff"])


def get_staff_queryset(active_only: bool = True):
    """
    Unified helper that returns every staff member (masters) regardless of how they were created.
    """
    staff_filter = Q(master_profile__isnull=False) | Q(userrole__role__name="Master")
    qs = CustomUserDisplay.objects.filter(staff_filter).distinct()
    if active_only:
        qs = qs.filter(is_active=True)
    return qs


def get_dealer_discount_percent(user) -> int:
    """
    Унифицированный доступ к скидке дилера.
    Используйте в расчёте final_price, в корзине, на чеках и т.п.
    """
    try:
        up = user.userprofile
    except Exception:
        return 0
    return getattr(up, "dealer_discount_percent", 0) or 0


def _to_decimal(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0.00")


def apply_dealer_discount(base_price, percent: int) -> Decimal:
    """
    Returns a quantized Decimal representing the discounted price.
    """
    amount = _to_decimal(base_price)
    pct = Decimal(str(percent or 0))
    if pct <= 0:
        return amount.quantize(MONEY_QUANT)
    factor = (Decimal("100") - pct) / Decimal("100")
    return (amount * factor).quantize(MONEY_QUANT)


def dealer_discount_savings(base_price, percent: int) -> Decimal:
    """
    Calculates how much money is saved versus the base price for the given discount percent.
    """
    amount = _to_decimal(base_price).quantize(MONEY_QUANT)
    discounted = apply_dealer_discount(base_price, percent)
    return (amount - discounted).quantize(MONEY_QUANT)


def format_currency(amount, include_code: bool = True) -> str:
    """
    Formats a numeric value using the default currency code/symbol defined in settings.
    include_code=False keeps only the symbol (useful for tight UI spots).
    """
    quantized = _to_decimal(amount).quantize(MONEY_QUANT)
    symbol = getattr(settings, "DEFAULT_CURRENCY_SYMBOL", "$") or ""
    code = getattr(settings, "DEFAULT_CURRENCY_CODE", "").upper()
    formatted = f"{symbol}{quantized:,.2f}".strip()
    if include_code and code:
        return f"{code} {formatted}".strip()
    return formatted
