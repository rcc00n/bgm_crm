import html
import re

from django import template
from django.conf import settings
from django.templatetags.static import static
from django.utils.html import strip_tags

register = template.Library()

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


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


@register.filter
def meta_text(value: str) -> str:
    """
    Normalizes arbitrary text for safe use inside meta tag attributes.
    - strips HTML tags
    - collapses whitespace
    - unescapes entities (then Django will escape as needed in templates)
    """
    if value is None:
        return ""
    text = html.unescape(str(value))
    text = _HTML_TAG_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    return text


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


@register.filter
def meta_text(value) -> str:
    """
    Normalize user/content-managed HTML into a safe, single-line plain-text
    string suitable for meta tags (title/description/site_name).
    """
    if value is None:
        return ""
    text = str(value)

    # Treat common line-break / block end tags as whitespace separators so
    # adjacent words don't get concatenated when tags are stripped.
    text = re.sub(r"(?i)<\s*br\s*/?\s*>", " ", text)
    text = re.sub(r"(?i)</\s*(p|li|div|h[1-6])\s*>", " ", text)
    text = strip_tags(text)

    # Decode entities (twice to handle double-encoded input like &amp;amp;).
    text = html.unescape(text)
    text = html.unescape(text)

    # Collapse whitespace into a single line.
    text = re.sub(r"\s+", " ", text).strip()
    return text
