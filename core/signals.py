from django.contrib.auth.signals import user_logged_in
from django.db.models.signals import post_save
from django.dispatch import receiver

from core.models import MasterProfile, StaffLoginEvent, UserRole
from core.services.ip_location import format_ip_location, get_client_ip


@receiver(user_logged_in)
def track_staff_login(sender, request, user, **kwargs):
    if not user or not getattr(user, "is_staff", False):
        return

    meta = getattr(request, "META", {}) or {}
    session = getattr(request, "session", None)
    StaffLoginEvent.objects.create(
        user=user,
        ip_address=get_client_ip(meta),
        ip_location=format_ip_location(meta),
        user_agent=(meta.get("HTTP_USER_AGENT") or "")[:1024],
        login_path=(getattr(request, "path", "") or "")[:255],
        session_key=(getattr(session, "session_key", "") or "")[:64],
    )


@receiver(post_save, sender=UserRole)
def ensure_master_profile_for_master_role(sender, instance, **kwargs):
    role = getattr(instance, "role", None)
    if not role or role.name != "Master" or not instance.user_id:
        return

    user = instance.user
    if not user.is_staff:
        user.is_staff = True
        user.save(update_fields=["is_staff"])

    MasterProfile.objects.get_or_create(user_id=instance.user_id)
