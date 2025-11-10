from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List

from django.db.models import Avg, Count
from django.db.models.functions import TruncDate
from django.utils import timezone

from core.models import PageView, VisitorSession


def _day_range(window_days: int):
    today = timezone.localdate()
    start = today - timedelta(days=window_days - 1)
    return [start + timedelta(days=offset) for offset in range(window_days)]


def summarize_web_analytics(window_days: int = 7) -> Dict[str, object]:
    window_days = max(1, min(window_days, 31))
    day_list = _day_range(window_days)
    start_date = day_list[0]
    start_dt = timezone.make_aware(datetime.combine(start_date, datetime.min.time()))

    recent_sessions = VisitorSession.objects.filter(created_at__gte=start_dt)
    recent_views = PageView.objects.filter(started_at__gte=start_dt)

    visits = recent_sessions.count()
    signed_in = recent_sessions.filter(user__isnull=False).count()
    total_page_views = recent_views.count()

    avg_duration_ms = recent_views.aggregate(avg=Avg("duration_ms"))[
        "avg"
    ] or 0
    avg_duration_seconds = round(avg_duration_ms / 1000, 1)
    avg_pages_per_visit = round(total_page_views / visits, 2) if visits else 0.0
    signed_in_pct = round((signed_in / visits) * 100, 1) if visits else 0.0

    visitor_counts = (
        recent_sessions
        .annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(count=Count("id"))
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
        recent_sessions.exclude(referrer="")
        .values("referrer")
        .annotate(visits=Count("id"))
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
        "visitor_timeseries": visitor_timeseries,
        "engagement_timeseries": engagement_timeseries,
        "recent_signed_in_sessions": signed_in_sessions,
    }
