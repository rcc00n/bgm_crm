from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from django.contrib.auth import get_user_model
from django.conf import settings
from django.contrib.admin.models import LogEntry, ADDITION, CHANGE, DELETION
from django.core.paginator import Paginator
from django.db.models import Avg, Case, Count, IntegerField, Max, Q, Sum, When
from django.db.models.functions import TruncDate
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.utils.text import capfirst

from core.models import PageView, StaffLoginEvent, VisitorSession


def _percentile(sorted_values: List[int], percentile: float) -> float:
    if not sorted_values:
        return 0.0
    if percentile <= 0:
        return float(sorted_values[0])
    if percentile >= 1:
        return float(sorted_values[-1])

    k = (len(sorted_values) - 1) * percentile
    lower = int(k)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = k - lower
    return float(sorted_values[lower]) * (1 - weight) + float(sorted_values[upper]) * weight


def _day_range(window_days: int):
    today = timezone.localdate()
    start = today - timedelta(days=window_days - 1)
    return [start + timedelta(days=offset) for offset in range(window_days)]


def _format_duration(seconds: int) -> str:
    seconds = max(0, int(round(seconds or 0)))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def summarize_web_analytics(window_days: int = 7, *, include_admin: bool = False) -> Dict[str, object]:
    window_days = max(1, min(window_days, 31))
    day_list = _day_range(window_days)
    start_date = day_list[0]
    start_dt = timezone.make_aware(datetime.combine(start_date, datetime.min.time()))

    recent_views = PageView.objects.filter(started_at__gte=start_dt)
    if not include_admin:
        recent_views = recent_views.exclude(path__startswith="/admin")
    session_ids = recent_views.values_list("session_id", flat=True).distinct()
    recent_sessions = VisitorSession.objects.filter(id__in=session_ids)

    visits = recent_sessions.count()
    signed_in = recent_sessions.filter(user__isnull=False).count()
    total_page_views = recent_views.count()
    new_visitors = recent_sessions.filter(created_at__gte=start_dt).count()
    returning_visitors = max(0, visits - new_visitors)
    new_visitors_pct = round((new_visitors / visits) * 100, 1) if visits else 0.0

    admin_visits = recent_sessions.filter(user__is_staff=True).count()
    member_visits = recent_sessions.filter(user__is_staff=False, user__isnull=False).count()
    guest_visits = max(0, visits - admin_visits - member_visits)

    admin_page_views = recent_views.filter(user__is_staff=True).count()
    member_page_views = recent_views.filter(user__is_staff=False, user__isnull=False).count()
    guest_page_views = max(0, total_page_views - admin_page_views - member_page_views)
    admin_page_views_pct = round((admin_page_views / total_page_views) * 100, 1) if total_page_views else 0.0
    member_page_views_pct = round((member_page_views / total_page_views) * 100, 1) if total_page_views else 0.0
    guest_page_views_pct = round((guest_page_views / total_page_views) * 100, 1) if total_page_views else 0.0

    avg_duration_ms = recent_views.aggregate(avg=Avg("duration_ms"))["avg"] or 0
    avg_duration_seconds = round(avg_duration_ms / 1000, 1)
    avg_pages_per_visit = round(total_page_views / visits, 2) if visits else 0.0
    signed_in_pct = round((signed_in / visits) * 100, 1) if visits else 0.0

    duration_values = list(
        recent_views.exclude(duration_ms__isnull=True)
        .order_by("duration_ms")
        .values_list("duration_ms", flat=True)
    )
    max_duration_seconds = round((duration_values[-1] if duration_values else 0) / 1000, 1)
    median_seconds = round(_percentile(duration_values, 0.5) / 1000, 1)
    p90_seconds = round(_percentile(duration_values, 0.9) / 1000, 1)

    signed_in_avg_ms = (
        recent_views.filter(user__isnull=False).aggregate(avg=Avg("duration_ms"))["avg"] or 0
    )
    anonymous_avg_ms = (
        recent_views.filter(user__isnull=True).aggregate(avg=Avg("duration_ms"))["avg"] or 0
    )

    visitor_counts = (
        recent_views
        .annotate(day=TruncDate("started_at"))
        .values("day")
        .annotate(count=Count("session", distinct=True))
    )
    visitor_map = {entry["day"]: entry["count"] for entry in visitor_counts}
    visitor_timeseries: List[Dict[str, object]] = [
        {
            "label": day.strftime("%b %d"),
            "count": visitor_map.get(day, 0),
        }
        for day in day_list
    ]

    engagement_counts = (
        recent_views
        .annotate(day=TruncDate("started_at"))
        .values("day")
        .annotate(
            avg_duration=Avg("duration_ms"),
            views=Count("id"),
        )
    )
    engagement_map = {entry["day"]: entry for entry in engagement_counts}
    engagement_timeseries = [
        {
            "label": day.strftime("%b %d"),
            "avg": round((engagement_map.get(day, {}).get("avg_duration") or 0) / 1000, 1),
            "views": engagement_map.get(day, {}).get("views", 0),
        }
        for day in day_list
    ]

    def _first_or_none(items: List[Dict[str, object]]) -> Optional[Dict[str, object]]:
        return items[0] if items else None

    busiest_visit_day: Optional[Dict[str, object]] = None
    quietest_visit_day: Optional[Dict[str, object]] = None
    if visits:
        visitors_desc = sorted(visitor_timeseries, key=lambda x: x["count"], reverse=True)
        visitors_asc = list(reversed(visitors_desc)) if visitors_desc else []
        busiest_visit_day = _first_or_none(visitors_desc)
        quietest_visit_day = _first_or_none(visitors_asc)

    best_engagement_day: Optional[Dict[str, object]] = None
    if total_page_views:
        populated_engagement = [entry for entry in engagement_timeseries if entry.get("views")]
        best_engagement_day = max(populated_engagement, key=lambda x: x["avg"], default=None)

    top_pages = list(
        recent_views.values("path")
        .annotate(views=Count("id"), avg_duration=Avg("duration_ms"))
        .order_by("-views")[:6]
    )
    for page in top_pages:
        page["avg_seconds"] = round((page.get("avg_duration") or 0) / 1000, 1)

    slow_pages = list(
        recent_views.filter(duration_ms__gte=3000)
        .values("path")
        .annotate(avg_duration=Avg("duration_ms"), views=Count("id"))
        .order_by("-avg_duration")[:5]
    )
    for entry in slow_pages:
        entry["avg_seconds"] = round((entry.get("avg_duration") or 0) / 1000, 1)

    top_referrers = list(
        recent_views.exclude(referrer="")
        .values("referrer")
        .annotate(visits=Count("session", distinct=True))
        .order_by("-visits")[:5]
    )

    signed_in_sessions = list(
        VisitorSession.objects.filter(user__isnull=False)
        .order_by("-last_seen_at")
        .values("user_name_snapshot", "user_email_snapshot", "last_seen_at")[:5]
    )

    return {
        "window_days": window_days,
        "has_data": bool(visits or total_page_views),
        "totals": {
            "visits": visits,
            "unique_visitors": visits,
            "new_visitors": new_visitors,
            "returning_visitors": returning_visitors,
            "new_visitors_pct": new_visitors_pct,
            "signed_in": signed_in,
            "signed_in_pct": signed_in_pct,
            "avg_duration_seconds": avg_duration_seconds,
            "avg_pages_per_visit": avg_pages_per_visit,
            "page_views": total_page_views,
            "admin_visits": admin_visits,
            "member_visits": member_visits,
            "guest_visits": guest_visits,
            "admin_page_views": admin_page_views,
            "member_page_views": member_page_views,
            "guest_page_views": guest_page_views,
            "admin_page_views_pct": admin_page_views_pct,
            "member_page_views_pct": member_page_views_pct,
            "guest_page_views_pct": guest_page_views_pct,
        },
        "top_pages": top_pages,
        "slow_pages": slow_pages,
        "top_referrers": top_referrers,
        "engagement": {
            "average_seconds": avg_duration_seconds,
            "median_seconds": median_seconds,
            "p90_seconds": p90_seconds,
            "max_seconds": max_duration_seconds,
            "avg_signed_in_seconds": round(signed_in_avg_ms / 1000, 1),
            "avg_anonymous_seconds": round(anonymous_avg_ms / 1000, 1),
            "avg_pages_per_visit": avg_pages_per_visit,
            "total_page_views": total_page_views,
            "sample_size": len(duration_values),
        },
        "traffic_highlights": {
            "busiest_day": busiest_visit_day,
            "quietest_day": quietest_visit_day,
            "best_engagement_day": best_engagement_day,
        },
        "recent_signed_in_sessions": signed_in_sessions,
    }


