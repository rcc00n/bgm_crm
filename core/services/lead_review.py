from __future__ import annotations

import html
import logging
from urllib.parse import urljoin

from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from core.models import LeadReviewCase

logger = logging.getLogger(__name__)
_ENTITY_ADMIN_NAMES = {
    "fitment_request": "admin:store_customfitmentrequest_change",
    "service_lead": "admin:core_servicelead_change",
    "lead": "admin:core_lead_change",
}


def review_case_for(entity_type, entity_id):
    return LeadReviewCase.objects.filter(entity_type=entity_type, entity_id=str(entity_id)).first()


def register_lead_review(entity_type, entity_id, assessment=None, evaluation=None):
    if entity_type not in _ENTITY_ADMIN_NAMES:
        raise ValueError("Unsupported lead review entity type")
    reasons = list(getattr(assessment, "reasons", []) or [])
    reasons += list(getattr(evaluation, "reasons", []) or [])
    reasons = list(dict.fromkeys(str(reason)[:128] for reason in reasons))[:25]
    if not reasons:
        reasons = ["staff_review"]
    with transaction.atomic():
        case, created = LeadReviewCase.objects.get_or_create(
            entity_type=entity_type, entity_id=str(entity_id),
            defaults={
                "reasons": reasons,
                "known_campaign": bool(getattr(assessment, "known_campaign", False)),
                "fingerprint": str(getattr(assessment, "fingerprint", "") or "")[:64],
            },
        )
        if not created:
            case = LeadReviewCase.objects.select_for_update().get(pk=case.pk)
            case.reasons = list(dict.fromkeys(case.reasons + reasons))[:25]
            case.known_campaign = case.known_campaign or bool(getattr(assessment, "known_campaign", False))
            case.save(update_fields=["reasons", "known_campaign", "updated_at"])
    return case


def entity_admin_url(case):
    return reverse(_ENTITY_ADMIN_NAMES[case.entity_type], args=[case.entity_id])


def notify_review_case(case):
    """Fallback alert with a trusted admin link and no customer-supplied URLs."""
    from notifications.services import send_telegram_message

    base = str(getattr(settings, "COMPANY_WEBSITE", "badguymotors.com") or "badguymotors.com")
    if not base.startswith(("https://", "http://")):
        base = "https://" + base
    url = urljoin(base, reverse("admin:core_leadreviewcase_change", args=[case.pk]))
    label = html.escape(case.get_entity_type_display())
    reason = "Known phishing campaign indicators" if case.known_campaign else "Submission needs staff review"
    message = (
        "<b>Saved inquiry awaiting review</b>\n"
        f"Type: {label}\n"
        f"Reference: #{html.escape(case.entity_id)}\n"
        f"Reason: {reason}\n"
        f'<a href="{html.escape(url, quote=True)}">Review saved inquiry</a>'
    )
    return send_telegram_message(
        message, event_type="lead_review", entity_type="lead_review_case",
        entity_id=str(case.pk), dedupe_key=f"lead-review:{case.pk}",
    )


def release_lead_review(case):
    """Release one inquiry once, retaining a retryable case after any failure."""
    from core.services import shop_sync
    from notifications import services

    handlers = {
        "fitment_request": (shop_sync.sync_fitment_request_to_shop, services.notify_about_fitment_request),
        "service_lead": (shop_sync.sync_service_lead_to_shop, services.notify_about_service_lead),
        "lead": (shop_sync.sync_qualify_lead_to_shop, services.notify_about_lead),
    }
    release_recorded = False
    try:
        with transaction.atomic():
            locked = LeadReviewCase.objects.select_for_update().get(pk=case.pk)
            if locked.status == LeadReviewCase.Status.RELEASED:
                return False
            sync_func, notify_func = handlers[locked.entity_type]
            if locked.shop_synced_at is None:
                # These sync functions only write the same DB. Unlike the
                # fire-and-forget queue helper, failures roll back the release.
                sync_func(int(locked.entity_id))
                locked.shop_synced_at = timezone.now()
            locked.status = LeadReviewCase.Status.RELEASED
            locked.reviewed_at = timezone.now()
            locked.last_error = ""
            locked.save(update_fields=["shop_synced_at", "status", "reviewed_at", "last_error", "updated_at"])
            release_recorded = True
        # Notification helpers use stable entity-based delivery deduplication.
        notify_func(int(locked.entity_id))
    except Exception as exc:
        retry_case = LeadReviewCase.objects.filter(pk=case.pk)
        if release_recorded:
            retry_case = retry_case.filter(status=LeadReviewCase.Status.RELEASED, reviewed_at=locked.reviewed_at)
        else:
            # A concurrent successful release must not be overwritten after a
            # failed sync transaction has already rolled back its row lock.
            retry_case = retry_case.exclude(status=LeadReviewCase.Status.RELEASED)
        retry_case.update(
            status=LeadReviewCase.Status.PENDING, last_error=type(exc).__name__, updated_at=timezone.now(),
        )
        logger.warning("Lead review release failed for case %s (%s)", case.pk, type(exc).__name__)
        raise
    case.refresh_from_db()
    return True


def mark_lead_review_spam(case):
    """Preserve the source inquiry and make the staff decision reversible."""
    updated = LeadReviewCase.objects.filter(pk=case.pk).exclude(status=LeadReviewCase.Status.RELEASED).update(
        status=LeadReviewCase.Status.SPAM, reviewed_at=timezone.now(), updated_at=timezone.now(),
    )
    case.refresh_from_db()
    return bool(updated)
