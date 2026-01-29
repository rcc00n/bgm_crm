from django import template

from core.models import AdminLoginBranding

register = template.Library()


@register.simple_tag
def get_admin_login_branding():
    try:
        return AdminLoginBranding.get_solo()
    except Exception:
        return None