def summarize_web_analytics_periods(
    windows: List[int], cache: Optional[Dict[int, Dict[str, object]]] = None
) -> List[Dict[str, object]]:
    """
    Produce compact summaries for multiple windows, reusing cached summaries when provided.
    """

    normalized_seen = set()
    results: List[Dict[str, object]] = []
    cache = cache or {}

    for days in windows:
        normalized = max(1, min(days, 31))
        if normalized in normalized_seen:
            continue
        normalized_seen.add(normalized)

        summary = cache.get(normalized) or summarize_web_analytics(window_days=normalized)
        label = "Today" if normalized == 1 else f"Last {normalized} days"

        results.append(
            {
                "label": label,
                "window_days": normalized,
                "totals": summary.get("totals", {}),
                "engagement": summary.get("engagement", {}),
                "traffic_highlights": summary.get("traffic_highlights", {}),
            }
        )

    return results


def _format_utc_offset(minutes: int) -> str:
    minutes = int(minutes or 0)
    sign = "+" if minutes >= 0 else "-"
    total = abs(minutes)
    hours, mins = divmod(total, 60)
    if mins:
        return f"UTC{sign}{hours}:{mins:02d}"
    return f"UTC{sign}{hours}"


def _classify_referrer(referrer: str, host: Optional[str] = None) -> str:
    if not referrer:
        return "Direct"
    ref = referrer.lower()
    if host and host.lower() in ref:
        return "Internal"
    search_sources = (
        "google.",
        "bing.",
        "yahoo.",
        "duckduckgo.",
        "baidu.",
        "yandex.",
    )
    if any(token in ref for token in search_sources):
        return "Search"
    social_sources = (
        "facebook.com",
        "instagram.com",
        "t.co",
        "twitter.com",
        "linkedin.com",
        "tiktok.com",
        "pinterest.com",
    )
    if any(token in ref for token in social_sources):
        return "Social"
    email_sources = (
        "mail.",
        "gmail",
        "outlook",
        "mailchimp",
        "newsletter",
        "sendgrid",
        "mandrill",
    )
    if any(token in ref for token in email_sources):
        return "Email"
    return "Other"


def _classify_browser(user_agent: str) -> str:
    if not user_agent:
        return "Unknown"
    agent = user_agent.lower()
    if "edg" in agent:
        return "Edge"
    if "opr" in agent or "opera" in agent:
        return "Opera"
    if "chrome" in agent and "chromium" not in agent and "edg" not in agent and "opr" not in agent:
        return "Chrome"
    if "safari" in agent and "chrome" not in agent:
        return "Safari"
    if "firefox" in agent:
        return "Firefox"
    return "Other"


