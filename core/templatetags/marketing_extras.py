from django import template

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
