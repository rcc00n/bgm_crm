from __future__ import annotations

from datetime import datetime
from typing import Any

from django.apps import apps
from django.utils import timezone
from django.urls import NoReverseMatch, reverse


# Keep newest entries first. Every admin-facing UX/workflow change should add a
# release entry here and follow docs/admin_whats_new_agent_instructions.md.
ADMIN_RELEASES: list[dict[str, Any]] = [
    {
        "key": "2026-03-20-telegramm-bot-moved-into-email-hub",
        "published_at": "2026-03-20T20:05:00-06:00",
        "title": "Telegramm Bot moved into the Email & Campaigns hub",
        "summary": "The old Automation area now lives at the bottom of the Email & Campaigns workspace and is labeled Telegramm Bot.",
        "highlights": [
            "Telegram contacts, bot settings, reminders, and delivery logs no longer live under Operations.",
            "Email & Campaigns now ends with a dedicated Telegramm Bot section so messaging tools stay together.",
            "Old Automation workspace links now forward into Email & Campaigns.",
        ],
        "areas": ["Navigation", "Workspaces", "Admin UX"],
        "links": [
            {
                "label": "Email & Campaigns",
                "url_name": "admin-workspace-hub",
                "url_kwargs": {"slug": "email-campaigns"},
                "note": "Open the updated messaging workspace.",
            },
            {
                "label": "Website & Marketing",
                "url_name": "admin-workspace-website-marketing",
                "note": "See the messaging lane inside the wider marketing workspace.",
            },
        ],
    },
    {
        "key": "2026-03-20-workspace-anchor-highlight-feedback",
        "published_at": "2026-03-20T19:45:00-06:00",
        "title": "Workspace section numbers now react while you scroll",
        "summary": "The numbered section chips inside workspace hubs now change color as you move between anchors, making long hubs feel more interactive.",
        "highlights": [
            "Jump-to-section chips now highlight the section you are currently reading instead of staying visually static.",
            "Switching to another anchor updates the numbered chip color immediately, so it is easier to track where you are inside a hub.",
            "The active workspace card gets a matching accent so the jump bar and the content stay visually linked.",
        ],
        "areas": ["Admin UX", "Workspaces", "Navigation"],
        "links": [
            {
                "label": "Scheduling & Shop",
                "url_name": "admin-workspace-hub",
                "url_kwargs": {"slug": "scheduling-shop"},
                "note": "Example hub with multiple anchor sections.",
            },
            {
                "label": "Catalog, Merch & Fulfillment",
                "url_name": "admin-workspace-hub",
                "url_kwargs": {"slug": "catalog-merch"},
                "note": "Another long hub using the interactive jump bar.",
            },
        ],
    },
    {
        "key": "2026-03-20-scheduling-shop-absorbs-payments-and-crm",
        "published_at": "2026-03-20T19:20:00-06:00",
        "title": "Scheduling & Shop now includes payments, promotions, CRM, and vehicles",
        "summary": "The Scheduling & Shop workspace now absorbs the old Payments & Promotions and CRM & Vehicles hubs so more admin setup work starts from one place.",
        "highlights": [
            "Payments, promo codes, discounts, lead sources, users, roles, and vehicle tables now live inside Scheduling & Shop.",
            "The merged workspace now has dedicated sections for payments and promotions, booking rules, and CRM or vehicle references.",
            "Old Payments & Promotions and CRM & Vehicles workspace URLs now forward into Scheduling & Shop.",
        ],
        "areas": ["Navigation", "Workspaces", "Admin UX"],
        "links": [
            {
                "label": "Scheduling & Shop",
                "url_name": "admin-workspace-hub",
                "url_kwargs": {"slug": "scheduling-shop"},
                "note": "Open the merged operating workspace.",
            },
            {
                "label": "Staff Guide",
                "url_name": "admin-staff-guide",
                "note": "See the updated staff instructions for the merged setup.",
            },
            {
                "label": "Reference & Setup",
                "url_name": "admin-workspace-reference-setup",
                "note": "Maintenance lane with reminder links into Scheduling & Shop.",
            },
        ],
    },
    {
        "key": "2026-03-20-whats-new-section-links",
        "published_at": "2026-03-20T18:55:00-06:00",
        "title": "What's New entries now link straight to updated sections",
        "summary": "Each admin journal entry now includes direct links to the workspaces or pages that changed.",
        "highlights": [
            "Release notes are now actionable: you can jump from each entry straight into the updated admin sections.",
            "Existing release entries were backfilled with direct links so older admin updates are easier to revisit.",
        ],
        "areas": ["Release Notes", "Navigation", "Admin UX"],
        "links": [
            {
                "label": "What's New",
                "url_name": "admin-whats-new",
                "note": "Open the full admin journal.",
            },
            {
                "label": "Catalog, Merch & Fulfillment",
                "url_name": "admin-workspace-hub",
                "url_kwargs": {"slug": "catalog-merch"},
                "note": "Example linked workspace entry.",
            },
        ],
    },
    {
        "key": "2026-03-20-catalog-workspace-icon-restored",
        "published_at": "2026-03-20T18:25:00-06:00",
        "title": "Catalog workspace icon restored in the sidebar",
        "summary": "The Catalog, Merch & Fulfillment workspace now shows its sidebar icon correctly again.",
        "highlights": [
            "The merged commerce workspace now has a visible icon in the left sidebar instead of a blank slot.",
            "No pages moved and no workflow changed; this restores the visual cue for the existing hub.",
        ],
        "areas": ["Navigation", "Admin UX"],
        "links": [
            {
                "label": "Catalog, Merch & Fulfillment",
                "url_name": "admin-workspace-hub",
                "url_kwargs": {"slug": "catalog-merch"},
                "note": "Open the merged commerce workspace.",
            },
        ],
    },
    {
        "key": "2026-03-20-admin-hub-consolidation",
        "published_at": "2026-03-20T18:10:00-06:00",
        "title": "Admin hubs consolidated into fewer workspaces",
        "summary": "Content and brand pages, store and fulfillment pages, booking references, and access controls were regrouped into fewer admin workspaces.",
        "highlights": [
            "Page Content and Brand & Assets now live together in one Content, Brand & Assets workspace with separate sections for editors, brand controls, and media.",
            "Catalog & Merch and Orders & Fulfillment now share one commerce workspace so products, orders, fitment, and fulfillment tools stay one click apart.",
            "Booking & Payments now lives inside Scheduling & Shop, and People & Access now lives inside CRM & Vehicles.",
            "Old workspace URLs still forward into the new destinations so bookmarks and saved habits keep working.",
        ],
        "areas": ["Navigation", "Workspaces", "Admin UX"],
        "links": [
            {
                "label": "Content, Brand & Assets",
                "url_name": "admin-workspace-hub",
                "url_kwargs": {"slug": "page-content"},
                "note": "Page editors, brand controls, and media.",
            },
            {
                "label": "Catalog, Merch & Fulfillment",
                "url_name": "admin-workspace-hub",
                "url_kwargs": {"slug": "catalog-merch"},
                "note": "Products, orders, and store rules.",
            },
            {
                "label": "Scheduling & Shop",
                "url_name": "admin-workspace-hub",
                "url_kwargs": {"slug": "scheduling-shop"},
                "note": "Daily scheduling plus booking/payment references.",
            },
            {
                "label": "CRM & Vehicles",
                "url_name": "admin-workspace-hub",
                "url_kwargs": {"slug": "crm-vehicles"},
                "note": "CRM references, access, and vehicle tables.",
            },
        ],
    },
    {
        "key": "2026-03-20-product-editor-redesign",
        "published_at": "2026-03-20T15:15:00-06:00",
        "title": "Product editor redesigned for faster catalog work",
        "summary": "The product change form now uses a custom editor layout with clearer sections, better save flow, and cleaner option/image management.",
        "highlights": [
            "Product identity, pricing, storefront content, compatibility, and specs are now grouped into clearer workspace cards instead of one long uneven form.",
            "The product page now surfaces a quick product summary, stock and margin context, and a cleaner action rail while you edit.",
            "Options and gallery rows still work as before, but they now sit inside clearer inline sections that are easier to scan and maintain.",
        ],
        "areas": ["Products", "Catalog", "Admin UX"],
        "links": [
            {
                "label": "Products",
                "model": "store.Product",
                "note": "Open the product workspace.",
            },
        ],
    },
    {
        "key": "2026-03-19-admin-search-favorites-and-workspace-navigation",
        "published_at": "2026-03-19T23:40:00-06:00",
        "title": "Global admin search, favorites, and smarter workspace navigation",
        "summary": "The admin header now includes search, favorites, recent pages, and richer workspace pages with quick actions and attention states.",
        "highlights": [
            "You can search pages, products, orders, clients, and leads from one header search bar, with live suggestions and keyboard focus shortcuts.",
            "Any admin page can be saved to favorites, and recently visited pages are now available from the top bar so staff can jump back into active work faster.",
            "Workspace pages now surface quick actions, cross-links to related workspaces, needs-attention signals, stronger empty states, and clearer support-page layouts.",
        ],
        "areas": ["Navigation", "Search", "Favorites", "Workspaces"],
        "links": [
            {
                "label": "Dashboard",
                "url_name": "admin:index",
                "note": "Search, favorites, and recent pages live in the admin header.",
            },
            {
                "label": "What's New",
                "url_name": "admin-whats-new",
                "note": "Release center in the header menu.",
            },
            {
                "label": "Operations",
                "url_name": "admin-workspace-operations",
                "note": "Example workspace with richer quick actions.",
            },
        ],
    },
    {
        "key": "2026-03-19-whats-new-and-focused-sidebar",
        "published_at": "2026-03-19T16:30:00-06:00",
        "title": "What's New center and cleaner sidebar",
        "summary": "Low-priority sidebar links now live inside workspace hubs, and the admin top bar has a per-user What's New center.",
        "highlights": [
            "The sidebar now keeps only the primary pages for each area so daily work is easier to scan.",
            "Support pages such as logs, history, webhook diagnostics, and reference lists still exist inside the workspace hub pages.",
            "A new What's New button in the admin header shows release notes and unread updates for each staff user.",
        ],
        "areas": ["Navigation", "Admin UX", "Release Notes"],
        "links": [
            {
                "label": "What's New",
                "url_name": "admin-whats-new",
                "note": "Open the full release history.",
            },
            {
                "label": "Customers & Sales",
                "url_name": "admin-workspace-customers-sales",
                "note": "Example of the focused-sidebar workspace pattern.",
            },
            {
                "label": "Website & Marketing",
                "url_name": "admin-workspace-website-marketing",
                "note": "Brand, content, and campaign hub.",
            },
        ],
    },
    {
        "key": "2026-03-19-admin-workspace-hubs",
        "published_at": "2026-03-19T12:00:00-06:00",
        "title": "Workspace hubs added for major admin areas",
        "summary": "Top-level admin sections now open combined workspace pages instead of forcing staff to jump between raw changelists.",
        "highlights": [
            "Operations, Customers & Sales, Website & Marketing, Reporting & Access, and Reference & Setup each have a dedicated hub page.",
            "Each hub groups the main actions first and keeps secondary/support pages nearby with context.",
            "Section headers in the sidebar are now clickable entry points into those hubs.",
        ],
        "areas": ["Navigation", "Workspaces"],
        "links": [
            {"label": "Operations", "url_name": "admin-workspace-operations", "note": "Appointments, staffing, and payments."},
            {"label": "Customers & Sales", "url_name": "admin-workspace-customers-sales", "note": "Clients, catalog, and fulfillment."},
            {"label": "Website & Marketing", "url_name": "admin-workspace-website-marketing", "note": "Content, brand system, and campaigns."},
            {"label": "Reporting & Access", "url_name": "admin-workspace-reporting-access", "note": "Insights and QA."},
            {"label": "Reference & Setup", "url_name": "admin-workspace-reference-setup", "note": "Reference data and maintenance."},
        ],
    },
]