def _classify_os(user_agent: str) -> str:
    if not user_agent:
        return "Unknown"
    agent = user_agent.lower()
    if "windows" in agent:
        return "Windows"
    if "iphone" in agent or "ipad" in agent or "ios" in agent:
        return "iOS"
    if "android" in agent:
        return "Android"
    if "macintosh" in agent or "mac os" in agent:
        return "macOS"
    if "linux" in agent:
        return "Linux"
    return "Other"


def _classify_device_from_user_agent(user_agent: str) -> str:
    if not user_agent:
        return "Unknown"
    agent = user_agent.lower()
    if "ipad" in agent or "tablet" in agent:
        return "Tablet"
    if "mobi" in agent or "iphone" in agent or "android" in agent:
        return "Mobile"
    return "Desktop"


def _format_login_device_label(user_agent: str) -> str:
    device = _classify_device_from_user_agent(user_agent)
    browser = _classify_browser(user_agent)
    os_label = _classify_os(user_agent)

    detail = ""
    if browser != "Unknown" and os_label != "Unknown":
        detail = f"{browser} on {os_label}"
    elif browser != "Unknown":
        detail = browser
    elif os_label != "Unknown":
        detail = os_label

    return f"{device} · {detail}" if detail else device


def _staff_login_source_label(path: str) -> str:
    normalized = (path or "").strip()
    if normalized.startswith("/admin/") or normalized == "/admin":
        return "Admin"
    if normalized:
        return "Site"
    return "Unknown"


