from __future__ import annotations

import logging

from django.conf import settings
from django.utils.timezone import localtime

from core.emails import build_email_html, send_html_email

logger = logging.getLogger(__name__)


def _appointment_client_name(appointment) -> str:
    client_name = appointment.contact_name
    if not client_name and appointment.client:
        client_name = appointment.client.get_full_name() or appointment.client.username
    return client_name or "Guest"


def send_appointment_confirmation(appointment_id) -> bool:
    from core.models import Appointment

    appointment = Appointment.objects.select_related(
        "service",
        "master",
        "client",
    ).get(pk=appointment_id)

    recipient = (appointment.contact_email or "").strip()
    if not recipient and appointment.client:
        recipient = (appointment.client.email or "").strip()
    if not recipient:
        return False

    sender = (
        getattr(settings, "DEFAULT_FROM_EMAIL", None)
        or getattr(settings, "SUPPORT_EMAIL", None)
    )
    if not sender:
        logger.warning(
            "Missing DEFAULT_FROM_EMAIL/SUPPORT_EMAIL; skipping appointment confirmation for %s",
            appointment_id,
        )
        return False

    brand = getattr(settings, "SITE_BRAND_NAME", "BGM Customs")
    client_name = _appointment_client_name(appointment)
    master_name = appointment.master.get_full_name() or appointment.master.username
    service_name = appointment.service.name
    start = localtime(appointment.start_time).strftime("%Y-%m-%d %H:%M %Z")

    subject = f"{brand} booking confirmed"
    lines = [
        f"Hi {client_name},",
        f"Thanks for booking with {brand}. Your appointment is confirmed.",
        "",
        f"Appointment ID: {appointment.id}",
        f"Service: {service_name}",
        f"Tech: {master_name}",
        f"When: {start}",
        "",
        "If you need to reschedule, reply to this email and we'll help.",
    ]

    try:
        detail_rows = [
            ("Appointment ID", appointment.id),
            ("Service", service_name),
            ("Tech", master_name),
            ("When", start),
        ]
        if appointment.contact_phone:
            detail_rows.append(("Phone", appointment.contact_phone))
        if appointment.contact_email:
            detail_rows.append(("Email", appointment.contact_email))
        html_body = build_email_html(
            title="Booking confirmed",
            preheader=f"Appointment {appointment.id} confirmed",
            greeting=f"Hi {client_name},",
            intro_lines=[f"Thanks for booking with {brand}. Your appointment is confirmed."],
            detail_rows=detail_rows,
            footer_lines=["If you need to reschedule, reply to this email and we'll help."],
            cta_label=f"Visit {brand}",
            cta_url=getattr(settings, "COMPANY_WEBSITE", ""),
        )
        send_html_email(
            subject=subject,
            text_body="\n".join(lines),
            html_body=html_body,
            from_email=sender,
            recipient_list=[recipient],
        )
    except Exception:
        logger.exception(
            "Failed to send appointment confirmation email for appointment %s",
            appointment_id,
        )
        return False
    return True
