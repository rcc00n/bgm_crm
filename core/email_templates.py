from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from django.conf import settings

from core.models import EmailTemplate


@dataclass(frozen=True)
class EmailTemplateDefinition:
    slug: str
    name: str
    description: str
    subject: str
    preheader: str
    title: str
    greeting: str
    intro_lines: Sequence[str]
    notice_title: str = ""
    notice_lines: Sequence[str] = ()
    footer_lines: Sequence[str] = ()
    cta_label: str = ""
    tokens: Sequence[str] = ()


@dataclass
class RenderedEmailTemplate:
    subject: str
    preheader: str
    title: str
    greeting: str
    intro_lines: list[str]
    notice_title: str
    notice_lines: list[str]
    footer_lines: list[str]
    cta_label: str


EMAIL_TEMPLATE_DEFINITIONS: dict[str, EmailTemplateDefinition] = {
    "appointment_confirmation": EmailTemplateDefinition(
        slug="appointment_confirmation",
        name="Appointment confirmation",
        description="Sent when a booking is confirmed.",
        subject="{brand} booking confirmed",
        preheader="Appointment {appointment_id} confirmed",
        title="Booking confirmed",
        greeting="Hi {client_name},",
        intro_lines=["Thanks for booking with {brand}. Your appointment is confirmed."],
        footer_lines=["If you need to reschedule, reply to this email and we'll help."],
        cta_label="Visit {brand}",
        tokens=[
            "brand",
            "client_name",
            "appointment_id",
            "service_name",
            "tech_name",
            "appointment_time",
            "company_website",
        ],
    ),
    "order_confirmation": EmailTemplateDefinition(
        slug="order_confirmation",
        name="Order confirmation",
        description="Sent after checkout succeeds.",
        subject="{brand} order #{order_id} confirmed",
        preheader="Order #{order_id} confirmed",
        title="Order confirmed",
        greeting="Hi {customer_name},",
        intro_lines=["Thanks for your order with {brand}. We've got it and will follow up shortly."],
        footer_lines=["Questions? Reply to this email and we'll help."],
        cta_label="Visit {brand}",
        tokens=[
            "brand",
            "customer_name",
            "order_id",
            "order_total",
            "payment_method",
            "payment_option",
            "company_website",
        ],
    ),
    "order_status_processing": EmailTemplateDefinition(
        slug="order_status_processing",
        name="Order status: processing",
        description="Sent when an order moves to processing.",
        subject="{brand} order #{order_id} {order_status}",
        preheader="We are preparing your order now.",
        title="Order update: processing",
        greeting="Hi {customer_name},",
        intro_lines=["Your order is now in processing. We'll keep you posted as it moves along."],
        footer_lines=["Questions? Reply to this email and we'll help."],
        cta_label="Visit {brand}",
        tokens=["brand", "customer_name", "order_id", "order_status", "order_total", "company_website"],
    ),
    "order_status_shipped": EmailTemplateDefinition(
        slug="order_status_shipped",
        name="Order status: shipped",
        description="Sent when an order ships.",
        subject="{brand} order #{order_id} {order_status}",
        preheader="Your order is on the way.",
        title="Order update: shipped",
        greeting="Hi {customer_name},",
        intro_lines=["Your order has shipped and is on the way to you."],
        footer_lines=["Questions? Reply to this email and we'll help."],
        cta_label="Visit {brand}",
        tokens=["brand", "customer_name", "order_id", "order_status", "order_total", "company_website"],
    ),
    "order_status_completed": EmailTemplateDefinition(
        slug="order_status_completed",
        name="Order status: completed",
        description="Sent when an order is completed.",
        subject="{brand} order #{order_id} {order_status}",
        preheader="Your order is marked complete.",
        title="Order update: completed",
        greeting="Hi {customer_name},",
        intro_lines=["Your order is marked complete. Thanks again for choosing us."],
        footer_lines=["Questions? Reply to this email and we'll help."],
        cta_label="Visit {brand}",
        tokens=["brand", "customer_name", "order_id", "order_status", "order_total", "company_website"],
    ),
    "order_status_cancelled": EmailTemplateDefinition(
        slug="order_status_cancelled",
        name="Order status: cancelled",
        description="Sent when an order is cancelled.",
        subject="{brand} order #{order_id} {order_status}",
        preheader="Your order was cancelled.",
        title="Order update: cancelled",
        greeting="Hi {customer_name},",
        intro_lines=["Your order was cancelled. If this is unexpected, reply to this email and we'll help."],
        footer_lines=["Questions? Reply to this email and we'll help."],
        cta_label="Visit {brand}",
        tokens=["brand", "customer_name", "order_id", "order_status", "order_total", "company_website"],
    ),
    "abandoned_cart_1": EmailTemplateDefinition(
        slug="abandoned_cart_1",
        name="Abandoned cart (1st)",
        description="First reminder when a cart is abandoned.",
        subject="{brand} - your cart is waiting",
        preheader="You left a few items behind. Resume checkout anytime.",
        title="Your cart is waiting",
        greeting="Hi there,",
        intro_lines=["You left a few items in your cart. We saved them for you."],
        footer_lines=["Questions? Reply to this email and we will help."],
        cta_label="Resume checkout",
        tokens=["brand", "checkout_url", "cart_url", "store_url"],
    ),
    "abandoned_cart_2": EmailTemplateDefinition(
        slug="abandoned_cart_2",
        name="Abandoned cart (2nd)",
        description="Second reminder when a cart is abandoned.",
        subject="{brand} - still want these items?",
        preheader="Finish checkout whenever you are ready.",
        title="Your cart is still saved",
        greeting="Hi there,",
        intro_lines=["Your cart is still saved. If you want help with fitment or shipping, reply here."],
        footer_lines=["Questions? Reply to this email and we will help."],
        cta_label="Go to checkout",
        tokens=["brand", "checkout_url", "cart_url", "store_url"],
    ),
    "abandoned_cart_3": EmailTemplateDefinition(
        slug="abandoned_cart_3",
        name="Abandoned cart (3rd)",
        description="Final reminder when a cart is abandoned.",
        subject="{brand} - last reminder for your cart",
        preheader="Your cart is ready if you still want these items.",
        title="Last reminder for your cart",
        greeting="Hi there,",
        intro_lines=["Just a final reminder in case you still want these items."],
        footer_lines=["Questions? Reply to this email and we will help."],
        cta_label="Checkout now",
        tokens=["brand", "checkout_url", "cart_url", "store_url"],
    ),
    "site_notice_welcome": EmailTemplateDefinition(
        slug="site_notice_welcome",
        name="Email signup: welcome code",
        description="Sent after someone joins the email list.",
        subject="{brand} welcome code",
        preheader="Welcome code inside: {welcome_code}",
        title="Your 5% welcome code",
        greeting="Thanks for joining the {brand} email list.",
        intro_lines=[
            "Here is your welcome code for 5% off your first order.",
            "Use it on any product or service invoice.",
        ],
        footer_lines=["Questions? Reply to this email and we will help."],
        cta_label="Visit {brand}",
        tokens=["brand", "welcome_code", "company_website"],
    ),
    "site_notice_followup_2": EmailTemplateDefinition(
        slug="site_notice_followup_2",
        name="Email signup: 24h follow-up",
        description="Sent 24 hours after email signup.",
        subject="{brand} follow-up: your 5% code",
        preheader="Customer note + your 5% code: {welcome_code}",
        title="Your welcome code is still ready",
        greeting="Hi there,",
        intro_lines=[
            "Your welcome code is still active: {welcome_code}.",
            "Use it on any product or service invoice.",
        ],
        notice_title="Customer note",
        notice_lines=["\"The install was clean and the team kept me updated the whole time.\""],
        footer_lines=["Questions? Reply to this email and we will help."],
        cta_label="Shop best sellers",
        tokens=["brand", "welcome_code", "best_sellers_url", "services_url", "booking_url"],
    ),
    "site_notice_followup_3": EmailTemplateDefinition(
        slug="site_notice_followup_3",
        name="Email signup: 3-day follow-up",
        description="Sent 3 days after email signup.",
        subject="{brand} - want a quote or want to book in?",
        preheader="Ready when you are - book or browse services.",
        title="Want a quote or want to book in?",
        greeting="Hi there,",
        intro_lines=[
            "We can price it out fast or lock in a time that works for you.",
            "Pick a service or jump straight to booking.",
        ],
        footer_lines=["Questions? Reply to this email and we will help."],
        cta_label="Book a service",
        tokens=["brand", "services_url", "booking_url"],
    ),
    "order_review_request": EmailTemplateDefinition(
        slug="order_review_request",
        name="Order review request",
        description="Sent after completed orders to request a review.",
        subject="{brand} - how did we do?",
        preheader="A quick review helps the team a ton.",
        title="How did we do?",
        greeting="Hi {customer_name},",
        intro_lines=[
            "Thanks again for your order.",
            "If everything looks good, would you leave us a quick review?",
        ],
        footer_lines=["Questions? Reply to this email and we'll help."],
        cta_label="Leave a review",
        tokens=["brand", "customer_name", "order_id", "review_url", "store_url"],
    ),
    "fitment_request_internal": EmailTemplateDefinition(
        slug="fitment_request_internal",
        name="Custom fitment request (internal)",
        description="Internal alert when a custom fitment request is submitted.",
        subject="Custom fitment request — {product_name}",
        preheader="New request from {customer_name}",
        title="New custom fitment request",
        greeting="Team,",
        intro_lines=["A new custom fitment request just landed. Details below."],
        notice_title="Notes",
        footer_lines=["Reply to the customer within 1-2 business days."],
        tokens=[
            "customer_name",
            "product_name",
            "customer_email",
            "customer_phone",
            "vehicle",
            "submodel",
            "performance_goals",
            "budget",
            "timeline",
            "source_url",
        ],
    ),
}


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return ""