def summarize_web_analytics_insights(
    window_days: int = 30,
    host: Optional[str] = None,
    include_admin: bool = False,
) -> Dict[str, object]:
    window_days = max(1, min(window_days, 90))
    day_list = _day_range(window_days)
    start_date = day_list[0]
    start_dt = timezone.make_aware(datetime.combine(start_date, datetime.min.time()))

    views = PageView.objects.filter(started_at__gte=start_dt)
    if not include_admin:
        views = views.exclude(path__startswith="/admin")

    page_views = views.count()
    admin_page_views = views.filter(user__is_staff=True).count()
    member_page_views = views.filter(user__is_staff=False, user__isnull=False).count()
    guest_page_views = max(0, page_views - admin_page_views - member_page_views)
    admin_page_views_pct = round((admin_page_views / page_views) * 100, 1) if page_views else 0.0
    member_page_views_pct = round((member_page_views / page_views) * 100, 1) if page_views else 0.0
    guest_page_views_pct = round((guest_page_views / page_views) * 100, 1) if page_views else 0.0
    avg_duration_ms = views.aggregate(avg=Avg("duration_ms"))["avg"] or 0
    avg_duration_seconds = round(avg_duration_ms / 1000, 1)

    duration_values = list(
        views.exclude(duration_ms__isnull=True)
        .order_by("duration_ms")
        .values_list("duration_ms", flat=True)
    )
    median_seconds = round(_percentile(duration_values, 0.5) / 1000, 1)
    p90_seconds = round(_percentile(duration_values, 0.9) / 1000, 1)

    duration_buckets = {
        "<5s": 0,
        "5-15s": 0,
        "15-60s": 0,
        "1-3m": 0,
        "3m+": 0,
    }
    for value in duration_values:
        if value < 5000:
            duration_buckets["<5s"] += 1
        elif value < 15000:
            duration_buckets["5-15s"] += 1
        elif value < 60000:
            duration_buckets["15-60s"] += 1
        elif value < 180000:
            duration_buckets["1-3m"] += 1
        else:
            duration_buckets["3m+"] += 1

    session_stats = {}
    session_totals = []
    total_session_ms = 0
    max_session_ms = 0
    bounce_sessions = 0
    engaged_sessions = 0
    depth_buckets = {
        "1 page": 0,
        "2-3 pages": 0,
        "4-6 pages": 0,
        "7+ pages": 0,
    }
    session_duration_buckets = {
        "<1m": 0,
        "1-3m": 0,
        "3-10m": 0,
        "10m+": 0,
    }

    for row in views.values("session_id").annotate(views=Count("id"), total_ms=Sum("duration_ms")):
        session_id = row["session_id"]
        views_count = int(row.get("views") or 0)
        total_ms = int(row.get("total_ms") or 0)
        session_stats[session_id] = {"views": views_count, "total_ms": total_ms}
        session_totals.append(total_ms)
        total_session_ms += total_ms
        max_session_ms = max(max_session_ms, total_ms)

        if views_count <= 1:
            bounce_sessions += 1
            depth_buckets["1 page"] += 1
        elif views_count <= 3:
            depth_buckets["2-3 pages"] += 1
        elif views_count <= 6:
            depth_buckets["4-6 pages"] += 1
        else:
            depth_buckets["7+ pages"] += 1

        if views_count >= 3 or total_ms >= 60000:
            engaged_sessions += 1

        if total_ms < 60000:
            session_duration_buckets["<1m"] += 1
        elif total_ms < 180000:
            session_duration_buckets["1-3m"] += 1
        elif total_ms < 600000:
            session_duration_buckets["3-10m"] += 1
        else:
            session_duration_buckets["10m+"] += 1

    visits = len(session_stats)
    avg_pages_per_visit = round(page_views / visits, 2) if visits else 0.0
    avg_session_seconds = round((total_session_ms / visits) / 1000, 1) if visits else 0.0
    max_session_seconds = round(max_session_ms / 1000, 1) if max_session_ms else 0.0
    session_totals_sorted = sorted(session_totals)
    session_median_seconds = round(_percentile(session_totals_sorted, 0.5) / 1000, 1)
    session_p90_seconds = round(_percentile(session_totals_sorted, 0.9) / 1000, 1)
    bounce_pct = round((bounce_sessions / visits) * 100, 1) if visits else 0.0
    engaged_pct = round((engaged_sessions / visits) * 100, 1) if visits else 0.0

    session_ids = list(session_stats.keys())
    sessions = VisitorSession.objects.filter(id__in=session_ids)

    signed_in = 0
    new_sessions = 0
    referrer_counts = defaultdict(int)
    browser_counts = defaultdict(int)
    os_counts = defaultdict(int)
    landing_stats = {}
    ip_stats = {}
    session_leaders = []

    for session in sessions.values(
        "id",
        "landing_path",
        "referrer",
        "user_agent",
        "user_id",
        "user_name_snapshot",
        "user_email_snapshot",
        "ip_address",
        "ip_location",
        "created_at",
        "last_seen_at",
    ):
        session_id = session["id"]
        stats = session_stats.get(session_id, {"views": 0, "total_ms": 0})
        views_count = int(stats.get("views") or 0)
        total_ms = int(stats.get("total_ms") or 0)
        landing_path = session.get("landing_path") or "—"

        landing_entry = landing_stats.setdefault(
            landing_path,
            {"visits": 0, "bounces": 0, "views": 0, "total_ms": 0},
        )
        landing_entry["visits"] += 1
        landing_entry["views"] += views_count
        landing_entry["total_ms"] += total_ms
        if views_count <= 1:
            landing_entry["bounces"] += 1

        referrer_counts[_classify_referrer(session.get("referrer") or "", host)] += 1
        browser_counts[_classify_browser(session.get("user_agent") or "")] += 1
        os_counts[_classify_os(session.get("user_agent") or "")] += 1

        if session.get("user_id"):
            signed_in += 1
        if session.get("created_at") and session["created_at"] >= start_dt:
            new_sessions += 1

        ip_address = session.get("ip_address") or ""
        ip_location = session.get("ip_location") or ""
        if ip_address:
            ip_entry = ip_stats.setdefault(
                ip_address,
                {"visits": 0, "signed_in": 0, "last_seen": None, "location": ""},
            )
            ip_entry["visits"] += 1
            if session.get("user_id"):
                ip_entry["signed_in"] += 1
            last_seen = session.get("last_seen_at")
            if last_seen and (not ip_entry["last_seen"] or last_seen > ip_entry["last_seen"]):
                ip_entry["last_seen"] = last_seen
            if ip_location and not ip_entry["location"]:
                ip_entry["location"] = ip_location

        session_leaders.append(
            {
                "session_id": str(session_id),
                "user_name": session.get("user_name_snapshot") or "Guest",
                "user_email": session.get("user_email_snapshot") or "",
                "ip_address": ip_address or "",
                "ip_location": ip_location or "",
                "landing_path": landing_path,
                "views": views_count,
                "total_seconds": round(total_ms / 1000, 1),
                "last_seen": session.get("last_seen_at"),
            }
        )

    signed_in_pct = round((signed_in / visits) * 100, 1) if visits else 0.0
    returning_sessions = max(0, visits - new_sessions)
    returning_pct = round((returning_sessions / visits) * 100, 1) if visits else 0.0
    new_visitors_pct = round((new_sessions / visits) * 100, 1) if visits else 0.0

    admin_visits = sessions.filter(user__is_staff=True).count()
    member_visits = sessions.filter(user__is_staff=False, user__isnull=False).count()
    guest_visits = max(0, visits - admin_visits - member_visits)
    admin_visits_pct = round((admin_visits / visits) * 100, 1) if visits else 0.0
    member_visits_pct = round((member_visits / visits) * 100, 1) if visits else 0.0
    guest_visits_pct = round((guest_visits / visits) * 100, 1) if visits else 0.0

    landing_pages = []
    for path, stats in landing_stats.items():
        visits_count = stats["visits"]
        avg_pages = round(stats["views"] / visits_count, 2) if visits_count else 0.0
        avg_seconds = round((stats["total_ms"] / visits_count) / 1000, 1) if visits_count else 0.0
        landing_pages.append(
            {
                "path": path,
                "visits": visits_count,
                "bounce_pct": round((stats["bounces"] / visits_count) * 100, 1)
                if visits_count
                else 0.0,
                "avg_pages": avg_pages,
                "avg_seconds": avg_seconds,
            }
        )
    landing_pages.sort(key=lambda item: (-item["visits"], item["path"]))
    landing_pages = landing_pages[:8]

    session_leaders.sort(key=lambda item: (-item["total_seconds"], -item["views"]))
    session_leaders = session_leaders[:6]

    ip_rows = []
    for ip, stats in ip_stats.items():
        visits_count = stats["visits"]
        ip_rows.append(
            {
                "ip_address": ip,
                "location": stats.get("location") or "",
                "visits": visits_count,
                "signed_in": stats["signed_in"],
                "signed_in_pct": round((stats["signed_in"] / visits_count) * 100, 1)
                if visits_count
                else 0.0,
                "last_seen": stats["last_seen"],
            }
        )
    ip_rows.sort(key=lambda item: (-item["visits"], item["ip_address"]))
    ip_rows = ip_rows[:6]

    browser_mix = [
        {"label": key, "count": value}
        for key, value in sorted(browser_counts.items(), key=lambda item: -item[1])
    ]
    os_mix = [
        {"label": key, "count": value}
        for key, value in sorted(os_counts.items(), key=lambda item: -item[1])
    ]
    referrer_mix = [
        {"label": key, "count": value}
        for key, value in sorted(referrer_counts.items(), key=lambda item: -item[1])
    ]

    device_counts = views.aggregate(
        mobile=Count("id", filter=Q(viewport_width__gt=0, viewport_width__lt=768)),
        tablet=Count(
            "id",
            filter=Q(viewport_width__gte=768, viewport_width__lt=1024),
        ),
        desktop=Count("id", filter=Q(viewport_width__gte=1024)),
        unknown=Count("id", filter=Q(viewport_width__isnull=True) | Q(viewport_width=0)),
    )
    device_mix = [
        {"label": "Desktop", "count": int(device_counts.get("desktop") or 0)},
        {"label": "Tablet", "count": int(device_counts.get("tablet") or 0)},
        {"label": "Mobile", "count": int(device_counts.get("mobile") or 0)},
        {"label": "Unknown", "count": int(device_counts.get("unknown") or 0)},
    ]

    timezone_rows = list(
        views.values("timezone_offset")
        .annotate(count=Count("id"))
        .order_by("-count")
    )
    timezone_mix = []
    other_timezones = 0
    for idx, row in enumerate(timezone_rows):
        if idx < 6:
            timezone_mix.append(
                {
                    "label": _format_utc_offset(row.get("timezone_offset") or 0),
                    "count": row.get("count") or 0,
                }
            )
        else:
            other_timezones += row.get("count") or 0
    if other_timezones:
        timezone_mix.append({"label": "Other", "count": other_timezones})

    daily_counts = (
        views.annotate(day=TruncDate("started_at"))
        .values("day")
        .annotate(count=Count("session", distinct=True))
    )
    daily_map = {entry["day"]: entry["count"] for entry in daily_counts}
    daily_visits = [
        {"label": day.strftime("%b %d"), "count": daily_map.get(day, 0)} for day in day_list
    ]

    hourly_counts = [0] * 24
    for started_at, offset in views.values_list("started_at", "timezone_offset").iterator():
        local = started_at + timedelta(minutes=offset or 0)
        hourly_counts[local.hour] += 1
    hourly_activity = [
        {"label": f"{hour:02d}:00", "count": count} for hour, count in enumerate(hourly_counts)
    ]

    exit_counts = defaultdict(int)
    seen_sessions = set()
    for session_id, path in (
        views.order_by("session_id", "-started_at")
        .values_list("session_id", "path")
        .iterator()
    ):
        if session_id in seen_sessions:
            continue
        seen_sessions.add(session_id)
        exit_counts[path] += 1
    exit_pages = [
        {"path": path, "exits": count}
        for path, count in sorted(exit_counts.items(), key=lambda item: -item[1])
    ][:8]

    top_pages = list(
        views.values("path")
        .annotate(views=Count("id"), avg_duration=Avg("duration_ms"))
        .order_by("-views")[:8]
    )
    for entry in top_pages:
        entry["avg_seconds"] = round((entry.get("avg_duration") or 0) / 1000, 1)

    top_pages_by_duration = list(
        views.values("path")
        .annotate(views=Count("id"), avg_duration=Avg("duration_ms"))
        .filter(views__gte=3)
        .order_by("-avg_duration")[:6]
    )
    for entry in top_pages_by_duration:
        entry["avg_seconds"] = round((entry.get("avg_duration") or 0) / 1000, 1)

    top_referrers = list(
        views.exclude(referrer="")
        .values("referrer")
        .annotate(visits=Count("session", distinct=True))
        .order_by("-visits")[:6]
    )

    screen_sizes = list(
        views.exclude(viewport_width__isnull=True)
        .exclude(viewport_height__isnull=True)
        .values("viewport_width", "viewport_height")
        .annotate(count=Count("id"))
        .order_by("-count")[:6]
    )
    for entry in screen_sizes:
        entry["label"] = f"{entry.get('viewport_width')}×{entry.get('viewport_height')}"

    def _mix_with_pct(rows: List[Dict[str, object]], total: int) -> List[Dict[str, object]]:
        if not total:
            return rows
        for row in rows:
            row["pct"] = round((row["count"] / total) * 100, 1) if row.get("count") else 0.0
        return rows

    device_mix = _mix_with_pct(device_mix, page_views)
    referrer_mix = _mix_with_pct(referrer_mix, visits)
    browser_mix = _mix_with_pct(browser_mix, visits)
    os_mix = _mix_with_pct(os_mix, visits)
    timezone_mix = _mix_with_pct(timezone_mix, page_views)

    depth_bucket_list = [{"label": key, "count": value} for key, value in depth_buckets.items()]
    duration_bucket_list = [
        {"label": key, "count": value} for key, value in duration_buckets.items()
    ]
    session_duration_bucket_list = [
        {"label": key, "count": value} for key, value in session_duration_buckets.items()
    ]

    return {
        "window_days": window_days,
        "range": {"start": start_date, "end": day_list[-1]},
        "has_data": bool(visits or page_views),
        "totals": {
            "visits": visits,
            "unique_visitors": visits,
            "new_visitors": new_sessions,
            "new_visitors_pct": new_visitors_pct,
            "returning_visitors": returning_sessions,
            "page_views": page_views,
            "signed_in": signed_in,
            "signed_in_pct": signed_in_pct,
            "admin_visits": admin_visits,
            "admin_visits_pct": admin_visits_pct,
            "member_visits": member_visits,
            "member_visits_pct": member_visits_pct,
            "guest_visits": guest_visits,
            "guest_visits_pct": guest_visits_pct,
            "admin_page_views": admin_page_views,
            "admin_page_views_pct": admin_page_views_pct,
            "member_page_views": member_page_views,
            "member_page_views_pct": member_page_views_pct,
            "guest_page_views": guest_page_views,
            "guest_page_views_pct": guest_page_views_pct,
            "unique_ips": len(ip_stats),
            "avg_duration_seconds": avg_duration_seconds,
            "median_duration_seconds": median_seconds,
            "p90_duration_seconds": p90_seconds,
            "avg_pages_per_visit": avg_pages_per_visit,
        },
        "sessions": {
            "new": new_sessions,
            "returning": returning_sessions,
            "returning_pct": returning_pct,
            "bounce_sessions": bounce_sessions,
            "bounce_pct": bounce_pct,
            "engaged_sessions": engaged_sessions,
            "engaged_pct": engaged_pct,
            "avg_seconds": avg_session_seconds,
            "median_seconds": session_median_seconds,
            "p90_seconds": session_p90_seconds,
            "max_seconds": max_session_seconds,
            "depth_buckets": depth_bucket_list,
            "duration_buckets": session_duration_bucket_list,
        },
        "views": {
            "avg_seconds": avg_duration_seconds,
            "median_seconds": median_seconds,
            "p90_seconds": p90_seconds,
            "duration_buckets": duration_bucket_list,
        },
        "daily_visits": daily_visits,
        "hourly_activity": hourly_activity,
        "device_mix": device_mix,
        "referrer_mix": referrer_mix,
        "browser_mix": browser_mix,
        "os_mix": os_mix,
        "timezone_mix": timezone_mix,
        "landing_pages": landing_pages,
        "exit_pages": exit_pages,
        "top_pages": top_pages,
        "top_pages_by_duration": top_pages_by_duration,
        "top_referrers": top_referrers,
        "top_ips": ip_rows,
        "screen_sizes": screen_sizes,
        "session_leaders": session_leaders,
    }