def _coerce_release_datetime(value: Any):
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        return None
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_default_timezone())
    return dt


def _resolve_release_link(value: Any):
    if not isinstance(value, dict):
        return None

    label = str(value.get("label") or "").strip()
    if not label:
        return None

    href = str(value.get("href") or "").strip()
    url_name = str(value.get("url_name") or "").strip()
    model_label = str(value.get("model") or "").strip()
    note = str(value.get("note") or "").strip()
    url_kwargs = value.get("url_kwargs") if isinstance(value.get("url_kwargs"), dict) else {}
    url = ""

    if model_label:
        try:
            app_label, model_name = model_label.split(".", 1)
            model = apps.get_model(app_label, model_name)
            url = reverse(f"admin:{app_label}_{model._meta.model_name}_changelist")
        except Exception:
            url = ""
    elif url_name:
        try:
            url = reverse(url_name, kwargs=url_kwargs)
        except NoReverseMatch:
            url = href
    else:
        url = href

    url = str(url or "").strip()
    if not url:
        return None

    return {
        "label": label,
        "url": url,
        "note": note,
    }


def get_admin_releases() -> list[dict[str, Any]]:
    releases: list[dict[str, Any]] = []
    for release in ADMIN_RELEASES:
        published_at = _coerce_release_datetime(release.get("published_at"))
        if not published_at:
            continue
        releases.append(
            {
                "key": str(release.get("key") or "").strip(),
                "published_at": published_at,
                "title": str(release.get("title") or "").strip(),
                "summary": str(release.get("summary") or "").strip(),
                "highlights": [
                    item.strip()
                    for item in (release.get("highlights") or [])
                    if isinstance(item, str) and item.strip()
                ],
                "areas": [
                    item.strip()
                    for item in (release.get("areas") or [])
                    if isinstance(item, str) and item.strip()
                ],
                "links": [
                    resolved
                    for resolved in (
                        _resolve_release_link(item) for item in (release.get("links") or [])
                    )
                    if resolved
                ],
            }
        )
    releases.sort(key=lambda item: item["published_at"], reverse=True)
    return [release for release in releases if release["key"] and release["title"]]


def get_latest_admin_release_timestamp():
    releases = get_admin_releases()
    if not releases:
        return None
    return releases[0]["published_at"]


def get_admin_release_summary(last_seen_at=None, *, limit: int = 5) -> dict[str, Any]:
    releases = get_admin_releases()
    unseen = []
    if last_seen_at:
        if timezone.is_naive(last_seen_at):
            last_seen_at = timezone.make_aware(last_seen_at, timezone.get_default_timezone())
        unseen = [release for release in releases if release["published_at"] > last_seen_at]
    else:
        unseen = list(releases)
    return {
        "unseen_count": len(unseen),
        "latest": releases[: max(limit, 0)],
        "all": releases,
    }
