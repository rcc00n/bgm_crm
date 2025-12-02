from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Optional

from django.db.models import Avg, Count
from django.db.models.functions import TruncDate
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