def summarize_staff_usage(window_days: int = 7, include_inactive: bool = False) -> Dict[str, object]:
    """
    Summarize staff time on admin vs client pages within a window.
    """
    window_days = max(1, min(window_days, 90))
    day_list = _day_range(window_days)
    start_date = day_list[0]
    window_start = timezone.make_aware(datetime.combine(start_date, datetime.min.time()))
    window_end = timezone.now()

    # Staff often keeps admin pages open for long periods, which means a PageView can start
    # outside the requested window yet still be active within it (updated_at keeps moving).
    # We therefore filter by updated_at and estimate the portion of duration that overlaps
    # the requested window.

    admin_prefixes: List[str] = []
    try:
        admin_prefixes.append(reverse("admin:index"))
    except Exception:
        pass
    configured_prefixes = getattr(settings, "ADMIN_USAGE_PATH_PREFIXES", None) or []
    for prefix in configured_prefixes:
        if prefix:
            admin_prefixes.append(str(prefix))
    admin_prefixes.extend(["/admin/", "/admin"])

    normalized_prefixes: List[str] = []
    for prefix in admin_prefixes:
        prefix = (prefix or "").strip()
        if not prefix:
            continue
        if not prefix.startswith("/"):
            prefix = f"/{prefix}"
        normalized_prefixes.append(prefix)
    normalized_prefixes = list(dict.fromkeys(normalized_prefixes))

    def _is_admin_path(path: str, full_path: str) -> bool:
        path = path or ""
        full_path = full_path or ""
        for prefix in normalized_prefixes:
            if (
                path.startswith(prefix)
                or prefix in path
                or full_path.startswith(prefix)
                or prefix in full_path
            ):
                return True
        return False

    def _overlap_ms(a_start, a_end, b_start, b_end) -> int:
        start = max(a_start, b_start)
        end = min(a_end, b_end)
        if end <= start:
            return 0
        return int(round((end - start).total_seconds() * 1000))

    def _window_duration_ms(started_at, updated_at, duration_ms: int) -> int:
        """
        Estimate how much of the recorded visible time fell within [window_start, window_end].

        We treat the recorded visible time as a contiguous block ending at updated_at.
        This avoids dropping long-lived PageViews that started before the window.
        """
        try:
            duration_ms = int(duration_ms or 0)
        except (TypeError, ValueError):
            duration_ms = 0
        if duration_ms <= 0:
            return 0
        if not started_at or not updated_at:
            return 0
        if updated_at <= window_start:
            return 0
        if updated_at < started_at:
            return 0

        active_end = min(updated_at, window_end)
        active_start = updated_at - timedelta(milliseconds=duration_ms)
        if active_start < started_at:
            active_start = started_at

        return _overlap_ms(active_start, active_end, window_start, window_end)

    view_rows = (
        PageView.objects.filter(
            updated_at__gte=window_start,
            user__isnull=False,
            user__is_staff=True,
        )
        .values("user_id", "path", "full_path", "started_at", "updated_at", "duration_ms")
        .iterator()
    )

    admin_ms_by_user: Dict[int, int] = defaultdict(int)
    client_ms_by_user: Dict[int, int] = defaultdict(int)
    admin_views_by_user: Dict[int, int] = defaultdict(int)
    client_views_by_user: Dict[int, int] = defaultdict(int)
    last_seen_by_user: Dict[int, datetime] = {}

    for row in view_rows:
        user_id = row.get("user_id")
        if not user_id:
            continue

        updated_at = row.get("updated_at")
        if updated_at:
            current_last = last_seen_by_user.get(user_id)
            if not current_last or updated_at > current_last:
                last_seen_by_user[user_id] = updated_at

        window_ms = _window_duration_ms(
            started_at=row.get("started_at"),
            updated_at=updated_at,
            duration_ms=row.get("duration_ms") or 0,
        )

        if _is_admin_path(row.get("path") or "", row.get("full_path") or ""):
            admin_views_by_user[user_id] += 1
            admin_ms_by_user[user_id] += window_ms
        else:
            client_views_by_user[user_id] += 1
            client_ms_by_user[user_id] += window_ms

    User = get_user_model()
    staff_qs = User.objects.filter(is_staff=True)
    if not include_inactive:
        staff_qs = staff_qs.filter(is_active=True)
    staff_list = list(staff_qs.order_by("first_name", "last_name", "username", "email"))

    rows = []
    total_admin_ms = 0
    total_client_ms = 0
    total_admin_views = 0
    total_client_views = 0

    for user in staff_list:
        admin_ms = int(admin_ms_by_user.get(user.id, 0) or 0)
        client_ms = int(client_ms_by_user.get(user.id, 0) or 0)
        admin_views = int(admin_views_by_user.get(user.id, 0) or 0)
        client_views = int(client_views_by_user.get(user.id, 0) or 0)
        total_ms = admin_ms + client_ms

        admin_seconds = int(round(admin_ms / 1000))
        client_seconds = int(round(client_ms / 1000))
        total_seconds = int(round(total_ms / 1000))

        total_admin_ms += admin_ms
        total_client_ms += client_ms
        total_admin_views += admin_views
        total_client_views += client_views

        display_name = user.get_full_name() or user.username or user.email or f"User {user.id}"

        rows.append(
            {
                "user_id": user.id,
                "name": display_name.strip(),
                "email": user.email or "",
                "admin_seconds": admin_seconds,
                "client_seconds": client_seconds,
                "total_seconds": total_seconds,
                "admin_label": _format_duration(admin_seconds),
                "client_label": _format_duration(client_seconds),
                "total_label": _format_duration(total_seconds),
                "admin_views": admin_views,
                "client_views": client_views,
                "total_views": admin_views + client_views,
                "last_seen": last_seen_by_user.get(user.id),
            }
        )

    rows.sort(key=lambda row: (-row["total_seconds"], row["name"].lower()))
    active_staff = sum(1 for row in rows if row["total_seconds"] > 0)

    total_admin_seconds = int(round(total_admin_ms / 1000))
    total_client_seconds = int(round(total_client_ms / 1000))
    total_seconds = int(round((total_admin_ms + total_client_ms) / 1000))

    return {
        "window_days": window_days,
        "has_data": total_seconds > 0,
        "staff_count": len(rows),
        "active_staff_count": active_staff,
        "totals": {
            "admin_seconds": total_admin_seconds,
            "client_seconds": total_client_seconds,
            "total_seconds": total_seconds,
            "admin_label": _format_duration(total_admin_seconds),
            "client_label": _format_duration(total_client_seconds),
            "total_label": _format_duration(total_seconds),
            "admin_views": total_admin_views,
            "client_views": total_client_views,
            "total_views": total_admin_views + total_client_views,
        },
        "rows": rows,
    }


