from __future__ import annotations

import logging

from django.conf import settings
from django.utils.timezone import localtime

from core.email_templates import base_email_context, email_brand_name, join_text_sections, render_email_template
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

    brand = email_brand_name()
    client_name = _appointment_client_name(appointment)
    master_name = appointment.master.get_full_name() or appointment.master.username
    service_name = appointment.service.name
    start = localtime(appointment.start_time).strftime("%Y-%m-%d %H:%M %Z")

    context = base_email_context(
        {
            "brand": brand,
            "client_name": client_name,
            "appointment_id": appointment.id,
            "service_name": service_name,
            "tech_name": master_name,
            "appointment_time": start,
        }
    )
    template = render_email_template("appointment_confirmation", context)

    detail_lines = [
        f"Appointment ID: {appointment.id}",
        f"Service: {service_name}",
        f"Tech: {master_name}",
        f"When: {start}",
    ]
    lines = join_text_sections(
        [template.greeting],
        template.intro_lines,
        detail_lines,
        template.footer_lines,
    )

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
            title=template.title,
            preheader=template.preheader,
            greeting=template.greeting,
            intro_lines=template.intro_lines,
            detail_rows=detail_rows,
            notice_title=template.notice_title or None,
            notice_lines=template.notice_lines,
            footer_lines=template.footer_lines,
            cta_label=template.cta_label,
            cta_url=template.cta_url,
        )
        send_html_email(
            subject=template.subject,
            text_body=lines,
            html_body=html_body,
            from_email=sender,
            recipient_list=[recipient],
            email_type="appointment_confirmation",
        )
    except Exception:
        logger.exception(
            "Failed to send appointment confirmation email for appointment %s",
            appointment_id,
        )
        return False
    return True
