"""
Utilities for the Telegram bot integration.
"""
from __future__ import annotations

import html
from datetime import timedelta
from decimal import Decimal
from typing import Sequence

from django.conf import settings
from django.core.cache import cache
from django.db.models import (
    DecimalField,
    ExpressionWrapper,
    F,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.timezone import localtime
from telebot import TeleBot
from telebot.apihelper import ApiTelegramException

from core.emails import build_email_html, send_html_email
from core.email_templates import join_text_sections

from .models import (
    TelegramBotSettings,
    TelegramMessageLog,
    TelegramReminder,
)


class TelegramConfigurationError(Exception):
    """Raised when Telegram bot actions are requested without valid settings."""


# Lead digests are limited to 3pm and 9pm local time to avoid spam.
LEAD_DIGEST_HOURS_LOCAL = (15, 21)
LEAD_DIGEST_CACHE_TTL = 60 * 60 * 48


def build_bot(settings_obj: TelegramBotSettings | None = None) -> tuple[TeleBot, TelegramBotSettings]:
    settings_obj = settings_obj or TelegramBotSettings.load_active()
    if not settings_obj:
        raise TelegramConfigurationError("Telegram bot is not configured or disabled.")
    bot = TeleBot(settings_obj.bot_token, parse_mode="HTML", threaded=False)
    return bot, settings_obj


def send_telegram_message(
    message: str,
    *,
    event_type: str,
    chat_ids: Sequence[int] | None = None,
) -> int:
    """
    Sends a Telegram message and persists the send result.
    """
    try:
        bot, settings_obj = build_bot()
    except TelegramConfigurationError:
        return 0

    recipients = list(chat_ids or settings_obj.chat_id_list)
    if not recipients:
        return 0

    delivered = 0
    for chat_id in recipients:
        success = True
        error_text = ""
        try:
            bot.send_message(chat_id, message, disable_web_page_preview=True)
            delivered += 1
        except ApiTelegramException as exc:
            success = False
            error_text = f"{exc.__class__.__name__}: {exc}"
        except Exception as exc:
            success = False
            error_text = f"{exc.__class__.__name__}: {exc}"

        TelegramMessageLog.objects.create(
            chat_id=chat_id,
            event_type=event_type,
            payload=message,
            success=success,
            error_message=error_text[:500],
        )
    return delivered


ROLE_NOTIFICATION_FIELDS = {
    TelegramMessageLog.EVENT_APPOINTMENT_CREATED: "notify_on_new_appointment",
    TelegramMessageLog.EVENT_ORDER_CREATED: "notify_on_new_order",
    TelegramMessageLog.EVENT_SERVICE_LEAD: "notify_on_service_lead",
    TelegramMessageLog.EVENT_FITMENT_REQUEST: "notify_on_fitment_request",
    TelegramMessageLog.EVENT_SITE_NOTICE_WELCOME: "notify_on_site_notice_signup",
    TelegramMessageLog.EVENT_ORDER_REVIEW_REQUEST: "notify_on_order_review_request",
}


def _staff_recipients_for_event(event_type: str) -> list[str]:
    field = ROLE_NOTIFICATION_FIELDS.get(event_type)
    if not field:
        return []
    from core.models import CustomUserDisplay, Role

    roles = Role.objects.filter(**{field: True})
    if not roles.exists():
        return []
    users = (
        CustomUserDisplay.objects.filter(
            is_staff=True,
            is_active=True,
            userrole__role__in=roles,
        )
        .exclude(email__isnull=True)
        .exclude(email__exact="")
        .distinct()
    )
    emails = sorted({user.email.strip().lower() for user in users if user.email})
    return emails


def send_staff_email_notification(
    *,
    event_type: str,
    subject: str,
    intro_lines: Sequence[str],
    detail_rows: Sequence[tuple[str, object]] | None = None,
    item_rows: Sequence[tuple[object, object]] | None = None,
    notice_lines: Sequence[str] | None = None,
) -> int:
    recipients = _staff_recipients_for_event(event_type)
    if not recipients:
        return 0
    sender = (
        getattr(settings, "DEFAULT_FROM_EMAIL", None)
        or getattr(settings, "SUPPORT_EMAIL", None)
    )
    if not sender:
        return 0

    greeting = "Team,"
    html_body = build_email_html(
        title=subject,
        preheader=subject,
        greeting=greeting,
        intro_lines=list(intro_lines),
        detail_rows=detail_rows,
        item_rows=item_rows,
        notice_lines=list(notice_lines or []),
        footer_lines=[],
    )
    detail_lines = []
    for label, value in detail_rows or []:
        value_text = str(value).strip() if value is not None else ""
        if not value_text:
            continue
        detail_lines.append(f"{label}: {value_text}")
    text_body = join_text_sections(
        [greeting],
        list(intro_lines),
        detail_lines,
        list(notice_lines or []),
    )

    sent = 0
    for recipient in recipients:
        try:
            send_html_email(
                subject=subject,
                text_body=text_body,
                html_body=html_body,
                from_email=sender,
                recipient_list=[recipient],
                email_type=f"staff_{event_type}",
            )
            sent += 1
        except Exception:
            pass
    return sent


def _format_digest_counts(items: dict[str, int], limit: int = 3) -> str:
    if not items:
        return ""
    ordered = sorted(items.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    return ", ".join(f"{label} ({count})" for label, count in ordered)


def _lead_digest_slot(now_local: timezone.datetime) -> timezone.datetime | None:
    for hour in sorted(LEAD_DIGEST_HOURS_LOCAL, reverse=True):
        slot_dt = now_local.replace(hour=hour, minute=0, second=0, microsecond=0)
        if now_local >= slot_dt:
            return slot_dt
    return None


def _lead_digest_slot_key(slot_dt: timezone.datetime) -> str:
    return slot_dt.strftime("%Y-%m-%d-%H")


def queue_lead_digest(
    *,
    form_type: str,
    suspicious: bool,
    ip_address: str | None = None,
    asn: str | None = None,
    interval_seconds: int = 300,
) -> None:
    """
    Aggregate noisy lead alerts and emit a compact digest at 3pm/9pm local time.
    """
    cache_key = f"tg:lead_digest:{form_type}"
    now = timezone.now()
    state = cache.get(cache_key) or {
        "started_at": now,
        "total": 0,
        "suspected": 0,
        "ips": {},
        "asns": {},
        "last_sent_slot": "",
    }

    state["total"] = int(state.get("total") or 0) + 1
    if suspicious:
        state["suspected"] = int(state.get("suspected") or 0) + 1

    ips = state.get("ips") or {}
    if ip_address and len(ips) < 25:
        ips[ip_address] = int(ips.get(ip_address, 0)) + 1
    state["ips"] = ips

    asns = state.get("asns") or {}
    if asn and len(asns) < 25:
        asns[asn] = int(asns.get(asn, 0)) + 1
    state["asns"] = asns

    started_at = state.get("started_at") or now
    if isinstance(started_at, str):
        try:
            started_at = timezone.datetime.fromisoformat(started_at)
        except Exception:
            started_at = now
    if timezone.is_naive(started_at):
        started_at = timezone.make_aware(started_at, timezone.get_default_timezone())

    slot_dt = _lead_digest_slot(localtime(now))
    slot_key = _lead_digest_slot_key(slot_dt) if slot_dt else ""
    last_sent_slot = state.get("last_sent_slot") or ""

    if slot_dt and slot_key and slot_key != last_sent_slot:
        elapsed = (now - started_at).total_seconds()
        total = int(state.get("total") or 0)
        suspected = int(state.get("suspected") or 0)
        top_ips = _format_digest_counts(state.get("ips") or {})
        top_asns = _format_digest_counts(state.get("asns") or {})

        label = "Site notice" if form_type == "site_notice" else "Service leads"
        message = (
            f"<b>Lead digest — {label}</b>\n"
            f"Window: {int(elapsed // 60)} min\n"
            f"New: {total}\n"
            f"Suspected: {suspected}\n"
        )
        if top_ips:
            message += f"Top IPs: {top_ips}\n"
        if top_asns:
            message += f"Top ASN: {top_asns}\n"

        send_telegram_message(
            message,
            event_type=TelegramMessageLog.EVENT_DIGEST,
        )
        state = {
            "started_at": now,
            "total": 0,
            "suspected": 0,
            "ips": {},
            "asns": {},
            "last_sent_slot": slot_key,
        }

    cache_timeout = max(interval_seconds * 4, LEAD_DIGEST_CACHE_TTL)
    cache.set(cache_key, state, timeout=cache_timeout)


def notify_about_appointment(appointment_id) -> int:
    settings_obj = TelegramBotSettings.load_active()
    from core.models import Appointment

    appointment = Appointment.objects.select_related(
        "service",
        "master",
        "client",
    ).get(pk=appointment_id)

    client_name = appointment.contact_name
    if not client_name and appointment.client:
        client_name = appointment.client.get_full_name() or appointment.client.username
    client_name = client_name or "Guest"

    master_name = appointment.master.get_full_name() or appointment.master.username
    service_name = appointment.service.name
    start = localtime(appointment.start_time).strftime("%Y-%m-%d %H:%M")
    message = (
        f"<b>New appointment booked</b>\n"
        f"Client: {client_name}\n"
        f"Service: {service_name}\n"
        f"Tech: {master_name}\n"
        f"When: {start}\n"
    )
    if appointment.contact_phone:
        message += f"Phone: {appointment.contact_phone}\n"
    if appointment.contact_email:
        message += f"Email: {appointment.contact_email}\n"

    detail_rows = [
        ("Client", client_name),
        ("Service", service_name),
        ("Tech", master_name),
        ("When", start),
    ]
    if appointment.contact_phone:
        detail_rows.append(("Phone", appointment.contact_phone))
    if appointment.contact_email:
        detail_rows.append(("Email", appointment.contact_email))

    send_staff_email_notification(
        event_type=TelegramMessageLog.EVENT_APPOINTMENT_CREATED,
        subject="New appointment booked",
        intro_lines=[f"{client_name} booked {service_name}."],
        detail_rows=detail_rows,
    )

    if settings_obj and settings_obj.notify_on_new_appointment:
        return send_telegram_message(
            message,
            event_type=TelegramMessageLog.EVENT_APPOINTMENT_CREATED,
        )
    return 0


def notify_about_order(order_id) -> int:
    settings_obj = TelegramBotSettings.load_active()

    from store.models import Order

    order = (
        Order.objects.select_related("user")
        .prefetch_related("items__product", "items__option")
        .get(pk=order_id)
    )

    lines = []
    for item in order.items.all():
        option_label = f" ({item.option.name})" if getattr(item, "option", None) else ""
        lines.append(f"• {item.product.name}{option_label} × {item.qty}")

    total = f"{order.total:.2f}"
    message = (
        f"<b>New order #{order.pk}</b>\n"
        f"Customer: {order.customer_name}\n"
        f"Email: {order.email}\n"
        f"Phone: {order.phone or '—'}\n"
        f"Total: {total}\n"
    )
    if lines:
        message += "Items:\n" + "\n".join(lines)
    if order.notes:
        message += f"\nNote: {order.notes}"

    detail_rows = [
        ("Order #", order.pk),
        ("Customer", order.customer_name),
        ("Email", order.email),
        ("Phone", order.phone or "—"),
        ("Total", total),
    ]
    item_rows = []
    for item in order.items.all():
        option_label = f" ({item.option.name})" if getattr(item, "option", None) else ""
        item_rows.append((f"{item.product.name}{option_label}", f"x {item.qty}"))

    send_staff_email_notification(
        event_type=TelegramMessageLog.EVENT_ORDER_CREATED,
        subject=f"New order #{order.pk}",
        intro_lines=[f"New order from {order.customer_name}."],
        detail_rows=detail_rows,
        item_rows=item_rows,
    )

    if settings_obj and settings_obj.notify_on_new_order:
        return send_telegram_message(
            message,
            event_type=TelegramMessageLog.EVENT_ORDER_CREATED,
        )
    return 0


def notify_about_service_lead(lead_id) -> int:
    """
    Notify ops chat about a new marketing/landing page inquiry.
    """
    settings_obj = TelegramBotSettings.load_active()

    from core.models import ServiceLead  # late import to avoid circular dependency

    lead = ServiceLead.objects.get(pk=lead_id)

    def _safe(val: str | None) -> str:
        return html.escape(val) if val else "—"

    message = (
        "<b>New service lead</b>\n"
        f"Page: {_safe(lead.get_source_page_display())}\n"
        f"Name: {_safe(lead.full_name)}\n"
        f"Phone: {_safe(lead.phone)}\n"
        f"Email: {_safe(lead.email)}\n"
        f"Service: {_safe(lead.service_needed)}\n"
    )
    if lead.vehicle:
        message += f"Vehicle: {_safe(lead.vehicle)}\n"
    if lead.notes:
        message += f"Notes: {_safe(lead.notes)}\n"
    if lead.source_url:
        message += f"Source: {_safe(lead.source_url)}"

    detail_rows = [
        ("Page", lead.get_source_page_display()),
        ("Name", lead.full_name or "—"),
        ("Phone", lead.phone or "—"),
        ("Email", lead.email or "—"),
        ("Service", lead.service_needed or "—"),
    ]
    if lead.vehicle:
        detail_rows.append(("Vehicle", lead.vehicle))
    if lead.notes:
        detail_rows.append(("Notes", lead.notes))
    if lead.source_url:
        detail_rows.append(("Source", lead.source_url))

    send_staff_email_notification(
        event_type=TelegramMessageLog.EVENT_SERVICE_LEAD,
        subject="New service lead",
        intro_lines=[f"New service lead from {lead.full_name or 'guest'}."],
        detail_rows=detail_rows,
    )

    return send_telegram_message(
        message,
        event_type=TelegramMessageLog.EVENT_SERVICE_LEAD,
    )


def notify_about_fitment_request(request_id) -> int:
    """
    Notify ops chat about a new custom fitment request.
    """
    settings_obj = TelegramBotSettings.load_active()

    from store.models import CustomFitmentRequest  # late import to avoid circular dependency

    req = CustomFitmentRequest.objects.select_related("product").get(pk=request_id)

    def _safe(val: str | None) -> str:
        return html.escape(val) if val else "—"

    product_name = req.product_name or (req.product.name if req.product else "")
    message = (
        "<b>New fitment request</b>\n"
        f"Product: {_safe(product_name)}\n"
        f"Customer: {_safe(req.customer_name)}\n"
        f"Email: {_safe(req.email)}\n"
        f"Phone: {_safe(req.phone)}\n"
        f"Vehicle: {_safe(req.vehicle)}\n"
        f"Submodel: {_safe(req.submodel)}\n"
        f"Goals: {_safe(req.performance_goals)}\n"
        f"Budget: {_safe(req.budget)}\n"
        f"Timeline: {_safe(req.timeline)}\n"
    )
    if req.message:
        message += f"Message: {_safe(req.message)}\n"
    if req.source_url:
        message += f"Source: {_safe(req.source_url)}"

    detail_rows = [
        ("Product", product_name or "—"),
        ("Customer", req.customer_name or "—"),
        ("Email", req.email or "—"),
        ("Phone", req.phone or "—"),
        ("Vehicle", req.vehicle or "—"),
        ("Submodel", req.submodel or "—"),
        ("Goals", req.performance_goals or "—"),
        ("Budget", req.budget or "—"),
        ("Timeline", req.timeline or "—"),
    ]
    if req.message:
        detail_rows.append(("Message", req.message))
    if req.source_url:
        detail_rows.append(("Source", req.source_url))

    send_staff_email_notification(
        event_type=TelegramMessageLog.EVENT_FITMENT_REQUEST,
        subject="New fitment request",
        intro_lines=[f"New fitment request from {req.customer_name or 'guest'}."],
        detail_rows=detail_rows,
    )

    return send_telegram_message(
        message,
        event_type=TelegramMessageLog.EVENT_FITMENT_REQUEST,
    )


def notify_about_site_notice_signup(signup_id) -> int:
    """
    Notify ops chat about a new site notice signup (welcome code sent).
    """
    settings_obj = TelegramBotSettings.load_active()

    from core.models import SiteNoticeSignup  # late import to avoid circular dependency

    signup = SiteNoticeSignup.objects.get(pk=signup_id)

    def _safe(val: str | None) -> str:
        return html.escape(val) if val else "—"

    sent_at = localtime(signup.welcome_sent_at).strftime("%Y-%m-%d %H:%M")
    message = (
        "<b>New site notice signup</b>\n"
        f"Email: {_safe(signup.email)}\n"
        f"Welcome code: {_safe(signup.welcome_code)}\n"
        f"Sent at: {sent_at}\n"
    )

    detail_rows = [
        ("Email", signup.email),
        ("Welcome code", signup.welcome_code),
        ("Sent at", sent_at),
    ]
    send_staff_email_notification(
        event_type=TelegramMessageLog.EVENT_SITE_NOTICE_WELCOME,
        subject="New site notice signup",
        intro_lines=["New site notice signup captured."],
        detail_rows=detail_rows,
    )

    return send_telegram_message(
        message,
        event_type=TelegramMessageLog.EVENT_SITE_NOTICE_WELCOME,
    )


def notify_about_order_review_request(order_id, *, review_url: str = "", store_url: str = "") -> int:
    """
    Notify ops chat about a review request email being sent.
    """
    settings_obj = TelegramBotSettings.load_active()

    from store.models import Order  # late import to avoid circular dependency

    order = Order.objects.select_related("user").get(pk=order_id)

    def _safe(val: str | None) -> str:
        return html.escape(val) if val else "—"

    completed_at = ""
    if order.completed_at:
        completed_at = localtime(order.completed_at).strftime("%Y-%m-%d %H:%M")

    message = (
        "<b>Order review request sent</b>\n"
        f"Order #: {order.pk}\n"
        f"Customer: {_safe(order.customer_name)}\n"
        f"Email: {_safe(order.email)}\n"
        f"Completed at: {completed_at or '—'}\n"
    )
    if review_url:
        message += f"Review link: {_safe(review_url)}\n"
    if store_url:
        message += f"Store link: {_safe(store_url)}"

    detail_rows = [
        ("Order #", order.pk),
        ("Customer", order.customer_name),
        ("Email", order.email),
        ("Completed at", completed_at or "—"),
    ]
    if review_url:
        detail_rows.append(("Review link", review_url))
    if store_url:
        detail_rows.append(("Store link", store_url))

    send_staff_email_notification(
        event_type=TelegramMessageLog.EVENT_ORDER_REVIEW_REQUEST,
        subject=f"Order review request sent #{order.pk}",
        intro_lines=[f"Review request sent to {order.customer_name}."],
        detail_rows=detail_rows,
    )

    if settings_obj:
        return send_telegram_message(
            message,
            event_type=TelegramMessageLog.EVENT_ORDER_REVIEW_REQUEST,
        )
    return 0


def build_operations_digest() -> str:
    """
    Returns a daily overview of appointments and store activity.
    """
    from core.models import Appointment
    from store.models import Order, OrderItem

    today = timezone.localdate()
    now = timezone.now()
    today_appointments = Appointment.objects.filter(start_time__date=today)
    appt_count = today_appointments.count()
    upcoming = (
        Appointment.objects.filter(start_time__gte=now)
        .select_related("service", "master")
        .order_by("start_time")[:3]
    )
    orders_processing = Order.objects.filter(status=Order.STATUS_PROCESSING).count()
    recent_window = today - timedelta(days=7)
    money_expr = ExpressionWrapper(
        Coalesce(F("price_at_moment"), Value(0)) * F("qty"),
        output_field=DecimalField(max_digits=12, decimal_places=2),
    )
    revenue_val = (
        OrderItem.objects.filter(order__completed_at__date__gte=recent_window)
        .aggregate(total=Sum(money_expr))
        .get("total")
        or Decimal("0.00")
    )
    message = (
        f"<b>Daily operations — {today.strftime('%Y-%m-%d')}</b>\n"
        f"Appointments today: {appt_count}\n"
        f"Open orders: {orders_processing}\n"
        f"Completed revenue (7d): {revenue_val:.2f}\n"
    )
    if upcoming:
        message += "\nNext appointments:\n"
        for slot in upcoming:
            slot_time = localtime(slot.start_time).strftime("%b %d %H:%M")
            master_name = slot.master.get_full_name() or slot.master.username
            message += f"• {slot.service.name} with {master_name} at {slot_time}\n"
    return message


def send_daily_digest(force: bool = False) -> int:
    settings_obj = TelegramBotSettings.load_active()
    if not settings_obj or (not settings_obj.digest_enabled and not force):
        return 0

    today = timezone.localdate()
    current_hour = localtime(timezone.now()).hour
    if not force and current_hour < settings_obj.digest_hour_local:
        return 0
    if not force and settings_obj.last_digest_sent_on == today:
        return 0

    delivered = send_telegram_message(
        build_operations_digest(),
        event_type=TelegramMessageLog.EVENT_DIGEST,
    )
    if delivered:
        settings_obj.last_digest_sent_on = today
        settings_obj.save(update_fields=["last_digest_sent_on", "updated_at"])
    return delivered


def deliver_reminder(reminder: TelegramReminder) -> int:
    settings_obj = TelegramBotSettings.load_active()
    recipients = reminder.chat_id_list or (settings_obj.chat_id_list if settings_obj else [])
    if not recipients:
        reminder.mark_sent(
            success=False,
            error_message="Telegram bot is disabled or no recipients are configured.",
        )
        return 0

    text = f"<b>{reminder.title}</b>\n{reminder.message}"
    delivered = send_telegram_message(
        text,
        event_type=TelegramMessageLog.EVENT_REMINDER,
        chat_ids=recipients,
    )
    if delivered:
        reminder.mark_sent(success=True)
    else:
        reminder.mark_sent(success=False, error_message="Failed to deliver reminder.")
    return delivered


def process_due_reminders() -> int:
    processed = 0
    for reminder in TelegramReminder.due().order_by("scheduled_for"):
        deliver_reminder(reminder)
        processed += 1
    return processed