def summarize_staff_usage_periods(
    windows: List[int], include_inactive: bool = False
) -> List[Dict[str, object]]:
    """
    Produce staff usage summaries for multiple windows.
    """
    normalized_seen = set()
    results: List[Dict[str, object]] = []

    for days in windows:
        normalized = max(1, min(days, 90))
        if normalized in normalized_seen:
            continue
        normalized_seen.add(normalized)

        summary = summarize_staff_usage(window_days=normalized, include_inactive=include_inactive)
        label = "Today" if normalized == 1 else f"Last {normalized} days"

        results.append(
            {
                "label": label,
                "window_days": normalized,
                "has_data": summary.get("has_data"),
                "staff_count": summary.get("staff_count", 0),
                "active_staff_count": summary.get("active_staff_count", 0),
                "totals": summary.get("totals", {}),
                "rows": summary.get("rows", []),
            }
        )

    return results


def summarize_staff_login_history(
    window_days: int = 30,
    limit: int = 25,
) -> Dict[str, object]:
    """
    Recent successful sign-ins for staff users.
    """
    window_days = max(1, min(int(window_days or 0), 365))
    limit = max(1, min(int(limit or 0), 100))
    start_date = timezone.localdate() - timedelta(days=window_days - 1)
    start_dt = timezone.make_aware(datetime.combine(start_date, datetime.min.time()))

    login_qs = (
        StaffLoginEvent.objects.select_related("user")
        .filter(logged_in_at__gte=start_dt, user__is_staff=True)
        .order_by("-logged_in_at")
    )

    rows = []
    for event in login_qs[:limit]:
        user = event.user
        name = (
            (user.get_full_name() or "").strip()
            or (user.username or "").strip()
            or (user.email or "").strip()
            or f"User {user.pk}"
        )
        rows.append(
            {
                "user_id": user.pk,
                "name": name,
                "email": (user.email or "").strip(),
                "ip_address": event.ip_address or "—",
                "ip_location": (event.ip_location or "").strip(),
                "device_label": _format_login_device_label(event.user_agent or ""),
                "user_agent": (event.user_agent or "").strip(),
                "source_label": _staff_login_source_label(event.login_path),
                "login_path": (event.login_path or "").strip(),
                "logged_in_at": event.logged_in_at,
            }
        )

    total_count = login_qs.count()
    unique_staff_count = login_qs.values("user_id").distinct().count()

    return {
        "window_days": window_days,
        "total_count": total_count,
        "unique_staff_count": unique_staff_count,
        "rows": rows,
        "has_data": bool(rows),
    }


