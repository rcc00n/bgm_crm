from datetime import timedelta

from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from store.models import AbandonedCart


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="noreply@example.com",
    COMPANY_WEBSITE="https://example.com",
    ABANDONED_CART_EMAIL_1_DELAY_HOURS=2,
    ABANDONED_CART_EMAIL_2_DELAY_HOURS=24,
    ABANDONED_CART_EMAIL_3_DELAY_HOURS=72,
)
class AbandonedCartEmailTests(TestCase):
    def test_abandoned_cart_followups_send(self):
        now = timezone.now()
        cart = AbandonedCart.objects.create(
            email="cart@example.com",
            cart_items=[{"name": "Brake Kit", "qty": 1, "line_total": "499.00"}],
            cart_total="499.00",
            last_activity_at=now - timedelta(hours=3),
        )

        call_command("send_abandoned_cart_emails")
        self.assertEqual(len(mail.outbox), 1)
        cart.refresh_from_db()
        self.assertIsNotNone(cart.email_1_sent_at)
        self.assertIsNone(cart.email_2_sent_at)

        mail.outbox.clear()
        cart.last_activity_at = now - timedelta(days=2)
        cart.email_1_sent_at = now - timedelta(hours=20)
        cart.save(update_fields=["last_activity_at", "email_1_sent_at"])

        call_command("send_abandoned_cart_emails")
        self.assertEqual(len(mail.outbox), 1)
        cart.refresh_from_db()
        self.assertIsNotNone(cart.email_2_sent_at)

        mail.outbox.clear()
        cart.last_activity_at = now - timedelta(days=4)
        cart.email_2_sent_at = now - timedelta(days=2)
        cart.save(update_fields=["last_activity_at", "email_2_sent_at"])

        call_command("send_abandoned_cart_emails")
        self.assertEqual(len(mail.outbox), 1)
        cart.refresh_from_db()
        self.assertIsNotNone(cart.email_3_sent_at)
