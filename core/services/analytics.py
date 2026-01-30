from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from django.contrib.auth import get_user_model
from django.conf import settings
from django.db.models import Avg, Case, Count, IntegerField, Max, Q, Sum, When
from django.db.models.functions import TruncDate
from django.urls import reverse
from django.utils import timezone

from core.models import PageView, VisitorSession


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
    if seconds <= 0:
        return "0m"
    if seconds < 60:
        return "<1m"
    minutes, _ = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minutes}m" if minutes else f"{hours}h"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h" if hours else f"{days}d"


def summarize_web_analytics(window_days: int = 7) -> Dict[str, object]:
    window_days = max(1, min(window_days, 31))
    day_list = _day_range(window_days)
    start_date = day_list[0]
    start_dt = timezone.make_aware(datetime.combine(start_date, datetime.min.time()))

    recent_views = PageView.objects.filter(started_at__gte=start_dt)
    session_ids = recent_views.values_list("session_id", flat=True).distinct()
    recent_sessions = VisitorSession.objects.filter(id__in=session_ids)

    visits = recent_sessions.count()
    signed_in = recent_sessions.filter(user__isnull=False).count()
    total_page_views = recent_views.count()

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
            "signed_in": signed_in,
            "signed_in_pct": signed_in_pct,
            "avg_duration_seconds": avg_duration_seconds,
            "avg_pages_per_visit": avg_pages_per_visit,
            "page_views": total_page_views,
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
        if ip_address:
            ip_entry = ip_stats.setdefault(
                ip_address,
                {"visits": 0, "signed_in": 0, "last_seen": None},
            )
            ip_entry["visits"] += 1
            if session.get("user_id"):
                ip_entry["signed_in"] += 1
            last_seen = session.get("last_seen_at")
            if last_seen and (not ip_entry["last_seen"] or last_seen > ip_entry["last_seen"]):
                ip_entry["last_seen"] = last_seen

        session_leaders.append(
            {
                "session_id": str(session_id),
                "user_name": session.get("user_name_snapshot") or "Guest",
                "user_email": session.get("user_email_snapshot") or "",
                "ip_address": ip_address or "",
                "landing_path": landing_path,
                "views": views_count,
                "total_seconds": round(total_ms / 1000, 1),
                "last_seen": session.get("last_seen_at"),
            }
        )

    signed_in_pct = round((signed_in / visits) * 100, 1) if visits else 0.0
    returning_sessions = max(0, visits - new_sessions)
    returning_pct = round((returning_sessions / visits) * 100, 1) if visits else 0.0

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
            "page_views": page_views,
            "signed_in": signed_in,
            "signed_in_pct": signed_in_pct,
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
    start_dt = timezone.make_aware(datetime.combine(start_date, datetime.min.time()))

    admin_filter = Q(pk__isnull=True)
    admin_prefixes = []
    try:
        admin_prefixes.append(reverse("admin:index"))
    except Exception:
        admin_prefixes = []
    configured_prefixes = getattr(settings, "ADMIN_USAGE_PATH_PREFIXES", None) or []
    for prefix in configured_prefixes:
        if prefix:
            admin_prefixes.append(prefix)
    admin_prefixes.extend(["/admin/", "/admin"])
    normalized_prefixes = []
    for prefix in admin_prefixes:
        if not prefix:
            continue
        if not prefix.startswith("/"):
            prefix = f"/{prefix}"
        normalized_prefixes.append(prefix)

    for prefix in dict.fromkeys(normalized_prefixes):
        admin_filter |= (
            Q(path__startswith=prefix)
            | Q(path__contains=prefix)
            | Q(full_path__startswith=prefix)
            | Q(full_path__contains=prefix)
        )
    client_filter = ~Q(path__startswith="/admin")

    base_views = PageView.objects.filter(
        started_at__gte=start_dt,
        user__isnull=False,
        user__is_staff=True,
    )

    aggregates = base_views.values("user_id").annotate(
        admin_duration_ms=Sum(
            Case(When(admin_filter, then="duration_ms"), default=0, output_field=IntegerField())
        ),
        client_duration_ms=Sum(
            Case(When(client_filter, then="duration_ms"), default=0, output_field=IntegerField())
        ),
        admin_views=Count("id", filter=admin_filter),
        client_views=Count("id", filter=client_filter),
        total_views=Count("id"),
        last_seen=Max("updated_at"),
    )
    by_user = {row["user_id"]: row for row in aggregates}

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
        data = by_user.get(user.id, {})
        admin_ms = int(data.get("admin_duration_ms") or 0)
        client_ms = int(data.get("client_duration_ms") or 0)
        admin_views = int(data.get("admin_views") or 0)
        client_views = int(data.get("client_views") or 0)
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
                "last_seen": data.get("last_seen"),
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
