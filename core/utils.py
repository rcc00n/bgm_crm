# core/utils.py
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


def apply_dealer_discount(base_price, percent: int) -> float:
    if not percent:
        return float(base_price)
    return float(base_price) * (100.0 - float(percent)) / 100.0
