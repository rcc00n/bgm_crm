from django import template
from django.conf import settings
from django.templatetags.static import static

register = template.Library()


@register.filter
def absolute_url(value: str, origin: str = "") -> str:
    """
    Returns an absolute URL using the provided origin when the value is relative.
    """
    if not value:
        return ""
    text = str(value)
    if text.startswith(("http://", "https://")):
        return text
    origin = (origin or "").rstrip("/")
    if not origin:
        return text
    if text.startswith("/"):
        return f"{origin}{text}"
    return f"{origin}/{text}"


@register.simple_tag
def safe_static(path: str, fallback_path: str = "") -> str:
    """
    Resolve a static asset URL without failing hard on missing manifest entries.
    """
    candidate = (path or "").strip()
    if not candidate:
        return ""
    try:
        return static(candidate)
    except Exception:
        if fallback_path:
            fallback_candidate = fallback_path.strip()
            if fallback_candidate:
                try:
                    return static(fallback_candidate)
                except Exception:
                    candidate = fallback_candidate
        static_url = getattr(settings, "STATIC_URL", "/static/")
        return f"{static_url.rstrip('/')}/{candidate.lstrip('/')}"