def _staff_action_meta(flag: int) -> Dict[str, str]:
    if flag == ADDITION:
        return {"label": "Added", "css": "added"}
    if flag == CHANGE:
        return {"label": "Changed", "css": "changed"}
    if flag == DELETION:
        return {"label": "Deleted", "css": "deleted"}
    return {"label": "Action", "css": "changed"}


def summarize_staff_action_history(
    window_days: int = 30,
    page: int = 1,
    per_page: int = 50,
    include_inactive: bool = False,
    user_id: Optional[int] = None,
    action_flag: Optional[int] = None,
    content_type_id: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    query: str = "",
) -> Dict[str, object]:
    """
    Recent admin actions (add/change/delete) performed by staff users.
    """
    window_days = max(1, min(int(window_days or 0), 365))
    allowed_page_sizes = {25, 50}
    try:
        per_page = int(per_page or 0)
    except (TypeError, ValueError):
        per_page = 50
    if per_page not in allowed_page_sizes:
        per_page = 50

    try:
        page = int(page or 1)
    except (TypeError, ValueError):
        page = 1

    today = timezone.localdate()
    # Date range filter wins; otherwise fall back to "last N days".
    if start_date or end_date:
        if start_date is None:
            start_date = end_date
        if end_date is None:
            end_date = start_date
        if start_date and end_date and end_date < start_date:
            start_date, end_date = end_date, start_date
        # Keep queries bounded.
        if start_date and end_date and (end_date - start_date).days > 364:
            start_date = end_date - timedelta(days=364)

        window_days = max(1, int((end_date - start_date).days) + 1) if start_date and end_date else window_days
        start_dt = timezone.make_aware(datetime.combine(start_date, datetime.min.time()))
        end_dt = timezone.make_aware(datetime.combine(end_date, datetime.max.time()))
        entries_qs = (
            LogEntry.objects.select_related("user", "content_type")
            .filter(action_time__range=(start_dt, end_dt), user__is_staff=True)
            .order_by("-action_time")
        )
    else:
        since = timezone.now() - timedelta(days=window_days)
        start_date = today - timedelta(days=window_days - 1)
        end_date = today
        entries_qs = (
            LogEntry.objects.select_related("user", "content_type")
            .filter(action_time__gte=since, user__is_staff=True)
            .order_by("-action_time")
        )
    if not include_inactive:
        entries_qs = entries_qs.filter(user__is_active=True)

    if user_id:
        entries_qs = entries_qs.filter(user_id=int(user_id))

    if action_flag in {ADDITION, CHANGE, DELETION}:
        entries_qs = entries_qs.filter(action_flag=int(action_flag))

    if content_type_id:
        entries_qs = entries_qs.filter(content_type_id=int(content_type_id))

    query = (query or "").strip()
    if query:
        q_filter = Q(object_repr__icontains=query) | Q(change_message__icontains=query)
        if query.isdigit():
            q_filter = q_filter | Q(object_id=query)
        entries_qs = entries_qs.filter(q_filter)

    totals_by_user_raw = list(
        entries_qs.values(
            "user_id",
            "user__first_name",
            "user__last_name",
            "user__username",
            "user__email",
        )
        .annotate(total=Count("id"))
        .order_by("-total", "user__username")[:50]
    )
    totals_by_user = []
    for row in totals_by_user_raw:
        first = (row.get("user__first_name") or "").strip()
        last = (row.get("user__last_name") or "").strip()
        username = (row.get("user__username") or "").strip()
        email = (row.get("user__email") or "").strip()
        label = f"{first} {last}".strip() or username or email or f"User {row.get('user_id')}"
        totals_by_user.append(
            {
                "user_id": row.get("user_id"),
                "user_name": label,
                "user_email": email,
                "total": row.get("total") or 0,
            }
        )

    action_totals_raw = list(
        entries_qs.values("action_flag").annotate(total=Count("id")).order_by("action_flag")
    )
    action_totals_map = {row["action_flag"]: row["total"] for row in action_totals_raw}
    action_totals = []
    for flag in (ADDITION, CHANGE, DELETION):
        meta = _staff_action_meta(flag)
        action_totals.append(
            {
                "flag": flag,
                "label": meta["label"],
                "css": meta["css"],
                "total": int(action_totals_map.get(flag, 0) or 0),
            }
        )

    model_totals_raw = list(
        entries_qs.exclude(content_type__isnull=True)
        .values(
            "content_type_id",
            "content_type__app_label",
            "content_type__model",
        )
        .annotate(total=Count("id"))
        .order_by("-total", "content_type__model")[:80]
    )
    model_totals = []
    for row in model_totals_raw:
        # ContentType "name" isn't a DB field in modern Django; build a readable label from the model slug.
        label = capfirst((row.get("content_type__model") or "").replace("_", " "))
        if label:
            model_totals.append(
                {
                    "content_type_id": row.get("content_type_id"),
                    "label": label,
                    "app_label": row.get("content_type__app_label") or "",
                    "model": row.get("content_type__model") or "",
                    "total": row.get("total") or 0,
                }
            )

    paginator = Paginator(entries_qs, per_page)
    page_obj = paginator.get_page(page)
    total_pages = paginator.num_pages or 1

    entries = []
    for entry in page_obj.object_list:
        user = entry.user
        user_name = (
            user.get_full_name() or user.username or user.email or f"User {user.pk}"
        )
        user_email = user.email or ""

        meta = _staff_action_meta(entry.action_flag)
        model_label = capfirst(entry.content_type.name) if entry.content_type else "System"
        object_label = entry.object_repr or "—"
        message = entry.get_change_message() or "—"

        object_url = None
        if entry.content_type and entry.object_id and entry.action_flag != DELETION:
            try:
                object_url = reverse(
                    f"admin:{entry.content_type.app_label}_{entry.content_type.model}_change",
                    args=[entry.object_id],
                )
            except NoReverseMatch:
                object_url = None

        entries.append(
            {
                "user_name": user_name.strip(),
                "user_email": user_email,
                "action_label": meta["label"],
                "action_class": meta["css"],
                "model_label": model_label,
                "object_repr": object_label,
                "object_url": object_url,
                "message": message,
                "action_time": entry.action_time,
            }
        )

    return {
        "window_days": window_days,
        "start_date": start_date,
        "end_date": end_date,
        "per_page": per_page,
        "page": page_obj.number,
        "total_pages": total_pages,
        "total_count": paginator.count,
        "has_next": page_obj.has_next(),
        "has_previous": page_obj.has_previous(),
        "next_page": page_obj.next_page_number() if page_obj.has_next() else None,
        "prev_page": page_obj.previous_page_number() if page_obj.has_previous() else None,
        "entries": entries,
        "totals_by_user": totals_by_user,
        "action_totals": action_totals,
        "model_totals": model_totals,
        "filters": {
            "user_id": int(user_id) if user_id else None,
            "action_flag": int(action_flag) if action_flag else None,
            "content_type_id": int(content_type_id) if content_type_id else None,
            "query": query,
        },
    }
