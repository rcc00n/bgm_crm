"""
Utilities for the Telegram bot integration.
"""
from __future__ import annotations

import html
import re
import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Sequence

from django.conf import settings
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

from core.emails import build_email_html, send_html_email
from core.email_templates import join_text_sections

from .lead_digest import queue_lead_digest

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


def _neutralize_campaign_links(value: str) -> str:
    from core.services.lead_security import KNOWN_CAMPAIGN_DOMAINS

    for domain in KNOWN_CAMPAIGN_DOMAINS:
        pattern = r"(?<![\w.-])(?:[\w-]+\.)*" + re.escape(domain) + r"(?![\w.-])"
        value = re.sub(pattern, lambda match: match.group(0).replace(".", "[.]"), value, flags=re.IGNORECASE)
    return value


def safe_user_text(value: object | None, *, max_length: int = 120) -> str:
    if value is None or value == "":
        return "—"
    cleaned = _neutralize_campaign_links(str(value))
    escaped = html.escape(cleaned)
    if len(escaped.encode("utf-16-le", errors="replace")) // 2 <= max_length:
        return escaped
    # Budget escaped characters, so input containing many '&' or '<' characters
    # cannot create an oversized message. Never split an HTML entity/tag.
    parts = []
    length = 0
    for char in cleaned:
        part = html.escape(char)
        part_length = len(part.encode("utf-16-le", errors="replace")) // 2
        if length + part_length > max_length - 1:
            break
        parts.append(part)
        length += part_length
    return "".join(parts) + "…"


def _entity_link(entity_type: str, entity_id) -> str:
    paths = {
        "appointment": "core/appointment",
        "order": "store/order",
        "dealer_application": "core/dealerapplication",
        "service_lead": "core/servicelead",
        "lead": "core/lead",
        "fitment_request": "store/customfitmentrequest",
        "site_notice": "core/sitenoticesignup",
        "order_review_request": "store/order",
        "reminder": "notifications/telegramreminder",
    }
    base = (getattr(settings, "PUBLIC_BASE_URL", "") or "https://badguymotors.com").rstrip("/")
    url = f"{base}/admin/{paths[entity_type]}/{entity_id}/change/"
    return f'\n<a href="{html.escape(url, quote=True)}">Open full details</a>'


def _review_notice(entity_type: str, entity_id) -> str:
    from core.services.lead_review import review_case_for

    case = review_case_for(entity_type, entity_id)
    if not case or case.status != "pending":
        return ""
    base = (getattr(settings, "PUBLIC_BASE_URL", "") or "https://badguymotors.com").rstrip("/")
    reasons = ", ".join(str(reason) for reason in case.reasons) or "Needs staff verification"
    return (
        "<b>Lead needs review</b>\n"
        f"Reason: {safe_user_text(reasons)}\n"
        f"Review: {base}/admin/core/leadreviewcase/{case.pk}/change/\n\n"
    )


