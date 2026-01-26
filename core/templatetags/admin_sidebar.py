from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from django import template
from django.apps import apps
from django.conf import settings
from django.contrib.admin.models import LogEntry
from django.contrib.contenttypes.models import ContentType
from django.db.models import Max
from django.db.utils import DatabaseError, OperationalError
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.utils.text import capfirst

from core.models import AdminSidebarSeen
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
        item["model_label"] = f"{meta['app']}.{meta['model_lower']}"
        item["app_label"] = meta["app"]
        item["model_name"] = meta["model_lower"]

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


def _collect_model_labels(sidebar: List[Dict[str, Any]]) -> List[str]:
    labels: List[str] = []
    for section in sidebar:
        for group in section.get("groups", []):
            for item in group.get("items", []):
                model_label = item.get("model_label")
                if model_label:
                    labels.append(model_label)
    return labels


def _apply_notification_state(sidebar: List[Dict[str, Any]], user) -> None:
    model_labels = _collect_model_labels(sidebar)
    if not model_labels:
        return

    app_labels = {label.split(".", 1)[0] for label in model_labels}
    model_names = {label.split(".", 1)[1] for label in model_labels}

    try:
        content_types = ContentType.objects.filter(app_label__in=app_labels, model__in=model_names)
        ct_id_to_label = {ct.id: f"{ct.app_label}.{ct.model}" for ct in content_types}
        ct_ids = list(ct_id_to_label.keys())

        latest_by_label: Dict[str, Any] = {}
        if ct_ids:
            latest_rows = (
                LogEntry.objects.filter(content_type_id__in=ct_ids)
                .exclude(user_id=getattr(user, "id", None))
                .values("content_type_id")
                .annotate(last_action=Max("action_time"))
            )
            latest_by_label = {
                ct_id_to_label[row["content_type_id"]]: row["last_action"]
                for row in latest_rows
                if row.get("content_type_id") in ct_id_to_label
            }

        seen_rows = AdminSidebarSeen.objects.filter(
            user=user,
            app_label__in=app_labels,
            model_name__in=model_names,
        ).values("app_label", "model_name", "last_seen_at")
        seen_map = {
            f"{row['app_label']}.{row['model_name']}": row["last_seen_at"]
            for row in seen_rows
        }
    except (DatabaseError, OperationalError):
        return

    baseline = user.last_login or getattr(user, "date_joined", None) or timezone.now()

    for section in sidebar:
        section_has_unseen = False
        for group in section.get("groups", []):
            group_has_unseen = False
            for item in group.get("items", []):
                model_label = item.get("model_label")
                has_unseen = False
                if model_label:
                    last_action = latest_by_label.get(model_label)
                    if last_action:
                        last_seen = seen_map.get(model_label, baseline)
                        has_unseen = last_action > last_seen
                item["has_unseen"] = has_unseen
                if has_unseen:
                    group_has_unseen = True
            group["has_unseen"] = group_has_unseen
            if group_has_unseen:
                section_has_unseen = True
        section["has_unseen"] = section_has_unseen


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
    _apply_notification_state(sidebar, user)
    return sidebar
