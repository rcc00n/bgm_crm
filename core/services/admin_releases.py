from __future__ import annotations

from datetime import datetime
from typing import Any

from django.utils import timezone


# Keep newest entries first. Every admin-facing UX/workflow change should add a
# release entry here and follow docs/admin_whats_new_agent_instructions.md.
ADMIN_RELEASES: list[dict[str, Any]] = [
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
