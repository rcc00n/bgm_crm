from __future__ import annotations

import logging

from django.conf import settings
from django.urls import reverse

from core.email_templates import (
    base_email_context,
    email_brand_name,
    email_company_website,
    join_text_sections,
    render_email_template,
)
from core.emails import build_email_html, send_html_email

logger = logging.getLogger(__name__)


def _resolve_sender() -> str:
    return (
        (getattr(settings, "DEFAULT_FROM_EMAIL", None) or "").strip()
        or (getattr(settings, "SUPPORT_EMAIL", None) or "").strip()
    )


def _absolute_url(path: str) -> str:
    base = (email_company_website() or "").strip() or (getattr(settings, "COMPANY_WEBSITE", "") or "").strip()
    if not base:
        return path or ""
    if not base.startswith("http://") and not base.startswith("https://"):
        base = f"https://{base}"
    return f"{base.rstrip('/')}{path}"


def _application_recipient(app) -> str:
    recipient = (getattr(app, "email", "") or "").strip()
    if not recipient and getattr(app, "user", None):
        recipient = (getattr(app.user, "email", "") or "").strip()
    return recipient


def send_dealer_application_submitted(application_id) -> bool:
    from core.models import DealerApplication

    app = DealerApplication.objects.select_related("user").get(pk=application_id)
    recipient = _application_recipient(app)
    if not recipient:
        return False

    sender = _resolve_sender()
    if not sender:
        logger.warning("Missing DEFAULT_FROM_EMAIL/SUPPORT_EMAIL; skipping dealer application email.")
        return False

    user = app.user
    name = (user.get_full_name() or user.username or "there").strip() or "there"
    dealer_status_url = _absolute_url(reverse("dealer-status"))

    context = base_email_context(
        {
            "brand": email_brand_name(),
            "applicant_name": name,
            "business_name": app.business_name,
            "preferred_tier": app.get_preferred_tier_display() or app.preferred_tier,
            "dealer_status_url": dealer_status_url,
        }
    )
    template = render_email_template("dealer_application_submitted", context)

    text_body = join_text_sections(
        [template.greeting],
        template.intro_lines,
        [f"View your application status: {dealer_status_url}"] if dealer_status_url else [],
        template.footer_lines,
    )

    try:
        html_body = build_email_html(
            title=template.title,
            preheader=template.preheader,
            greeting=template.greeting,
            intro_lines=template.intro_lines,
            detail_rows=[
                ("Business", app.business_name),
                ("Projected tier", app.get_preferred_tier_display() or app.preferred_tier),
            ],
            footer_lines=template.footer_lines,
            cta_label=template.cta_label,
            cta_url=template.cta_url or dealer_status_url,
        )
        send_html_email(
            subject=template.subject,
            text_body=text_body,
            html_body=html_body,
            from_email=sender,
            recipient_list=[recipient],
            email_type="dealer_application_submitted",
        )
    except Exception:
        logger.exception("Failed to send dealer application submitted email for %s", application_id)
        return False
    return True


def send_dealer_application_approved(application_id) -> bool:
    from core.models import DealerApplication

    app = DealerApplication.objects.select_related("user").get(pk=application_id)
    recipient = _application_recipient(app)
    if not recipient:
        return False

    sender = _resolve_sender()
    if not sender:
        logger.warning("Missing DEFAULT_FROM_EMAIL/SUPPORT_EMAIL; skipping dealer application email.")
        return False

    user = app.user
    name = (user.get_full_name() or user.username or "there").strip() or "there"
    dealer_portal_url = _absolute_url(reverse("dealer-status"))
    tier = app.get_assigned_tier_display() or app.get_preferred_tier_display() or app.resolved_tier()

    context = base_email_context(
        {
            "brand": email_brand_name(),
            "applicant_name": name,
            "business_name": app.business_name,
            "assigned_tier": tier,
            "dealer_portal_url": dealer_portal_url,
        }
    )
    template = render_email_template("dealer_application_approved", context)

    text_body = join_text_sections(
        [template.greeting],
        template.intro_lines,
        [f"Open dealer portal: {dealer_portal_url}"] if dealer_portal_url else [],
        template.footer_lines,
    )

    try:
        html_body = build_email_html(
            title=template.title,
            preheader=template.preheader,
            greeting=template.greeting,
            intro_lines=template.intro_lines,
            detail_rows=[
                ("Business", app.business_name),
                ("Tier", tier),
            ],
            footer_lines=template.footer_lines,
            cta_label=template.cta_label,
            cta_url=template.cta_url or dealer_portal_url,
        )
        send_html_email(
            subject=template.subject,
            text_body=text_body,
            html_body=html_body,
            from_email=sender,
            recipient_list=[recipient],
            email_type="dealer_application_approved",
        )
    except Exception:
        logger.exception("Failed to send dealer application approved email for %s", application_id)
        return False
    return True


def send_dealer_application_rejected(application_id) -> bool:
    from core.models import DealerApplication

    app = DealerApplication.objects.select_related("user").get(pk=application_id)
    recipient = _application_recipient(app)
    if not recipient:
        return False

    sender = _resolve_sender()
    if not sender:
        logger.warning("Missing DEFAULT_FROM_EMAIL/SUPPORT_EMAIL; skipping dealer application email.")
        return False

    user = app.user
    name = (user.get_full_name() or user.username or "there").strip() or "there"
    dealer_status_url = _absolute_url(reverse("dealer-status"))

    context = base_email_context(
        {
            "brand": email_brand_name(),
            "applicant_name": name,
            "business_name": app.business_name,
            "dealer_status_url": dealer_status_url,
        }
    )
    template = render_email_template("dealer_application_rejected", context)

    text_body = join_text_sections(
        [template.greeting],
        template.intro_lines,
        [f"View your application status: {dealer_status_url}"] if dealer_status_url else [],
        template.footer_lines,
    )

    try:
        html_body = build_email_html(
            title=template.title,
            preheader=template.preheader,
            greeting=template.greeting,
            intro_lines=template.intro_lines,
            detail_rows=[("Business", app.business_name)],
            footer_lines=template.footer_lines,
            cta_label=template.cta_label,
            cta_url=template.cta_url or dealer_status_url,
        )
        send_html_email(
            subject=template.subject,
            text_body=text_body,
            html_body=html_body,
            from_email=sender,
            recipient_list=[recipient],
            email_type="dealer_application_rejected",
        )
    except Exception:
        logger.exception("Failed to send dealer application rejected email for %s", application_id)
        return False
    return True

