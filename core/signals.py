from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from core.models import StaffLoginEvent
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