def send_telegram_message(
    message: str,
    *,
    event_type: str,
    chat_ids: Sequence[int] | None = None,
    dedupe_key: str | None = None,
    entity_type: str = "",
    entity_id: str = "",
    digest_slot: str = "",
) -> int:
    from .delivery import send_message

    return send_message(
        _neutralize_campaign_links(message),
        event_type=event_type,
        chat_ids=chat_ids,
        dedupe_key=dedupe_key,
        entity_type=entity_type,
        entity_id=entity_id,
        digest_slot=digest_slot,
    )


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
    # Internal notifications should always land in the support inbox (single source of truth).
    recipient = (getattr(settings, "SUPPORT_EMAIL", "") or "").strip()
    if not recipient:
        recipient = "support@badguymotors.com"
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

    try:
        send_html_email(
            subject=subject,
            text_body=text_body,
            html_body=html_body,
            from_email=sender,
            recipient_list=[recipient],
            email_type=f"staff_{event_type}",
        )
        return 1
    except Exception:
        return 0


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
        f"Client: {safe_user_text(client_name)}\n"
        f"Service: {safe_user_text(service_name)}\n"
        f"Tech: {safe_user_text(master_name)}\n"
        f"When: {start}\n"
    )
    if appointment.contact_phone:
        message += f"Phone: {safe_user_text(appointment.contact_phone)}\n"
    if appointment.contact_email:
        message += f"Email: {safe_user_text(appointment.contact_email)}\n"

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

    message += _entity_link("appointment", appointment_id)

    if settings_obj and settings_obj.notify_on_new_appointment:
        return send_telegram_message(
            message,
            event_type=TelegramMessageLog.EVENT_APPOINTMENT_CREATED,
            dedupe_key=f"appointment:{appointment_id}",
            entity_type="appointment",
            entity_id=appointment_id,
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
        lines.append(f"• {safe_user_text(item.product.name + option_label)} × {item.qty}")

    total = f"{order.total:.2f}"
    message = (
        f"<b>New order #{order.pk}</b>\n"
        f"Customer: {safe_user_text(order.customer_name)}\n"
        f"Email: {safe_user_text(order.email)}\n"
        f"Phone: {safe_user_text(order.phone)}\n"
        f"Total: {total}\n"
    )
    if lines:
        message += "Items:\n" + "\n".join(lines[:8])
        if len(lines) > 8:
            message += f"\n… and {len(lines) - 8} more items; see full order."
    if order.notes:
        message += f"\nNote: {safe_user_text(order.notes, max_length=1600)}"

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

    message += _entity_link("order", order_id)

    if settings_obj and settings_obj.notify_on_new_order:
        return send_telegram_message(
            message,
            event_type=TelegramMessageLog.EVENT_ORDER_CREATED,
            dedupe_key=f"order:{order_id}",
            entity_type="order",
            entity_id=order_id,
        )
    return 0


def notify_about_dealer_application(application_id) -> int:
    from core.models import DealerApplication

    app = (
        DealerApplication.objects.select_related("user")
        .get(pk=application_id)
    )

    def _safe(val: str | None) -> str:
        return safe_user_text(val)

    user = app.user
    user_label = user.get_full_name() or user.username or "User"
    user_label = user_label.strip() or "User"

    products_spent = "—"
    try:
        from core.utils import format_currency

        up = getattr(user, "userprofile", None)
        if up:
            products_spent = format_currency(up.total_spent_products_cad())
    except Exception:
        products_spent = "—"

    address_bits = []
    if app.business_address:
        address_bits.append(app.business_address)
    city_line = ", ".join([bit for bit in [app.city, app.province, app.postal_code] if bit]).strip(", ")
    if city_line:
        address_bits.append(city_line)

    message = (
        "<b>New dealer application</b>\n"
        f"User: {_safe(user_label)} (#{getattr(user, 'pk', '—')})\n"
        f"Business: {_safe(app.business_name)}\n"
        f"Email: {_safe(app.email or getattr(user, 'email', ''))}\n"
        f"Phone: {_safe(app.phone)}\n"
        f"Products spent: {_safe(products_spent)}\n"
        f"Projected tier: {_safe(getattr(app, 'get_preferred_tier_display', lambda: '')() or app.preferred_tier)}\n"
    )
    if address_bits:
        message += "Address:\n" + "\n".join(_safe(line) for line in address_bits)

    message += _entity_link("dealer_application", application_id)

    return send_telegram_message(
        message,
        event_type=TelegramMessageLog.EVENT_DEALER_APPLICATION_CREATED,
        dedupe_key=f"dealer_application:{application_id}",
        entity_type="dealer_application",
        entity_id=application_id,
    )


def notify_about_service_lead(lead_id) -> int:
    """
    Notify ops chat about a new marketing/landing page inquiry.
    """
    settings_obj = TelegramBotSettings.load_active()

    from core.models import ServiceLead  # late import to avoid circular dependency

    lead = ServiceLead.objects.get(pk=lead_id)

    def _safe(val: str | None) -> str:
        return safe_user_text(val)

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
        message += f"Notes: {safe_user_text(lead.notes, max_length=1600)}\n"
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

    review_notice = _review_notice("service_lead", lead_id)
    if not review_notice:
        send_staff_email_notification(
            event_type=TelegramMessageLog.EVENT_SERVICE_LEAD,
            subject="New service lead",
            intro_lines=[f"New service lead from {lead.full_name or 'guest'}."],
            detail_rows=detail_rows,
        )

    if review_notice:
        message = review_notice + message

    message += _entity_link("service_lead", lead_id)

    return send_telegram_message(
        message,
        event_type=TelegramMessageLog.EVENT_SERVICE_LEAD,
        dedupe_key=f"service_lead:{lead_id}",
        entity_type="service_lead",
        entity_id=lead_id,
    )


def notify_about_lead(lead_id) -> int:
    """
    Notify ops chat about a new qualification lead.
    """
    from core.models import Lead  # late import to avoid circular dependency

    lead = Lead.objects.get(pk=lead_id)

    def _safe(val: str | None) -> str:
        return safe_user_text(val)

    work_needed = ", ".join(lead.get_work_needed_display_list()) or "—"
    truck_label = f"{lead.truck_year} {lead.truck_make} {lead.truck_model}".strip()

    message = (
        "<b>New lead</b>\n"
        f"Flagged: {_safe('Yes' if lead.flagged else 'No')}\n"
        f"Name: {_safe(lead.name)}\n"
        f"Phone: {_safe(lead.phone)}\n"
        f"Email: {_safe(lead.email)}\n"
        f"Preferred contact: {_safe(lead.get_contact_pref_display())}\n"
        f"Truck: {_safe(truck_label)}\n"
        f"Mileage: {_safe(lead.get_mileage_display())}\n"
        f"Primary use: {_safe(lead.get_industry_display())}\n"
        f"Work needed: {_safe(work_needed)}\n"
        f"Timeline: {_safe(lead.get_timeline_display())}\n"
        f"Frustration: {safe_user_text(lead.frustration, max_length=1600)}\n"
    )

    review_notice = _review_notice("lead", lead_id)
    if review_notice:
        message = review_notice + message

    message += _entity_link("lead", lead_id)

    return send_telegram_message(
        message,
        event_type=TelegramMessageLog.EVENT_LEAD,
        dedupe_key=f"lead:{lead_id}",
        entity_type="lead",
        entity_id=lead_id,
    )


def notify_about_fitment_request(request_id) -> int:
    """
    Notify ops chat about a new custom fitment request.
    """
    settings_obj = TelegramBotSettings.load_active()

    from store.models import CustomFitmentRequest  # late import to avoid circular dependency

    req = CustomFitmentRequest.objects.select_related("product").get(pk=request_id)

    def _safe(val: str | None) -> str:
        return safe_user_text(val)

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
        message += f"Message: {safe_user_text(req.message, max_length=1600)}\n"
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

    review_notice = _review_notice("fitment_request", request_id)
    if not review_notice:
        send_staff_email_notification(
            event_type=TelegramMessageLog.EVENT_FITMENT_REQUEST,
            subject="New fitment request",
            intro_lines=[f"New fitment request from {req.customer_name or 'guest'}."],
            detail_rows=detail_rows,
        )

    if review_notice:
        message = review_notice + message

    message += _entity_link("fitment_request", request_id)

    return send_telegram_message(
        message,
        event_type=TelegramMessageLog.EVENT_FITMENT_REQUEST,
        dedupe_key=f"fitment_request:{request_id}",
        entity_type="fitment_request",
        entity_id=request_id,
    )


def notify_about_site_notice_signup(signup_id) -> int:
    """
    Notify ops chat about a new site notice signup (welcome code sent).
    """
    settings_obj = TelegramBotSettings.load_active()

    from core.models import SiteNoticeSignup  # late import to avoid circular dependency

    signup = SiteNoticeSignup.objects.get(pk=signup_id)

    def _safe(val: str | None) -> str:
        return safe_user_text(val)

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

    message += _entity_link("site_notice", signup_id)

    return send_telegram_message(
        message,
        event_type=TelegramMessageLog.EVENT_SITE_NOTICE_WELCOME,
        dedupe_key=f"site_notice:{signup_id}",
        entity_type="site_notice",
        entity_id=signup_id,
    )


def notify_about_order_review_request(order_id, *, review_url: str = "", store_url: str = "") -> int:
    """
    Notify ops chat about a review request email being sent.
    """
    settings_obj = TelegramBotSettings.load_active()

    from store.models import Order  # late import to avoid circular dependency

    order = Order.objects.select_related("user").get(pk=order_id)

    def _safe(val: str | None) -> str:
        return safe_user_text(val)

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

    message += _entity_link("order_review_request", order_id)

    if settings_obj:
        return send_telegram_message(
            message,
            event_type=TelegramMessageLog.EVENT_ORDER_REVIEW_REQUEST,
            dedupe_key=f"order_review_request:{order_id}",
            entity_type="order_review_request",
            entity_id=order_id,
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
            message += f"• {safe_user_text(slot.service.name)} with {safe_user_text(master_name)} at {slot_time}\n"
    return message


def send_daily_digest(force: bool = False) -> int:
    from .delivery import queued_message_count

    settings_obj = TelegramBotSettings.load_active()
    if not settings_obj or (not settings_obj.digest_enabled and not force):
        return 0
    today = timezone.localdate()
    if not force and localtime(timezone.now()).hour < settings_obj.digest_hour_local:
        return 0
    if not force and settings_obj.last_digest_sent_on == today:
        return 0

    key = f"daily-operations:{today.isoformat()}"
    if force:
        key += f":manual:{uuid.uuid4().hex}"
    recipients = settings_obj.chat_id_list
    delivered = send_telegram_message(
        build_operations_digest(),
        event_type=TelegramMessageLog.EVENT_DIGEST,
        chat_ids=recipients,
        dedupe_key=key,
        entity_type="daily_operations",
        entity_id=today.isoformat(),
        digest_slot=today.isoformat(),
    )
    # A queued copy survives Telegram failure, so the bot's retry loop owns it.
    if queued_message_count(key, recipients) == len(set(recipients)):
        settings_obj.last_digest_sent_on = today
        settings_obj.save(update_fields=["last_digest_sent_on", "updated_at"])
    return delivered


def deliver_reminder(reminder: TelegramReminder) -> int:
    settings_obj = TelegramBotSettings.load()
    recipients = list(dict.fromkeys(reminder.chat_id_list or (settings_obj.chat_id_list if settings_obj else [])))
    if not recipients:
        reminder.last_error = "No recipients configured; reminder remains pending."
        reminder.save(update_fields=["last_error", "updated_at"])
        return 0

    key = f"reminder:{reminder.pk}"
    text = f"<b>{safe_user_text(reminder.title)}</b>\n{safe_user_text(reminder.message, max_length=2800)}"
    text += _entity_link("reminder", reminder.pk)
    delivered = send_telegram_message(
        text,
        event_type=TelegramMessageLog.EVENT_REMINDER,
        chat_ids=recipients,
        dedupe_key=key,
        entity_type="reminder",
        entity_id=reminder.pk,
    )
    sent_count = TelegramMessageLog.objects.filter(
        dedupe_key=key, chat_id__in=recipients, status=TelegramMessageLog.Status.SENT,
    ).count()
    if sent_count == len(recipients):
        reminder.mark_sent(success=True)
    else:
        reminder.status = TelegramReminder.Status.PENDING
        reminder.last_error = "Delivery queued; remaining recipients will retry automatically."
        reminder.save(update_fields=["status", "last_error", "updated_at"])
    return delivered


def process_due_reminders(*, since=None, limit: int = 20) -> int:
    if since is None:
        since = getattr(settings, "TELEGRAM_AUTOMATION_START_AT", None)
    if isinstance(since, str):
        from django.utils.dateparse import parse_datetime
        since = parse_datetime(since)
    due = TelegramReminder.due()
    if since is not None:
        due = due.filter(scheduled_for__gte=since)
    processed = 0
    for reminder in due.order_by("scheduled_for")[:max(0, min(limit, 100))]:
        deliver_reminder(reminder)
        processed += 1
    return processed
