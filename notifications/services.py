"""
Utilities for the Telegram bot integration.
"""
from __future__ import annotations

import html
from datetime import timedelta
from decimal import Decimal
from typing import Sequence

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

from .models import (
    TelegramBotSettings,
    TelegramMessageLog,
    TelegramReminder,
)


class TelegramConfigurationError(Exception):
    """Raised when Telegram bot actions are requested without valid settings."""


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


def _format_digest_counts(items: dict[str, int], limit: int = 3) -> str:
    if not items:
        return ""
    ordered = sorted(items.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    return ", ".join(f"{label} ({count})" for label, count in ordered)


def queue_lead_digest(
    *,
    form_type: str,
    suspicious: bool,
    ip_address: str | None = None,
    asn: str | None = None,
    interval_seconds: int = 300,
) -> None:
    """
    Aggregate noisy lead alerts and emit a compact digest every interval.
    """
    cache_key = f"tg:lead_digest:{form_type}"
    now = timezone.now()
    state = cache.get(cache_key) or {
        "started_at": now,
        "total": 0,
        "suspected": 0,
        "ips": {},
        "asns": {},
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

    elapsed = (now - started_at).total_seconds()
    if elapsed >= interval_seconds:
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
        }

    cache.set(cache_key, state, timeout=interval_seconds * 4)


def notify_about_appointment(appointment_id) -> int:
    settings_obj = TelegramBotSettings.load_active()
    if not settings_obj or not settings_obj.notify_on_new_appointment:
        return 0
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

    return send_telegram_message(
        message,
        event_type=TelegramMessageLog.EVENT_APPOINTMENT_CREATED,
    )


def notify_about_order(order_id) -> int:
    settings_obj = TelegramBotSettings.load_active()
    if not settings_obj or not settings_obj.notify_on_new_order:
        return 0

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

    return send_telegram_message(
        message,
        event_type=TelegramMessageLog.EVENT_ORDER_CREATED,
    )


def notify_about_service_lead(lead_id) -> int:
    """
    Notify ops chat about a new marketing/landing page inquiry.
    """
    settings_obj = TelegramBotSettings.load_active()
    if not settings_obj:
        return 0

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

    return send_telegram_message(
        message,
        event_type=TelegramMessageLog.EVENT_SERVICE_LEAD,
    )


def notify_about_fitment_request(request_id) -> int:
    """
    Notify ops chat about a new custom fitment request.
    """
    settings_obj = TelegramBotSettings.load_active()
    if not settings_obj:
        return 0

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

    return send_telegram_message(
        message,
        event_type=TelegramMessageLog.EVENT_FITMENT_REQUEST,
    )


def notify_about_site_notice_signup(signup_id) -> int:
    """
    Notify ops chat about a new site notice signup (welcome code sent).
    """
    settings_obj = TelegramBotSettings.load_active()
    if not settings_obj:
        return 0

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

    return send_telegram_message(
        message,
        event_type=TelegramMessageLog.EVENT_SITE_NOTICE_WELCOME,
    )


def notify_about_order_review_request(order_id, *, review_url: str = "", store_url: str = "") -> int:
    """
    Notify ops chat about a review request email being sent.
    """
    settings_obj = TelegramBotSettings.load_active()
    if not settings_obj:
        return 0

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

    return send_telegram_message(
        message,
        event_type=TelegramMessageLog.EVENT_ORDER_REVIEW_REQUEST,
    )


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
