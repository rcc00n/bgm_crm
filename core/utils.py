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
