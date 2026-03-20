from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.apps import apps
from django.conf import settings
from django.contrib.auth.models import User
from django.db.models import Q
from django.urls import NoReverseMatch, reverse
from django.utils.text import capfirst

from core.models import ServiceLead, UserProfile
from store.models import Order, Product


@dataclass
class AdminTarget:
    label: str
    url: str
    icon: str
    category: str
    kind: str = "page"
    note: str = ""
    keywords: str = ""


def _as_list(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value if str(item).strip()]


def _user_can_access_model(user, model_label: str, *, add: bool = False) -> bool:
    try:
        app_label, model_name = model_label.split(".", 1)
        model = apps.get_model(app_label, model_name)
    except Exception:
        return False

    perm_model = model._meta.model_name
    perms = [f"{app_label}.add_{perm_model}"] if add else [
        f"{app_label}.view_{perm_model}",
        f"{app_label}.change_{perm_model}",
        f"{app_label}.add_{perm_model}",
        f"{app_label}.delete_{perm_model}",
    ]
    return any(user.has_perm(perm) for perm in perms)


def _resolve_item_url(item_def: dict[str, Any], *, add: bool = False) -> str | None:
    model_label = (item_def.get("model") or "").strip()
    url_name = (item_def.get("url_name") or item_def.get("url") or "").strip()
    href = (item_def.get("href") or "").strip()

    if model_label:
        try:
            app_label, model_name = model_label.split(".", 1)
            model = apps.get_model(app_label, model_name)
            action = "add" if add else "changelist"
            return reverse(f"admin:{app_label}_{model._meta.model_name}_{action}")
        except Exception:
            return None

    if url_name:
        try:
            return reverse(url_name)
        except NoReverseMatch:
            return href or None
    return href or None


def _resolve_model_icon(model_label: str, explicit_icon: str = "") -> str:
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


def _normalize_nav_item(item_def: dict[str, Any], *, category: str = "", group_label: str = "") -> dict[str, Any] | None:
    item = dict(item_def)
    model_label = (item.get("model") or "").strip()
    explicit_label = (item.get("label") or "").strip()
    note = str(item.get("note") or "").strip()
    icon = str(item.get("icon") or "").strip()
    category = str(category or "").strip()
    group_label = str(group_label or "").strip()

    if model_label:
        try:
            app_label, model_name = model_label.split(".", 1)
            model = apps.get_model(app_label, model_name)
        except Exception:
            return None
        label = explicit_label or str(capfirst(model._meta.verbose_name_plural))
        icon = _resolve_model_icon(model_label, icon)
        item.setdefault("url_name", f"admin:{app_label}_{model._meta.model_name}_changelist")
        if not note:
            note = group_label or category
    else:
        label = str(explicit_label or "").strip()
        if not label:
            return None

    url = _resolve_item_url(item)
    if not url:
        return None

    return {
        "label": str(label).strip(),
        "url": url,
        "icon": icon or "fas fa-circle",
        "category": category,
        "note": note,
        "model": model_label,
        "keywords": " ".join(filter(None, [label, category, group_label, note])).strip(),
    }


