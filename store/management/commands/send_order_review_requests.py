import logging
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.email_templates import base_email_context, join_text_sections, render_email_template
from core.emails import build_email_html, send_html_email
from store.models import Order

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


def _sender() -> str:
    return (
        getattr(settings, "DEFAULT_FROM_EMAIL", None)
        or getattr(settings, "SUPPORT_EMAIL", None)
        or ""
    )


class Command(BaseCommand):
    help = "Send review request emails for completed store orders."

    def handle(self, *args, **options):
        sender = _sender()
        if not sender:
            self.stdout.write(self.style.WARNING("Missing DEFAULT_FROM_EMAIL/SUPPORT_EMAIL."))
            return

        delay_days = int(getattr(settings, "ORDER_REVIEW_REQUEST_DELAY_DAYS", 5))
        cutoff = timezone.now() - timedelta(days=delay_days)
        review_url = _resolve_url("ORDER_REVIEW_URL", "/")
        store_url = _resolve_url("ABANDONED_CART_STORE_URL", "/store/")

        qs = Order.objects.filter(
            status=Order.STATUS_COMPLETED,
            completed_at__isnull=False,
            review_request_sent_at__isnull=True,
            completed_at__lte=cutoff,
        ).order_by("completed_at")

        sent = 0
        for order in qs:
            recipient = (order.email or "").strip()
            if not recipient:
                continue
            brand = getattr(settings, "SITE_BRAND_NAME", "BGM Customs")
            context = base_email_context(
                {
                    "brand": brand,
                    "customer_name": order.customer_name,
                    "order_id": order.pk,
                    "review_url": review_url,
                    "store_url": store_url,
                }
            )
            template = render_email_template("order_review_request", context)
            link_lines = [
                f"Leave a review: {review_url}",
                f"Shop store: {store_url}",
            ]
            text_body = join_text_sections(
                [template.greeting],
                template.intro_lines,
                link_lines,
                template.footer_lines,
            )

            try:
                html_body = build_email_html(
                    title=template.title,
                    preheader=template.preheader,
                    greeting=template.greeting,
                    intro_lines=template.intro_lines,
                    detail_rows=[
                        ("Order #", order.pk),
                        ("Status", order.get_status_display()),
                    ],
                    link_rows=[
                        ("Leave a review", review_url),
                        ("Shop store", store_url),
                    ],
                    notice_title=template.notice_title or None,
                    notice_lines=template.notice_lines,
                    cta_label=template.cta_label,
                    cta_url=review_url,
                    footer_lines=template.footer_lines,
                )
                send_html_email(
                    subject=template.subject,
                    text_body=text_body,
                    html_body=html_body,
                    from_email=sender,
                    recipient_list=[recipient],
                )
            except Exception:
                logger.exception("Failed to send review request for order %s", order.pk)
                continue

            order.review_request_sent_at = timezone.now()
            order.save(update_fields=["review_request_sent_at"])
            sent += 1

        self.stdout.write(self.style.SUCCESS(f"Review requests sent: {sent}."))
