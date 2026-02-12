import html
import re

from django import template
from django.utils.html import strip_tags

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


@register.filter
def meta_text(value) -> str:
    """
    Converts rich text or encoded copy into one clean plain-text line for meta tags.
    """
    if value is None:
        return ""
    text = str(value)
    # firstof can hand us already-escaped text (e.g. &lt;p&gt;...).
    text = html.unescape(text)
    text = html.unescape(text)
    text = re.sub(r"(?i)<\s*br\s*/?\s*>", " ", text)
    text = re.sub(r"(?i)</\s*(p|li|div|h[1-6])\s*>", " ", text)
    text = strip_tags(text)
    # Decode twice so double-encoded entities (e.g. &amp;mdash;) resolve cleanly.
    text = html.unescape(text)
    text = html.unescape(text)
    return " ".join(text.split())