def get_admin_navigation_targets(user) -> list[AdminTarget]:
    targets: list[AdminTarget] = []
    seen_urls: set[str] = set()

    def add_target(payload: dict[str, Any], *, kind: str = "page"):
        url = (payload.get("url") or "").strip()
        if not url or url in seen_urls:
            return
        seen_urls.add(url)
        targets.append(
            AdminTarget(
                label=str(payload.get("label") or "").strip(),
                url=url,
                icon=str(payload.get("icon") or "fas fa-circle").strip() or "fas fa-circle",
                category=str(payload.get("category") or "Admin").strip(),
                kind=kind,
                note=str(payload.get("note") or "").strip(),
                keywords=str(payload.get("keywords") or "").strip(),
            )
        )

    static_targets = [
        {"label": "Dashboard", "url": reverse("admin:index"), "icon": "fas fa-th-large", "category": "Admin", "note": "Main admin home and health overview."},
        {"label": "What's New", "url": reverse("admin-whats-new"), "icon": "far fa-lightbulb", "category": "Admin", "note": "Release notes and recent admin updates."},
        {"label": "Staff Guide", "url": reverse("admin-staff-guide"), "icon": "fas fa-route", "category": "Admin", "note": "How staff should use the admin."},
        {"label": "Operations", "url": reverse("admin-workspace-operations"), "icon": "fas fa-tachometer-alt", "category": "Workspace", "note": "Scheduling, shop setup, payments, CRM references."},
        {"label": "Customers & Sales", "url": reverse("admin-workspace-customers-sales"), "icon": "fas fa-users-cog", "category": "Workspace", "note": "Clients, catalog, orders, fulfillment."},
        {"label": "Website & Marketing", "url": reverse("admin-workspace-website-marketing"), "icon": "fas fa-globe", "category": "Workspace", "note": "Content, brand system, assets, campaigns, Telegramm Bot."},
        {"label": "Reporting & Access", "url": reverse("admin-workspace-reporting-access"), "icon": "fas fa-chart-line", "category": "Workspace", "note": "Insights, QA, reporting."},
        {"label": "Reference & Setup", "url": reverse("admin-workspace-reference-setup"), "icon": "fas fa-archive", "category": "Workspace", "note": "Maintenance logs and moved-reference reminders."},
    ]
    for payload in static_targets:
        add_target(payload, kind="workspace" if payload["category"] == "Workspace" else "page")

    config = getattr(settings, "ADMIN_SIDEBAR_SECTIONS", None) or settings.JAZZMIN_SETTINGS.get("custom_sidebar", []) or []
    for section in config:
        section_label = (section.get("label") or "").strip() or "Admin"
        for group in section.get("groups", []):
            group_label = (group.get("label") or "").strip()
            if group.get("sidebar_expand") is False:
                group_payload = _normalize_nav_item(group, category=section_label, group_label=group_label)
                if group_payload:
                    add_target(group_payload, kind="workspace")

            for item in group.get("items", []):
                payload = _normalize_nav_item(item, category=section_label, group_label=group_label)
                if payload:
                    add_target(payload, kind="model" if payload.get("model") else "page")

    return targets


def resolve_admin_page_meta(request, *, title: str = "") -> dict[str, str]:
    path = (getattr(request, "path", "") or "").strip()
    full_path = (request.get_full_path() or path or "").strip()
    title = (title or "").strip()
    user = getattr(request, "user", None)

    for target in get_admin_navigation_targets(user):
        if target.url == full_path or target.url == path:
            return {
                "url": full_path or target.url,
                "label": title or target.label,
                "icon": target.icon,
                "category": target.category,
                "note": target.note,
            }

    resolver = getattr(request, "resolver_match", None)
    view_name = getattr(resolver, "view_name", "") or ""
    if view_name.startswith("admin:"):
        slug = view_name.split(":", 1)[1]
        if "_" in slug:
            app_label, rest = slug.split("_", 1)
            for suffix in ("changelist", "add", "change", "delete", "history"):
                token = f"_{suffix}"
                if rest.endswith(token):
                    model_name = rest[: -len(token)]
                    try:
                        model = apps.get_model(app_label, model_name)
                        return {
                            "url": full_path or path,
                            "label": title or capfirst(model._meta.verbose_name_plural),
                            "icon": _resolve_model_icon(f"{app_label}.{model_name}"),
                            "category": capfirst(app_label.replace("_", " ")),
                            "note": "",
                        }
                    except Exception:
                        break

    return {
        "url": full_path or path or "#",
        "label": title or "Admin page",
        "icon": "fas fa-star",
        "category": "Admin",
        "note": "",
    }


