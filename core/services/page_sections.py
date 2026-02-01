from __future__ import annotations

from typing import Any, Dict, List

from django.contrib.contenttypes.models import ContentType

from core.models import PageSection


def _coerce_int(value: Any) -> int:
    try:
        return int(round(float(value)))
    except Exception:
        return 0


def _coerce_width(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        width = int(round(float(value)))
    except Exception:
        return None
    return width if width > 0 else None


def _extract_mode(data: Any) -> Dict[str, Any]:
    if not isinstance(data, dict):
        data = {}
    return {
        "x": _coerce_int(data.get("x", 0)),
        "y": _coerce_int(data.get("y", 0)),
        "w": _coerce_width(data.get("w")),
    }


def _normalize_layout_overrides(raw: Any) -> Dict[str, Dict[str, Any]]:
    if not isinstance(raw, dict):
        raw = {}
    if "desktop" in raw or "mobile" in raw:
        return {
            "desktop": _extract_mode(raw.get("desktop")),
            "mobile": _extract_mode(raw.get("mobile")),
        }
    return {
        "desktop": _extract_mode(raw),
        "mobile": {"x": 0, "y": 0, "w": None},
    }


def get_page_sections(instance, include_hidden: bool = False) -> List[PageSection]:
    if not instance or not getattr(instance, "pk", None):
        return []
    content_type = ContentType.objects.get_for_model(instance.__class__)
    qs = PageSection.objects.filter(content_type=content_type, object_id=instance.pk)
    if not include_hidden:
        qs = qs.filter(is_hidden=False)
    sections = list(qs.order_by("order", "id"))
    for section in sections:
        section.layout_vars = _normalize_layout_overrides(getattr(section, "layout_overrides", None))
    return sections
