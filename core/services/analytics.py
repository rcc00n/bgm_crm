from __future__ import annotations

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
