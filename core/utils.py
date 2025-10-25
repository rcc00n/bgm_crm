# core/utils.py
from decimal import Decimal, InvalidOperation

from .models import UserRole

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
        return amount.quantize(Decimal("0.01"))
    factor = (Decimal("100") - pct) / Decimal("100")
    return (amount * factor).quantize(Decimal("0.01"))


def dealer_discount_savings(base_price, percent: int) -> Decimal:
    """
    Calculates how much money is saved versus the base price for the given discount percent.
    """
    amount = _to_decimal(base_price).quantize(Decimal("0.01"))
    discounted = apply_dealer_discount(base_price, percent)
    return (amount - discounted).quantize(Decimal("0.01"))