def base_email_context(extra: dict[str, object] | None = None) -> dict[str, str]:
    context = {
        "brand": getattr(settings, "SITE_BRAND_NAME", "Bad Guy Motors"),
        "support_email": getattr(settings, "SUPPORT_EMAIL", ""),
        "company_website": getattr(settings, "COMPANY_WEBSITE", ""),
        "company_phone": getattr(settings, "COMPANY_PHONE", ""),
    }
    if extra:
        context.update(extra)
    return {key: "" if value is None else str(value) for key, value in context.items()}


def _split_lines(value: str) -> list[str]:
    if not value:
        return []
    return [line.strip() for line in value.splitlines() if line.strip()]


def _format_value(value: str, context: dict[str, str]) -> str:
    if not value:
        return ""
    try:
        return value.format_map(_SafeDict(context))
    except Exception:
        return value


def _render_lines(lines: Iterable[str], context: dict[str, str]) -> list[str]:
    rendered = []
    for line in lines:
        formatted = _format_value(str(line), context).strip()
        if formatted:
            rendered.append(formatted)
    return rendered


def render_email_template(slug: str, context: dict[str, str]) -> RenderedEmailTemplate:
    definition = EMAIL_TEMPLATE_DEFINITIONS.get(slug)
    if not definition:
        raise ValueError(f"Unknown email template slug: {slug}")

    record = EmailTemplate.objects.filter(slug=slug).first()

    if record is None:
        subject_raw = definition.subject
        preheader_raw = definition.preheader
        title_raw = definition.title
        greeting_raw = definition.greeting
        intro_raw = "\n".join(definition.intro_lines)
        notice_title_raw = definition.notice_title
        notice_raw = "\n".join(definition.notice_lines)
        footer_raw = "\n".join(definition.footer_lines)
        cta_raw = definition.cta_label
    else:
        subject_raw = record.subject
        preheader_raw = record.preheader
        title_raw = record.title
        greeting_raw = record.greeting
        intro_raw = record.intro
        notice_title_raw = record.notice_title
        notice_raw = record.notice
        footer_raw = record.footer
        cta_raw = record.cta_label

    merged_context = {token: "" for token in (definition.tokens or [])}
    merged_context.update(context)

    subject = _format_value(subject_raw, merged_context)
    preheader = _format_value(preheader_raw, merged_context)
    title = _format_value(title_raw, merged_context)
    greeting = _format_value(greeting_raw, merged_context)
    intro_lines = _render_lines(_split_lines(intro_raw), merged_context)
    notice_title = _format_value(notice_title_raw, merged_context)
    notice_lines = _render_lines(_split_lines(notice_raw), merged_context)
    footer_lines = _render_lines(_split_lines(footer_raw), merged_context)
    cta_label = _format_value(cta_raw, merged_context)

    return RenderedEmailTemplate(
        subject=subject,
        preheader=preheader,
        title=title,
        greeting=greeting,
        intro_lines=intro_lines,
        notice_title=notice_title,
        notice_lines=notice_lines,
        footer_lines=footer_lines,
        cta_label=cta_label,
    )


def template_tokens(slug: str) -> list[str]:
    definition = EMAIL_TEMPLATE_DEFINITIONS.get(slug)
    if not definition:
        return []
    return list(definition.tokens or [])


def _as_lines(section: Iterable[str] | str | None) -> list[str]:
    if section is None:
        return []
    if isinstance(section, str):
        return [section] if section.strip() else []
    return [str(line) for line in section if str(line).strip()]


def join_text_sections(*sections: Iterable[str] | str | None) -> str:
    lines: list[str] = []
    for section in sections:
        section_lines = [line.strip() for line in _as_lines(section) if line.strip()]
        if not section_lines:
            continue
        if lines:
            lines.append("")
        lines.extend(section_lines)
    return "\n".join(lines)
