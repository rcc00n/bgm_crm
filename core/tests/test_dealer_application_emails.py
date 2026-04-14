from django.core import mail
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from core.models import DealerApplication, DealerTier, EmailSendLog
from core.services.dealer_application_emails import (
    send_dealer_application_approved,
    send_dealer_application_rejected,
    send_dealer_application_submitted,
)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="noreply@example.com",
)
class DealerApplicationEmailTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="alice",
            email="alice@example.com",
            password="pw",
        )
        self.app = DealerApplication.objects.create(
            user=self.user,
            business_name="Test Shop",
            phone="12345",
            email="dealer@example.com",
            preferred_tier=DealerTier.TIER_1,
        )

    def test_send_submitted_email(self):
        sent = send_dealer_application_submitted(self.app.pk)

        self.assertTrue(sent)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["dealer@example.com"])
        log = EmailSendLog.objects.get()
        self.assertTrue(log.success)
        self.assertEqual(log.email_type, "dealer_application_submitted")

    def test_send_approved_email(self):
        self.app.assigned_tier = DealerTier.TIER_1
        self.app.save(update_fields=["assigned_tier"])

        sent = send_dealer_application_approved(self.app.pk)

        self.assertTrue(sent)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["dealer@example.com"])
        log = EmailSendLog.objects.get()
        self.assertTrue(log.success)
        self.assertEqual(log.email_type, "dealer_application_approved")

    def test_send_rejected_email(self):
        sent = send_dealer_application_rejected(self.app.pk)

        self.assertTrue(sent)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["dealer@example.com"])
        log = EmailSendLog.objects.get()
        self.assertTrue(log.success)
        self.assertEqual(log.email_type, "dealer_application_rejected")
