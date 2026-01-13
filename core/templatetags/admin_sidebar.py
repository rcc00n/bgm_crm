from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from django import template
from django.apps import apps
from django.conf import settings
from django.urls import NoReverseMatch, reverse
from django.utils.text import capfirst

register = template.Library()


def _as_list(value: Optional[Iterable[str]]) -> List[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    return list(value)


def _resolve_model_bits(model_label: str) -> Optional[Dict[str, Any]]:
    try:
        app_label, model_name = model_label.split(".")
        model = apps.get_model(app_label, model_name)
    except (ValueError, LookupError):
        return None
    return {
        "app": app_label,
        "model": model,
        "model_name": model_name,
        "model_lower": model._meta.model_name,
        "label": capfirst(model._meta.verbose_name_plural),
    }


def _resolve_icon(model_label: str, explicit_icon: Optional[str]) -> str:
    if explicit_icon:
        return explicit_icon

    icons = settings.JAZZMIN_SETTINGS.get("icons", {})
    default_icon = settings.JAZZMIN_SETTINGS.get("default_icon_children", "fas fa-circle")
    attempts = [model_label, model_label.lower()]

    if "." in model_label:
        app_label, model_name = model_label.split(".", 1)
        attempts.extend(
            [
                f"{app_label}.{model_name}",
                f"{app_label}.{model_name.lower()}",
                f"{app_label}.{model_name.capitalize()}",
            ]
        )

    for key in attempts:
        icon = icons.get(key)
        if icon:
            return icon

    return default_icon


def _build_item(
    item_def: Dict[str, Any],
    user,
    view_name: str,
    path: str,
) -> Optional[Dict[str, Any]]:
    model_label = item_def.get("model")
    item = dict(item_def)
    perms = _as_list(item.pop("permissions", None))
    url_name = item.pop("url", None)
    href = item.pop("href", None)
    active_patterns = _as_list(item.pop("active_patterns", None))

    if model_label:
        meta = _resolve_model_bits(model_label)
        if not meta:
            return None
        item.setdefault("label", meta["label"])
        item.setdefault("icon", _resolve_icon(model_label, item.get("icon")))
        perms = perms or [f"{meta['app']}.view_{meta['model_lower']}"]
        url_name = url_name or f"admin:{meta['app']}_{meta['model_lower']}_changelist"
        if not active_patterns:
            active_patterns = [f"admin:{meta['app']}_{meta['model_lower']}_"]

    if perms and not user.has_perms(perms):
        return None

    url = href or "#"
    if url_name:
        try:
            url = reverse(url_name)
        except NoReverseMatch:
            # fall back to provided href if reversing fails
            url = href or "#"

    is_active = False
    if view_name and active_patterns:
        is_active = any(view_name.startswith(pattern) for pattern in active_patterns)
    if not is_active and href and path:
        is_active = path.startswith(href)

    item.setdefault("icon", settings.JAZZMIN_SETTINGS.get("default_icon_children", "fas fa-circle"))
    item.update({"url": url, "is_active": is_active})
    return item


@register.simple_tag(takes_context=True)
def build_admin_sidebar(context) -> List[Dict[str, Any]]:
    request = context.get("request")
    if not request:
        return []

    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return []

    config = getattr(settings, "ADMIN_SIDEBAR_SECTIONS", None) or settings.JAZZMIN_SETTINGS.get(
        "custom_sidebar", []
    )
    view_name = getattr(getattr(request, "resolver_match", None), "view_name", "") or ""
    path = request.path

    sidebar: List[Dict[str, Any]] = []
    for section in config:
        groups_payload = []
        for group in section.get("groups", []):
            items_payload = []
            for item in group.get("items", []):
                rendered = _build_item(item, user, view_name, path)
                if rendered:
                    items_payload.append(rendered)
            if items_payload:
                groups_payload.append(
                    {
                        "label": group.get("label"),
                        "icon": group.get("icon", section.get("icon", "fas fa-layer-group")),
                        "badge": group.get("badge"),
                        "items": items_payload,
                        "is_open": any(child["is_active"] for child in items_payload),
                    }
                )
        if groups_payload:
            sidebar.append(
                {
                    "label": section.get("label"),
                    "icon": section.get("icon", "fas fa-layer-group"),
                    "groups": groups_payload,
                    "is_open": any(group["is_open"] for group in groups_payload),
                }
            )
    return sidebar
