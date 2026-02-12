from django.db import migrations


NO_REPLY_FOOTER = (
    "Please do not reply to this email. This message was sent from a no-reply address and replies are not monitored.\n"
    "For help, email {support_email}."
)

DEALER_SUBMITTED_FOOTER = (
    "If you need to update anything, email {support_email}.\n"
    "Please do not reply to this email. This message was sent from a no-reply address and replies are not monitored."
)


def apply_no_reply_copy(apps, schema_editor):
    EmailTemplate = apps.get_model("core", "EmailTemplate")

    # Update seeded templates that still include reply-to-this-email instructions.
    slugs = [
        "appointment_confirmation",
        "order_confirmation",
        "order_status_processing",
        "order_status_shipped",
        "order_status_completed",
        "order_status_cancelled",
        "abandoned_cart_1",
        "abandoned_cart_2",
        "abandoned_cart_3",
        "site_notice_welcome",
        "site_notice_followup_2",
        "site_notice_followup_3",
        "order_review_request",
    ]
    for slug in slugs:
        EmailTemplate.objects.filter(slug=slug, footer__icontains="reply to this email").update(
            footer=NO_REPLY_FOOTER
        )

    EmailTemplate.objects.filter(
        slug="order_status_cancelled", intro__icontains="reply to this email"
    ).update(intro="Your order was cancelled. If this is unexpected, email {support_email} and we'll help.")

    EmailTemplate.objects.filter(slug="abandoned_cart_2", intro__icontains="reply here").update(
        intro="Your cart is still saved. If you want help with fitment or shipping, email {support_email}."
    )

    # Seed dealer application templates so they are editable in admin like the others.
    dealer_templates = [
        {
            "slug": "dealer_application_submitted",
            "name": "Dealer application: submitted",
            "description": "Sent to applicants when a dealer application is submitted.",
            "subject": "{brand} dealer application received",
            "preheader": "We received your application and will review it shortly.",
            "title": "Application received",
            "greeting": "Hi {applicant_name},",
            "intro": "Thanks for applying to the {brand} dealer program.\nOur team received your application and will review it shortly.",
            "notice_title": "",
            "notice": "",
            "footer": DEALER_SUBMITTED_FOOTER,
            "cta_label": "View status",
            "cta_url": "",
        },
        {
            "slug": "dealer_application_approved",
            "name": "Dealer application: approved",
            "description": "Sent to applicants when a dealer application is approved.",
            "subject": "Welcome to {brand} Dealers",
            "preheader": "Your dealer access is now active.",
            "title": "You're approved",
            "greeting": "Hi {applicant_name},",
            "intro": "Congratulations, your dealer application has been approved.\nYour dealer access is now active.",
            "notice_title": "",
            "notice": "",
            "footer": NO_REPLY_FOOTER,
            "cta_label": "Open dealer portal",
            "cta_url": "",
        },
        {
            "slug": "dealer_application_rejected",
            "name": "Dealer application: declined",
            "description": "Sent to applicants when a dealer application is declined.",
            "subject": "{brand} dealer application update",
            "preheader": "Your application status has been updated.",
            "title": "Application update",
            "greeting": "Hi {applicant_name},",
            "intro": "Thanks for applying to the {brand} dealer program.\nAt this time we're not able to approve your application.",
            "notice_title": "",
            "notice": "",
            "footer": NO_REPLY_FOOTER,
            "cta_label": "View status",
            "cta_url": "",
        },
    ]

    for payload in dealer_templates:
        EmailTemplate.objects.get_or_create(slug=payload["slug"], defaults=payload)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0101_dealer_welcome_banner"),
    ]

    operations = [
        migrations.RunPython(apply_no_reply_copy, migrations.RunPython.noop),
    ]
