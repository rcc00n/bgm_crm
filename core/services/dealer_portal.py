from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import List, Optional

from django.utils import timezone

from core.models import DealerApplication, DealerTier, DealerTierLevel
from store.models import Order

OPEN_ORDER_STATUSES = {Order.STATUS_PROCESSING, Order.STATUS_SHIPPED}
MONEY_QUANT = Decimal("0.01")


def _to_decimal(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0.00")


def _ordered_tiers() -> List[DealerTierLevel]:
    try:
        return list(
            DealerTierLevel.objects.filter(is_active=True).order_by("minimum_spend", "sort_order", "code")
        )
    except Exception:
        return []


def _application_timeline(application: Optional[DealerApplication], profile) -> list[dict]:
    """
    Returns a deterministic lifecycle timeline for the template.
    """
    steps = [
        {
            "label": "Application started",
            "state": bool(application),
            "timestamp": getattr(application, "created_at", None),
        },
        {
            "label": "Under review",
            "state": bool(application and application.status in {application.Status.PENDING, application.Status.APPROVED, application.Status.REJECTED}),
            "timestamp": getattr(application, "created_at", None),
        },
        {
            "label": "Decision posted",
            "state": bool(application and application.status in {application.Status.APPROVED, application.Status.REJECTED}),
            "timestamp": getattr(application, "reviewed_at", None),
            "details": getattr(application, "get_status_display", lambda: "—")(),
        },
        {
            "label": "Dealer portal live",
            "state": bool(profile and profile.is_dealer),
            "timestamp": getattr(profile, "dealer_since", None),
        },
    ]
    return steps


def _orders_snapshot(user) -> dict:
    base = {"total": 0, "open": 0, "completed": 0, "latest": None}
    if not user.is_authenticated:
        return base
    qs = Order.objects.filter(user=user).order_by("-id")
    base["total"] = qs.count()
    base["open"] = qs.filter(status__in=OPEN_ORDER_STATUSES).count()
    # Completed is the remainder once open orders are excluded; clamp at 0 to
    # protect against inconsistent data.
    base["completed"] = max(base["total"] - base["open"], 0)
    base["latest"] = qs.first()
    return base


def _next_tier(current_code: str, tiers: List[DealerTierLevel]):
    if not tiers:
        return None, None
    lookup = {t.code: idx for idx, t in enumerate(tiers)}
    idx = lookup.get(current_code)
    if idx is None:
        idx = lookup.get(DealerTier.NONE)
    current = tiers[idx] if idx is not None else None
    next_idx = (idx + 1) if idx is not None else 0
    if next_idx >= len(tiers):
        return current, None
    return current, tiers[next_idx]


def build_portal_snapshot(user):
    """
    Collects everything the dealer portal template needs:
    - profile/tier details
    - application timeline
    - spend progress
    - order summary
    """
    profile = getattr(user, "userprofile", None)
    application = getattr(user, "dealer_application", None)
    tiers = _ordered_tiers()
    tier_map = {t.code: t for t in tiers}

    if profile:
        lifetime_spent = _to_decimal(profile.total_spent_cad()).quantize(MONEY_QUANT)
        tier_code = profile.dealer_tier
        tier_level = tier_map.get(tier_code) or profile.get_dealer_tier_level()
    else:
        lifetime_spent = Decimal("0.00")
        tier_code = DealerTier.NONE
        tier_level = tier_map.get(DealerTier.NONE)

    current, upcoming = _next_tier(tier_code, tiers)
    current_threshold = Decimal(str(getattr(current, "minimum_spend", 0)))
    if current_threshold < 0:
        current_threshold = Decimal("0")

    progress = 100
    remaining = None
    if upcoming:
        next_threshold = Decimal(str(upcoming.minimum_spend))
        denom = max(Decimal("1.00"), next_threshold - current_threshold)
        progress = int(
            max(
                0,
                min(
                    100,
                    ((lifetime_spent - current_threshold) / denom * 100).quantize(Decimal("1")),
                ),
            )
        )
        remaining = max(Decimal("0.00"), next_threshold - lifetime_spent)
    else:
        progress = 100

    snapshot = {
        "profile": profile,
        "application": application,
        "timeline": _application_timeline(application, profile),
        "orders": _orders_snapshot(user),
        "lifetime_spent": lifetime_spent,
        "tier": tier_level,
        "tier_code": tier_code,
        "tier_label": tier_level.label if tier_level else (profile.get_dealer_tier_display() if profile else "Standard"),
        "discount_percent": getattr(tier_level, "discount_percent", 0),
        "current_threshold": current_threshold,
        "progress": progress,
        "next_tier": upcoming,
        "remaining_to_next": remaining,
        "tiers": tiers,
        "is_dealer": bool(profile and profile.is_dealer),
    }
    return snapshot