def search_admin_navigation(user, query: str, *, limit: int = 8) -> list[dict[str, Any]]:
    q = (query or "").strip().lower()
    if not q:
        return []
    scored: list[tuple[int, AdminTarget]] = []
    for target in get_admin_navigation_targets(user):
        haystack = " ".join([target.label, target.category, target.note, target.keywords]).lower()
        if q not in haystack:
            continue
        score = 0
        if target.label.lower().startswith(q):
            score += 6
        if q in target.label.lower():
            score += 4
        if q in target.category.lower():
            score += 2
        scored.append((score, target))
    scored.sort(key=lambda item: (-item[0], item[1].label))
    return [
        {
            "label": target.label,
            "url": target.url,
            "icon": target.icon,
            "category": target.category,
            "note": target.note,
            "kind": target.kind,
        }
        for _, target in scored[: max(limit, 0)]
    ]


def search_admin_records(user, query: str, *, per_group: int = 5) -> list[dict[str, Any]]:
    q = (query or "").strip()
    if not q:
        return []

    results: list[dict[str, Any]] = []

    if _user_can_access_model(user, "store.Product"):
        products = Product.objects.filter(
            Q(name__icontains=q) | Q(sku__icontains=q)
        ).select_related("category")[:per_group]
        items = [
            {
                "label": product.name,
                "url": reverse("admin:store_product_change", args=[product.pk]),
                "icon": _resolve_model_icon("store.Product"),
                "note": f"{product.sku} · {getattr(product.category, 'name', 'No category')}",
            }
            for product in products
        ]
        if items:
            results.append({"title": "Products", "kind": "records", "items": items})

    if _user_can_access_model(user, "store.Order"):
        order_query = Q(customer_name__icontains=q) | Q(email__icontains=q) | Q(phone__icontains=q)
        if q.isdigit():
            order_query |= Q(pk=int(q))
        orders = Order.objects.filter(order_query)[:per_group]
        items = [
            {
                "label": f"Order #{order.pk}",
                "url": reverse("admin:store_order_change", args=[order.pk]),
                "icon": _resolve_model_icon("store.Order"),
                "note": f"{order.customer_name} · {order.email}",
            }
            for order in orders
        ]
        if items:
            results.append({"title": "Orders", "kind": "records", "items": items})

    if user.has_perm("auth.view_user") or _user_can_access_model(user, "core.UserProfile"):
        user_query = (
            Q(username__icontains=q)
            | Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(email__icontains=q)
            | Q(userprofile__phone__icontains=q)
        )
        users = User.objects.filter(user_query).select_related("userprofile")[:per_group]
        items = []
        for account in users:
            label = account.get_full_name() or account.username
            note_bits = [account.email]
            profile = getattr(account, "userprofile", None)
            if profile and profile.phone:
                note_bits.append(profile.phone)
            if profile:
                url = reverse("admin:core_userprofile_change", args=[profile.pk])
            else:
                url = reverse("admin:auth_user_change", args=[account.pk])
            items.append(
                {
                    "label": label,
                    "url": url,
                    "icon": "fas fa-user",
                    "note": " · ".join(bit for bit in note_bits if bit),
                }
            )
        if items:
            results.append({"title": "Clients & Users", "kind": "records", "items": items})

    if _user_can_access_model(user, "core.ServiceLead"):
        leads = ServiceLead.objects.filter(
            Q(full_name__icontains=q)
            | Q(email__icontains=q)
            | Q(phone__icontains=q)
            | Q(vehicle__icontains=q)
            | Q(service_needed__icontains=q)
        )[:per_group]
        items = [
            {
                "label": lead.full_name,
                "url": reverse("admin:core_servicelead_change", args=[lead.pk]),
                "icon": _resolve_model_icon("core.ServiceLead"),
                "note": " · ".join(bit for bit in [lead.service_needed, lead.phone or lead.email] if bit),
            }
            for lead in leads
        ]
        if items:
            results.append({"title": "Service Leads", "kind": "records", "items": items})

    return results
