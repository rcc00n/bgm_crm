import logging
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

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
    brand = getattr(settings, "SITE_BRAND_NAME", "Bad Guy Motors")
    code = (signup.welcome_code or "").strip()
    links = _link_bundle()

    subject = f"{brand} follow-up: your 5% code"
    text_lines = [
        f"Hi there,",
        "Quick customer note: \"The install was clean and the team kept me updated the whole time.\"",
        f"Your welcome code is still ready: {code}",
        "Use it on any product or service invoice.",
        "",
        f"Best sellers: {links['best_sellers']}",
        f"Services: {links['services']}",
        f"Booking: {links['booking']}",
        "",
        "Questions? Reply to this email and we will help.",
    ]

    html_body = build_email_html(
        title="Your welcome code is still ready",
        preheader=f"Customer note + your 5% code: {code}",
        greeting="Hi there,",
        intro_lines=[
            f"Your welcome code is still active: {code}.",
            "Use it on any product or service invoice.",
        ],
        notice_title="Customer note",
        notice_lines=[
            "\"The install was clean and the team kept me updated the whole time.\""
        ],
        summary_rows=[
            ("Welcome code", code),
            ("Discount", "5% off"),
        ],
        link_rows=[
            ("Best sellers", links["best_sellers"]),
            ("Services", links["services"]),
            ("Booking", links["booking"]),
        ],
        cta_label="Shop best sellers",
        cta_url=links["best_sellers"],
        footer_lines=["Questions? Reply to this email and we will help."],
    )
    return subject, "\n".join(text_lines), html_body


def _build_followup_3(signup: SiteNoticeSignup) -> tuple[str, str, str]:
    brand = getattr(settings, "SITE_BRAND_NAME", "Bad Guy Motors")
    links = _link_bundle()

    subject = f"{brand} - want a quote or want to book in?"
    text_lines = [
        "Want a quote or want to book in?",
        f"Book now: {links['booking']}",
        f"Browse services: {links['services']}",
        "",
        "Questions? Reply to this email and we will help.",
    ]

    html_body = build_email_html(
        title="Want a quote or want to book in?",
        preheader="Ready when you are - book or browse services.",
        greeting="Hi there,",
        intro_lines=[
            "We can price it out fast or lock in a time that works for you.",
            "Pick a service or jump straight to booking.",
        ],
        link_rows=[
            ("Book now", links["booking"]),
            ("Browse services", links["services"]),
        ],
        cta_label="Book a service",
        cta_url=links["booking"],
        footer_lines=["Questions? Reply to this email and we will help."],
    )
    return subject, "\n".join(text_lines), html_body


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
