from __future__ import annotations

from django import template

from core.utils_durations import format_hms_ms, format_hms_seconds

register = template.Library()


@register.filter(name="hms")
def hms(value):
    return format_hms_seconds(value)


@register.filter(name="hms_ms")
def hms_ms(value):
    return format_hms_ms(value)

