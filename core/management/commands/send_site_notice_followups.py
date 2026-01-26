import logging
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.email_templates import base_email_context, email_brand_name, join_text_sections, render_email_template
from core.emails import build_email_html, send_html_email
from core.models import SiteNoticeSignup

logger = logging.getLogger(__name__)


def _base_url() -> str:
    base = (getattr(settings, "COMPANY_WEBSITE", "") or "").strip()
    if not base:
        return ""
    if not base.startswith(("http://", "https://")):
        base = f"https://{base}"
    return base.rstrip("/")


def _resolve_url(setting_name: str, fallback_path: str) -> str:
    base = _base_url()
    raw = (getattr(settings, setting_name, "") or "").strip()
    if raw:
        if raw.startswith(("http://", "https://")):
            return raw
        if base:
            return f"{base}/{raw.lstrip('/')}"
        return raw
    if fallback_path.startswith(("http://", "https://")):
        return fallback_path
    if base:
        return f"{base}/{fallback_path.lstrip('/')}"
    return fallback_path


def _link_bundle() -> dict[str, str]:
    return {
        "best_sellers": _resolve_url("SITE_NOTICE_BEST_SELLERS_URL", "/store/"),
        "services": _resolve_url("SITE_NOTICE_SERVICES_URL", "/accounts/#services"),
        "booking": _resolve_url("SITE_NOTICE_BOOKING_URL", "/accounts/#services"),
    }


def _sender() -> str:
    return (
        getattr(settings, "DEFAULT_FROM_EMAIL", None)
        or getattr(settings, "SUPPORT_EMAIL", None)
        or ""
    )


def _send_email(recipient: str, *, subject: str, text_body: str, html_body: str) -> bool:
    sender = _sender()
    if not sender:
        logger.warning("Missing DEFAULT_FROM_EMAIL/SUPPORT_EMAIL for site notice followups.")
        return False
    if not recipient:
        return False
    try:
        send_html_email(
            subject=subject,
            text_body=text_body,
            html_body=html_body,
            from_email=sender,
            recipient_list=[recipient],
        )
    except Exception:
        logger.exception("Failed to send site notice followup to %s", recipient)
        return False
    return True


def _build_followup_2(signup: SiteNoticeSignup) -> tuple[str, str, str]:
    brand = email_brand_name()
    code = (signup.welcome_code or "").strip()
    links = _link_bundle()

    context = base_email_context(
        {
            "brand": brand,
            "welcome_code": code,
            "best_sellers_url": links["best_sellers"],
            "services_url": links["services"],
            "booking_url": links["booking"],
        }
    )
    template = render_email_template("site_notice_followup_2", context)
    notice_text_lines = []
    if template.notice_lines:
        if template.notice_title:
            notice_text_lines = [f"{template.notice_title}: {line}" for line in template.notice_lines]
        else:
            notice_text_lines = list(template.notice_lines)
    summary_lines = [f"Welcome code: {code}", "Discount: 5% off"]
    link_lines = [
        f"Best sellers: {links['best_sellers']}",
        f"Services: {links['services']}",
        f"Booking: {links['booking']}",
    ]
    text_body = join_text_sections(
        [template.greeting],
        template.intro_lines,
        notice_text_lines,
        summary_lines,
        link_lines,
        template.footer_lines,
    )

    html_body = build_email_html(
        title=template.title,
        preheader=template.preheader,
        greeting=template.greeting,
        intro_lines=template.intro_lines,
        notice_title=template.notice_title or None,
        notice_lines=template.notice_lines,
        summary_rows=[
            ("Welcome code", code),
            ("Discount", "5% off"),
        ],
        link_rows=[
            ("Best sellers", links["best_sellers"]),
            ("Services", links["services"]),
            ("Booking", links["booking"]),
        ],
        cta_label=template.cta_label,
        cta_url=links["best_sellers"],
        footer_lines=template.footer_lines,
    )
    return template.subject, text_body, html_body


def _build_followup_3(signup: SiteNoticeSignup) -> tuple[str, str, str]:
    brand = email_brand_name()
    links = _link_bundle()

    context = base_email_context(
        {
            "brand": brand,
            "services_url": links["services"],
            "booking_url": links["booking"],
        }
    )
    template = render_email_template("site_notice_followup_3", context)
    link_lines = [
        f"Book now: {links['booking']}",
        f"Browse services: {links['services']}",
    ]
    text_body = join_text_sections(
        [template.greeting],
        template.intro_lines,
        link_lines,
        template.footer_lines,
    )

    html_body = build_email_html(
        title=template.title,
        preheader=template.preheader,
        greeting=template.greeting,
        intro_lines=template.intro_lines,
        link_rows=[
            ("Book now", links["booking"]),
            ("Browse services", links["services"]),
        ],
        notice_title=template.notice_title or None,
        notice_lines=template.notice_lines,
        cta_label=template.cta_label,
        cta_url=links["booking"],
        footer_lines=template.footer_lines,
    )
    return template.subject, text_body, html_body


class Command(BaseCommand):
    help = "Send follow-up emails for site notice signups."

    def handle(self, *args, **options):
        now = timezone.now()
        cutoff_2 = now - timedelta(hours=24)
        cutoff_3 = now - timedelta(days=3)

        followup_2 = SiteNoticeSignup.objects.filter(
            welcome_sent_at__lte=cutoff_2,
            followup_2_sent_at__isnull=True,
        ).order_by("welcome_sent_at")

        followup_3 = SiteNoticeSignup.objects.filter(
            welcome_sent_at__lte=cutoff_3,
            followup_3_sent_at__isnull=True,
            followup_2_sent_at__isnull=False,
        ).order_by("welcome_sent_at")

        sent_2 = 0
        sent_3 = 0

        for signup in followup_2:
            subject, text_body, html_body = _build_followup_2(signup)
            if _send_email(signup.email, subject=subject, text_body=text_body, html_body=html_body):
                signup.followup_2_sent_at = now
                signup.save(update_fields=["followup_2_sent_at"])
                sent_2 += 1

        for signup in followup_3:
            subject, text_body, html_body = _build_followup_3(signup)
            if _send_email(signup.email, subject=subject, text_body=text_body, html_body=html_body):
                signup.followup_3_sent_at = now
                signup.save(update_fields=["followup_3_sent_at"])
                sent_3 += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Site notice followups sent: {sent_2} (24h), {sent_3} (3d)."
            )
        )
