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

from core.models import AdminFavoritePage, AdminRecentPage, AdminReleaseSeen, AdminSidebarSeen
from core.services.admin_navigation import resolve_admin_page_meta
from core.services.admin_releases import get_admin_release_summary
from core.services.admin_notifications import (
    expand_notification_group_keys,
    get_disabled_notification_sections,
    make_notification_group_key,
    resolve_notification_group_keys,
)
register = template.Library()


@register.simple_tag
def sidebar_status(request) -> str:
    """
    Preserve Jazzmin's cookie toggle, but start collapsed by default.
    """
    if request and request.COOKIES.get("jazzy_menu") == "open":
        return ""
    return "sidebar-collapse"


def _visible_group_keys_for_user(user) -> Optional[set[str]]:
    """
    Role-based sidebar visibility.

    - If no roles are configured (or roles have no visible groups set), do not restrict.
    - If at least one role has visible groups set, restrict to the union of those groups.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return None
    if getattr(user, "is_superuser", False):
        return None
    try:
        links = user.userrole_set.select_related("role").all()
    except Exception:
        return None

    configured: list[set[str]] = []
    for link in links:
        role = getattr(link, "role", None)
        raw = getattr(role, "admin_sidebar_visible_groups", None) or []
        if isinstance(raw, str):
            raw = [raw]
        values = {val for val in raw if isinstance(val, str) and val}
        if values:
            configured.append(values)
    if not configured:
        return None
    allowed: set[str] = set()
    for values in configured:
        allowed |= values
    return expand_notification_group_keys(resolve_notification_group_keys(allowed))


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
    item.pop("url_kwargs", None)
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
        if model_label:
            alt_perms = [
                f"{meta['app']}.change_{meta['model_lower']}",
                f"{meta['app']}.add_{meta['model_lower']}",
                f"{meta['app']}.delete_{meta['model_lower']}",
            ]
            if not any(user.has_perm(perm) for perm in alt_perms):
                return None
        else:
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
            if group.get("notifications_enabled") is False:
                continue
            for item in group.get("items", []):
                model_label = item.get("model_label")
                if model_label:
                    labels.append(model_label)
    return labels


def _apply_notification_state(sidebar: List[Dict[str, Any]], user) -> None:
    model_labels = _collect_model_labels(sidebar)
    if not model_labels:
        for section in sidebar:
            section["has_unseen"] = False
            for group in section.get("groups", []):
                group["has_unseen"] = False
                for item in group.get("items", []):
                    item["has_unseen"] = False
                    item["last_action"] = None
        return

    app_labels = {label.split(".", 1)[0] for label in model_labels}
    model_names = {label.split(".", 1)[1] for label in model_labels}

    try:
        content_types = ContentType.objects.filter(app_label__in=app_labels, model__in=model_names)
        ct_id_to_label = {ct.id: f"{ct.app_label}.{ct.model}" for ct in content_types}
        ct_ids = list(ct_id_to_label.keys())

        latest_by_label: Dict[str, Any] = {}
        if ct_ids:
            include_self = getattr(settings, "ADMIN_SIDEBAR_INCLUDE_SELF_ACTIVITY", False)
            log_entries = LogEntry.objects.filter(content_type_id__in=ct_ids)
            if not include_self:
                log_entries = log_entries.exclude(user_id=getattr(user, "id", None))
            latest_rows = log_entries.values("content_type_id").annotate(last_action=Max("action_time"))
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

    # If a staff user has never opened a given admin model page, we still want "new work"
    # to show up in the sidebar/bell. Using `last_login` as the fallback baseline is too
    # aggressive because it updates on every login and can hide activity that happened
    # shortly before the user signed in. Instead, anchor unseen detection to the earliest
    # model page the user has actually visited (or their account creation time).
    if seen_map:
        baseline = min(seen_map.values())
    else:
        baseline = getattr(user, "date_joined", None) or timezone.now()
    if baseline and timezone.is_naive(baseline):
        baseline = timezone.make_aware(baseline, timezone.get_default_timezone())
    baseline = baseline or timezone.now()
    activity_cache: Dict[tuple[str, str], Any] = {}

    for section in sidebar:
        section_has_unseen = False
        for group in section.get("groups", []):
            group_has_unseen = False
            if group.get("notifications_enabled") is False:
                for item in group.get("items", []):
                    item["has_unseen"] = False
                    item["last_action"] = None
                group["has_unseen"] = False
                continue
            for item in group.get("items", []):
                model_label = item.get("model_label")
                has_unseen = False
                if model_label:
                    last_seen = seen_map.get(model_label, baseline)
                    activity_field = item.get("activity_field")
                    if activity_field:
                        cache_key = (model_label, activity_field)
                        if cache_key not in activity_cache:
                            try:
                                app_label, model_name = model_label.split(".", 1)
                                model = apps.get_model(app_label, model_name)
                                last_action = (
                                    model.objects.order_by(f"-{activity_field}")
                                    .values_list(activity_field, flat=True)
                                    .first()
                                )
                            except Exception:
                                last_action = None
                            activity_cache[cache_key] = last_action
                        else:
                            last_action = activity_cache[cache_key]
                    else:
                        last_action = latest_by_label.get(model_label)

                    if last_action:
                        if timezone.is_naive(last_action):
                            last_action = timezone.make_aware(
                                last_action,
                                timezone.get_default_timezone(),
                            )
                        has_unseen = last_action > last_seen
                    item["last_action"] = last_action
                else:
                    item["last_action"] = None
                item["has_unseen"] = has_unseen
                if has_unseen:
                    group_has_unseen = True
            group["has_unseen"] = group_has_unseen
            if group_has_unseen:
                group["is_open"] = True
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

    cached = getattr(request, "_admin_sidebar_cache", None)
    if cached is not None:
        return cached

    config = getattr(settings, "ADMIN_SIDEBAR_SECTIONS", None) or settings.JAZZMIN_SETTINGS.get(
        "custom_sidebar", []
    )
    disabled_sections = get_disabled_notification_sections(user)
    visible_group_keys = _visible_group_keys_for_user(user)
    view_name = getattr(getattr(request, "resolver_match", None), "view_name", "") or ""
    path = request.path

    sidebar: List[Dict[str, Any]] = []
    for section in config:
        section_link = _build_item(section, user, view_name, path)
        groups_payload = []
        section_label = section.get("label", "") or ""
        for group in section.get("groups", []):
            group_link = _build_item(group, user, view_name, path)
            group_label = group.get("label", "") or ""
            notification_key = make_notification_group_key(section_label, group_label)
            if (
                visible_group_keys is not None
                and not group.get("always_visible")
                and notification_key not in visible_group_keys
            ):
                continue

            items_payload = []
            for item in group.get("items", []):
                rendered = _build_item(item, user, view_name, path)
                if rendered:
                    items_payload.append(rendered)
            if items_payload:
                notifications_enabled = notification_key not in disabled_sections
                group_is_active = bool(group_link and group_link.get("is_active"))
                has_active_child = any(child["is_active"] for child in items_payload)
                groups_payload.append(
                    {
                        "label": group.get("label"),
                        "icon": (group_link or {}).get("icon", group.get("icon", section.get("icon", "fas fa-layer-group"))),
                        "badge": group.get("badge"),
                        "items": items_payload,
                        "is_open": has_active_child,
                        "has_active_child": has_active_child,
                        "is_active": group_is_active,
                        "url": (group_link or {}).get("url"),
                        "sidebar_expand": group.get("sidebar_expand", True),
                        "notification_key": notification_key,
                        "notifications_enabled": notifications_enabled,
                    }
                )
        if groups_payload:
            section_is_active = bool(section_link and section_link.get("is_active"))
            sidebar.append(
                {
                    "label": section.get("label"),
                    "icon": section.get("icon", "fas fa-layer-group"),
                    "groups": groups_payload,
                    "is_open": section_is_active or any(group["is_open"] for group in groups_payload),
                    "url": (section_link or {}).get("url"),
                    "is_active": section_is_active,
                    "show_header": section.get("show_header", True),
                }
            )
    _apply_notification_state(sidebar, user)
    request._admin_sidebar_cache = sidebar
    return sidebar


@register.simple_tag(takes_context=True)
def build_admin_notifications(context) -> Dict[str, Any]:
    request = context.get("request")
    if not request:
        return {"unseen_count": 0, "groups": []}

    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {"unseen_count": 0, "groups": []}

    sidebar = getattr(request, "_admin_sidebar_cache", None)
    if sidebar is None:
        sidebar = build_admin_sidebar(context)

    groups: List[Dict[str, Any]] = []
    unseen_count = 0
    for section in sidebar:
        for group in section.get("groups", []):
            items = [item for item in group.get("items", []) if item.get("has_unseen")]
            if not items:
                continue
            unseen_count += len(items)
            groups.append(
                {
                    "section_label": section.get("label"),
                    "group_label": group.get("label"),
                    "icon": group.get("icon"),
                    "items": items,
                }
            )

    return {"unseen_count": unseen_count, "groups": groups}


@register.simple_tag(takes_context=True)
def build_admin_whats_new(context) -> Dict[str, Any]:
    request = context.get("request")
    if not request:
        return {"unseen_count": 0, "releases": []}

    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {"unseen_count": 0, "releases": []}

    cached = getattr(request, "_admin_whats_new_cache", None)
    if cached is not None:
        return cached

    last_seen_at = None
    try:
        last_seen_at = (
            AdminReleaseSeen.objects.filter(user=user)
            .values_list("last_seen_at", flat=True)
            .first()
        )
    except (DatabaseError, OperationalError):
        last_seen_at = None

    summary = get_admin_release_summary(last_seen_at, limit=5)
    payload = {
        "unseen_count": summary["unseen_count"],
        "releases": summary["latest"],
    }
    request._admin_whats_new_cache = payload
    return payload


@register.simple_tag(takes_context=True)
def build_admin_shell(context) -> Dict[str, Any]:
    request = context.get("request")
    if not request:
        return {
            "current_page": None,
            "favorites": [],
            "recent_pages": [],
            "is_favorite": False,
        }

    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {
            "current_page": None,
            "favorites": [],
            "recent_pages": [],
            "is_favorite": False,
        }

    cached = getattr(request, "_admin_shell_cache", None)
    if cached is not None:
        return cached

    current_page = resolve_admin_page_meta(request, title=context.get("title") or "")
    try:
        favorites_qs = AdminFavoritePage.objects.filter(user=user).order_by("label", "created_at")[:8]
        recent_qs = AdminRecentPage.objects.filter(user=user).order_by("-last_visited_at")[:8]
        favorites = [
            {
                "label": item.label,
                "url": item.url,
                "icon": item.icon or "fas fa-star",
                "category": item.category,
                "note": item.note,
            }
            for item in favorites_qs
        ]
        recent_pages = [
            {
                "label": item.label,
                "url": item.url,
                "icon": item.icon or "fas fa-history",
                "category": item.category,
                "note": item.note,
            }
            for item in recent_qs
        ]
        is_favorite = False
        if current_page and current_page.get("url"):
            is_favorite = AdminFavoritePage.objects.filter(user=user, url=current_page["url"]).exists()
    except (DatabaseError, OperationalError):
        favorites = []
        recent_pages = []
        is_favorite = False

    payload = {
        "current_page": current_page,
        "favorites": favorites,
        "recent_pages": recent_pages,
        "is_favorite": is_favorite,
    }
    request._admin_shell_cache = payload
    return payload
