import re
from django import template

register = template.Library()


@register.filter
def split_words(value):
    if value is None:
        return []
    text = str(value).strip()
    if not text:
        return []
    return [w for w in re.split(r"\s+", text) if w]


@register.filter
def split_bullets(value):
    if value is None:
        return []
    text = str(value).strip()
    if not text:
        return []
    parts = [p.strip() for p in re.split(r"\s*[•·|]\s*", text) if p.strip()]
    if len(parts) <= 1:
        return [text]
    return parts
