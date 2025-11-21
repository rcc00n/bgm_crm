from __future__ import annotations

from typing import Dict, List, Optional

from core.models import FontPreset, PageFontSetting

# Default fallbacks in case admin configuration is missing.
DEFAULT_FONT_SLUGS = {
    "body": "diesel",
    "heading": "ford",
}


def _serialize_font(font: Optional[FontPreset]) -> Dict[str, str]:
    if not font:
        return {}
    return {
        "slug": font.slug,
        "name": font.name,
        "family": font.font_family,
        "stack": font.font_stack,
        "url": font.url,
        "format": font.format_hint,
        "mime_type": font.mime_type,
        "weight": font.font_weight,
        "style": font.font_style,
        "display": font.font_display,
        "preload": font.preload,
        "has_source": bool(font.url),
    }


def _pick_font(slug: Optional[str], font_map: Dict[str, FontPreset], fallback: Optional[str] = None) -> Optional[FontPreset]:
    for candidate in (slug, fallback):
        if candidate and candidate in font_map:
            return font_map[candidate]
    return next(iter(font_map.values()), None)


def build_page_font_context(page_slug: str) -> Dict[str, object]:
    """
    Returns a template-friendly font payload for a given page.
    Ensures we always return sane defaults even if the admin data is incomplete.
    """
    slug_map = {
        "body": DEFAULT_FONT_SLUGS.get("body"),
        "heading": DEFAULT_FONT_SLUGS.get("heading"),
    }

    try:
        page_fonts = PageFontSetting.objects.select_related("body_font", "heading_font", "ui_font").get(page=page_slug)
    except PageFontSetting.DoesNotExist:
        page_fonts = None

    if page_fonts:
        slug_map["body"] = page_fonts.body_font.slug
        slug_map["heading"] = page_fonts.heading_font.slug
        slug_map["ui"] = page_fonts.resolved_ui_font.slug
    else:
        slug_map["ui"] = slug_map["body"]

    wanted_slugs = {value for value in slug_map.values() if value} | set(DEFAULT_FONT_SLUGS.values())
    font_map = {
        font.slug: font
        for font in FontPreset.objects.filter(slug__in=wanted_slugs, is_active=True)
    }

    body_font = _pick_font(slug_map.get("body"), font_map, DEFAULT_FONT_SLUGS.get("body"))
    heading_font = _pick_font(slug_map.get("heading"), font_map, body_font.slug if body_font else None)
    ui_font = _pick_font(slug_map.get("ui"), font_map, body_font.slug if body_font else None)

    ordered_fonts: List[FontPreset] = []
    for font in (body_font, heading_font, ui_font):
        if font and font not in ordered_fonts:
            ordered_fonts.append(font)

    serialized_fonts = [_serialize_font(font) for font in ordered_fonts if font]

    return {
        "body": _serialize_font(body_font),
        "heading": _serialize_font(heading_font),
        "ui": _serialize_font(ui_font),
        "fonts": serialized_fonts,
        "preload_fonts": [font for font in serialized_fonts if font.get("preload") and font.get("url")],
    }
